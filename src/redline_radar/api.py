"""
Data fetching and aggregation layer for Bluebeam Studio Sessions.

This module handles:
  - Fetching session metadata
  - Building the attendance list from session activities
  - Building per-file markup summaries

Where the ``revu_wrangler`` SDK doesn't yet have a method, we fall back
to raw HTTP requests using the client's ``http`` handle (the same pattern
used in ``development/explore_activities.py``).
"""

from __future__ import annotations

from typing import Any

from revu_wrangler import BluebeamClient


# ---------------------------------------------------------------------------
# Type aliases for clarity
# ---------------------------------------------------------------------------

SessionInfo = dict[str, Any]
AttendeeRecord = dict[str, Any]
FileMarkupSummary = dict[str, Any]
AuthorStats = dict[str, Any]


# ---------------------------------------------------------------------------
# Session info
# ---------------------------------------------------------------------------

def fetch_session_info(client: BluebeamClient, session_id: str) -> SessionInfo:
    """
    Fetch metadata for a single session.

    Uses ``client.sessions.get_session()`` which is already in the SDK.

    Returns:
        Session dict with at least ``Id``, ``Name``, ``Status`` fields.
    """
    return client.sessions.get_session(session_id)


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------

def fetch_session_files(
    client: BluebeamClient, session_id: str
) -> list[dict[str, Any]]:
    """
    Return the list of files in a session.

    The SDK's ``list_files()`` returns an envelope like
    ``{"Files": [...]}`` or a bare list.

    Returns:
        List of file dicts, each with at least ``Id`` and ``Name``.
    """
    resp = client.sessions.list_files(session_id)
    return _extract_list(resp, ["Files", "files", "Items", "items"])


# ---------------------------------------------------------------------------
# Attendance from activities
# ---------------------------------------------------------------------------

def _fetch_activities_raw(
    client: BluebeamClient, session_id: str
) -> list[dict[str, Any]]:
    """
    Fetch all session activities, using raw HTTP as a fallback.

    The activities endpoint may not be wrapped by the SDK yet.
    """
    try:
        resp = client.sessions.list_activities(session_id)  # type: ignore[attr-defined]
    except AttributeError:
        # SDK method does not exist yet — raw HTTP fallback
        url = f"{client.base_url}/publicapi/v1/sessions/{session_id}/activities"
        http_resp = client.http.get(url)
        http_resp.raise_for_status()
        resp = http_resp.json()

    return _extract_list(
        resp,
        ["Activities", "activities", "Items", "items", "Records", "records"],
    )


def _fetch_users_raw(
    client: BluebeamClient, session_id: str
) -> list[dict[str, Any]]:
    """
    Fetch the user/attendee list for a session (raw HTTP fallback).
    """
    try:
        resp = client.sessions.list_users(session_id)  # type: ignore[attr-defined]
    except AttributeError:
        url = f"{client.base_url}/publicapi/v1/sessions/{session_id}/users"
        http_resp = client.http.get(url)
        http_resp.raise_for_status()
        resp = http_resp.json()

    return _extract_list(resp, ["Users", "users", "Items", "items"])


def build_attendance(
    client: BluebeamClient, session_id: str
) -> list[AttendeeRecord]:
    """
    Build the attendance list: one record per user who has entered the session.

    Primary strategy: parse the activities feed for join events and take the
    *first* join timestamp per user.

    Fallback: if activities can't provide join timestamps, use the users list
    (which at minimum tells us who is in the session, even without timestamps).

    Returns:
        Sorted list of dicts with ``name``, ``email``, ``first_seen`` keys.
    """
    try:
        activities = _fetch_activities_raw(client, session_id)
        attendance = _attendance_from_activities(activities)
        if attendance:
            return attendance
    except Exception:
        pass

    # Fallback — users list without timestamps
    try:
        users = _fetch_users_raw(client, session_id)
        return _attendance_from_users(users)
    except Exception:
        return []


def _attendance_from_activities(
    activities: list[dict[str, Any]],
) -> list[AttendeeRecord]:
    """
    Extract the first join event per user from an activities list.

    Handles multiple possible field names since the exact schema is
    not fully documented.
    """
    # Identify the type field
    type_field = _find_field(
        activities, ["Type", "type", "ActivityType", "activityType", "Action", "action"]
    )
    # Identify user field
    user_field = _find_field(
        activities, ["User", "user", "Email", "email", "Actor", "actor"]
    )
    # Identify name field
    name_field = _find_field(
        activities, ["UserName", "userName", "Name", "name", "ActorName", "actorName"]
    )
    # Identify timestamp field
    time_field = _find_field(
        activities,
        ["Timestamp", "timestamp", "Created", "created", "Date", "date", "When", "when"],
    )

    if not type_field or not time_field:
        return []

    # Join-type values to look for (case-insensitive comparison)
    join_types = {"userjoined", "join", "joined", "user_joined", "sessionjoin"}

    first_seen: dict[str, AttendeeRecord] = {}
    for activity in activities:
        activity_type = str(activity.get(type_field, "")).lower().strip()
        if activity_type not in join_types:
            continue

        user_key = activity.get(user_field or "User") or activity.get("Email", "")
        if not user_key:
            continue

        timestamp = activity.get(time_field, "")
        user_name = activity.get(name_field or "UserName", user_key)

        if user_key not in first_seen or (
            timestamp and timestamp < first_seen[user_key]["first_seen"]
        ):
            first_seen[user_key] = {
                "name": user_name,
                "email": str(user_key),
                "first_seen": timestamp or "N/A",
            }

    return sorted(first_seen.values(), key=lambda x: str(x.get("first_seen", "")))


def _attendance_from_users(
    users: list[dict[str, Any]],
) -> list[AttendeeRecord]:
    """Fallback: build attendance from the users list (no timestamps)."""
    records: list[AttendeeRecord] = []
    for user in users:
        name = (
            user.get("Name")
            or user.get("name")
            or user.get("Email")
            or user.get("email")
            or "Unknown"
        )
        email = user.get("Email") or user.get("email") or ""
        records.append({
            "name": name,
            "email": email,
            "first_seen": "N/A",
        })
    return sorted(records, key=lambda x: x.get("name", "").lower())


# ---------------------------------------------------------------------------
# Markup summary per file
# ---------------------------------------------------------------------------

def _fetch_markups_for_file(
    client: BluebeamClient, session_id: str, file_id: str
) -> list[dict[str, Any]]:
    """
    Fetch markups for a single file in a session.

    The markup endpoint is Beta and may not be in the SDK.
    We try the SDK method first, then fall back to raw HTTP with
    several candidate URL patterns.
    """
    # Try SDK method
    try:
        resp = client.sessions.list_markups(session_id, file_id)  # type: ignore[attr-defined]
        return _extract_list(resp, ["Markups", "markups", "Items", "items"])
    except AttributeError:
        pass

    # Raw HTTP fallback — try candidate URL patterns
    candidate_urls = [
        f"{client.base_url}/publicapi/v1/sessions/{session_id}/files/{file_id}/markups",
        f"{client.base_url}/publicapi/v1/sessions/{session_id}/markups",
    ]

    for url in candidate_urls:
        try:
            http_resp = client.http.get(url)
            if http_resp.status_code == 200:
                resp = http_resp.json()
                return _extract_list(
                    resp, ["Markups", "markups", "Items", "items", "Data", "data"]
                )
        except Exception:
            continue

    return []


def build_markup_summary(
    client: BluebeamClient,
    session_id: str,
    files: list[dict[str, Any]],
    *,
    on_progress: Any | None = None,
) -> list[FileMarkupSummary]:
    """
    For each file in the session, fetch markups and aggregate by author.

    Args:
        client: Authenticated BluebeamClient.
        session_id: The session ID.
        files: List of file dicts from :func:`fetch_session_files`.
        on_progress: Optional callback called after each file is processed
            (for progress bar updates).

    Returns:
        List of dicts, each with:
          - ``name``: file name
          - ``file_id``: file ID
          - ``markup_authors``: list of ``{name, count, latest_date}``
    """
    result: list[FileMarkupSummary] = []

    for file_info in files:
        file_id = str(file_info.get("Id", file_info.get("id", "")))
        file_name = file_info.get("Name", file_info.get("name", f"File {file_id}"))

        try:
            markups = _fetch_markups_for_file(client, session_id, file_id)
        except Exception:
            # Beta endpoint failure — degrade gracefully
            markups = []

        author_stats: dict[str, AuthorStats] = {}
        for markup in markups:
            author = (
                markup.get("Author")
                or markup.get("author")
                or markup.get("AuthorEmail")
                or "Unknown"
            )
            date = (
                markup.get("Date")
                or markup.get("date")
                or markup.get("ModifiedDate")
                or markup.get("modifiedDate")
                or ""
            )
            if author not in author_stats:
                author_stats[author] = {
                    "name": author,
                    "count": 0,
                    "latest_date": date,
                }
            author_stats[author]["count"] += 1
            if date and (
                not author_stats[author]["latest_date"]
                or date > author_stats[author]["latest_date"]
            ):
                author_stats[author]["latest_date"] = date

        result.append({
            "name": file_name,
            "file_id": file_id,
            "markup_authors": sorted(
                author_stats.values(),
                key=lambda x: x.get("latest_date", ""),
                reverse=True,
            ),
        })

        if on_progress is not None:
            on_progress()

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_list(
    resp: Any, candidate_keys: list[str]
) -> list[dict[str, Any]]:
    """
    Extract the data list from an API response that may be a bare list
    or an envelope with the data under one of several possible keys.
    """
    if isinstance(resp, list):
        return resp

    if isinstance(resp, dict):
        for key in candidate_keys:
            if key in resp and isinstance(resp[key], list):
                return resp[key]

    return []


def _find_field(
    items: list[dict[str, Any]], candidates: list[str]
) -> str | None:
    """
    Given a list of dicts, find which of the candidate field names
    is actually present in the first item.
    """
    if not items:
        return None
    first = items[0]
    for name in candidates:
        if name in first:
            return name
    return None
