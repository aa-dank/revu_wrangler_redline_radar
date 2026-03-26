"""
Data fetching and aggregation layer for Bluebeam Studio Sessions.

This module handles:
  - Fetching session metadata
  - Building the attendance list from session activities
  - Building per-file markup summaries from the activity log

Where the ``revu_wrangler`` SDK doesn't yet have a method, we fall back
to raw HTTP requests using the client's ``http`` handle.

**API response conventions** (discovered via live testing 2026-03-13):
  - Envelope keys use Pascal-case prefixed with "Session":
    ``SessionActivities``, ``SessionUsers``, ``Files``, etc.
  - Most envelopes include a ``TotalCount`` field.
  - Activities paginate at 100 items per page; use ``?start=N`` to page.
  - Each activity has ``Id``, ``DocumentId``, ``UserId``, ``Message``,
    ``Created`` — there is *no* ``Type`` field; the ``Message`` string
    describes the action (e.g. ``"Joined Session"``, ``"Added Callout"``).
  - ``UserId`` is a numeric integer, not an email or name.
  - The ``/sessions/{id}/markups`` endpoint does **not** exist (404).
    Markup data must instead be derived from the activities feed.
"""

from __future__ import annotations

import re
from typing import Any

from revu_wrangler import BluebeamClient

from redline_radar.auth import ReauthenticationError, ensure_valid_client


# ---------------------------------------------------------------------------
# Type aliases for clarity
# ---------------------------------------------------------------------------

SessionInfo = dict[str, Any]
AttendeeRecord = dict[str, Any]
FileMarkupSummary = dict[str, Any]
AuthorStats = dict[str, Any]


# ---------------------------------------------------------------------------
# Activity message patterns
# ---------------------------------------------------------------------------

# Messages that indicate a user joined the session
_JOIN_MESSAGES = {"joined session"}

# Messages that indicate a markup was *added* (not edited, moved, or deleted).
# Pattern: "Added <markup-type>" or "Add <markup-type>"
_ADDED_PATTERN = re.compile(r"^(?:Added|Add)\s+(.+)$", re.IGNORECASE)

# Messages to exclude from markup-added counting even if they match the
# pattern above (file additions are not markups).
_ADDED_EXCLUSION_PATTERN = re.compile(r"^Added\s+'.*'$", re.IGNORECASE)

# Default page size returned by the activities endpoint.
_ACTIVITIES_PAGE_SIZE = 100


def _with_auth_retry(client: BluebeamClient, operation: Any) -> Any:
    """Run an API operation, retrying once after re-auth on auth failure."""
    try:
        return operation()
    except Exception as exc:
        msg = str(exc).lower()
        if "401" not in msg and "403" not in msg and "unauthorized" not in msg:
            raise

        try:
            ensure_valid_client(client)
        except ReauthenticationError as reauth_exc:
            raise reauth_exc from exc

        return operation()


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
    return _with_auth_retry(client, lambda: client.sessions.get_session(session_id))


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------

def fetch_session_files(
    client: BluebeamClient, session_id: str
) -> list[dict[str, Any]]:
    """
    Return the list of files in a session.

    Returns:
        List of file dicts, each with at least ``Id`` and ``Name``.
    """
    resp = _with_auth_retry(client, lambda: client.sessions.list_files(session_id))
    return _extract_list(resp, ["Files", "files", "SessionFiles", "Items", "items"])


# ---------------------------------------------------------------------------
# Users listing (for name resolution)
# ---------------------------------------------------------------------------

def _fetch_users_raw(
    client: BluebeamClient, session_id: str
) -> list[dict[str, Any]]:
    """
    Fetch the user/attendee list for a session.

    The API response envelope key is ``SessionUsers``.
    """
    try:
        resp = _with_auth_retry(
            client,
            lambda: client.sessions.list_users(session_id),  # type: ignore[attr-defined]
        )
    except AttributeError:
        url = f"{client.base_url}/publicapi/v1/sessions/{session_id}/users"
        http_resp = _with_auth_retry(client, lambda: client.http.get(url))
        http_resp.raise_for_status()
        resp = http_resp.json()

    return _extract_list(resp, ["SessionUsers", "Users", "users", "Items", "items"])


def _build_user_lookup(
    client: BluebeamClient, session_id: str
) -> dict[int, dict[str, str]]:
    """
    Build a ``{UserId: {"name": ..., "email": ...}}`` lookup from the
    session users list.
    """
    users = _fetch_users_raw(client, session_id)
    lookup: dict[int, dict[str, str]] = {}
    for u in users:
        uid = u.get("Id") or u.get("id") or u.get("UserId")
        if uid is None:
            continue
        uid = int(uid)
        name = (
            u.get("Name")
            or u.get("name")
            or u.get("DisplayName")
            or u.get("Email")
            or u.get("email")
            or str(uid)
        )
        email = u.get("Email") or u.get("email") or ""
        lookup[uid] = {"name": name, "email": email}
    return lookup


# ---------------------------------------------------------------------------
# Activities (with pagination)
# ---------------------------------------------------------------------------

def _fetch_all_activities(
    client: BluebeamClient, session_id: str
) -> list[dict[str, Any]]:
    """
    Fetch *all* session activities, handling pagination.

    The API returns up to 100 activities per page.  The response includes
    a ``TotalCount`` field indicating the total number of activities.
    We page through using ``?start=N`` until we have them all.
    """
    all_activities: list[dict[str, Any]] = []
    start = 0

    while True:
        try:
            resp = _with_auth_retry(
                client,
                lambda: client.sessions.list_activities(  # type: ignore[attr-defined]
                    session_id, start=start
                ),
            )
        except (AttributeError, TypeError):
            # SDK method doesn't exist or doesn't accept start — raw HTTP
            url = f"{client.base_url}/publicapi/v1/sessions/{session_id}/activities"
            params: dict[str, Any] = {}
            if start > 0:
                params["start"] = start
            http_resp = _with_auth_retry(
                client, lambda: client.http.get(url, params=params)
            )
            http_resp.raise_for_status()
            resp = http_resp.json()

        page = _extract_list(
            resp, ["SessionActivities", "Activities", "activities", "Items", "items"]
        )
        if not page:
            break

        all_activities.extend(page)

        # Check if we have all items
        total_count = (
            resp.get("TotalCount")
            if isinstance(resp, dict)
            else None
        )
        if total_count is not None and len(all_activities) >= int(total_count):
            break

        # If this page was smaller than the page size, we're done
        if len(page) < _ACTIVITIES_PAGE_SIZE:
            break

        start += len(page)

    return all_activities


# ---------------------------------------------------------------------------
# Attendance from activities
# ---------------------------------------------------------------------------

def build_attendance(
    client: BluebeamClient, session_id: str
) -> list[AttendeeRecord]:
    """
    Build the attendance list: one record per user who has entered the session.

    Uses the activities feed to find "Joined Session" events, then resolves
    user IDs to names/emails via the session users endpoint.

    Returns:
        Sorted list of dicts with ``name``, ``email``, ``first_seen`` keys.
    """
    # Fetch the users list for name resolution
    user_lookup = _build_user_lookup(client, session_id)

    # Fetch all activities
    try:
        activities = _fetch_all_activities(client, session_id)
    except Exception:
        activities = []

    if activities:
        attendance = _attendance_from_activities(activities, user_lookup)
        if attendance:
            return attendance

    # Fallback — users list without join timestamps
    if user_lookup:
        return _attendance_from_user_lookup(user_lookup)

    return []


def _attendance_from_activities(
    activities: list[dict[str, Any]],
    user_lookup: dict[int, dict[str, str]],
) -> list[AttendeeRecord]:
    """
    Extract the first "Joined Session" event per user from the activities list.

    The actual API schema uses:
      - ``Message``: free-text string like ``"Joined Session"``
      - ``UserId``: integer user identifier
      - ``Created``: ISO-8601 timestamp
    """
    first_seen: dict[int, AttendeeRecord] = {}

    for activity in activities:
        message = str(activity.get("Message", "")).strip().lower()
        if message not in _JOIN_MESSAGES:
            continue

        user_id = activity.get("UserId")
        if user_id is None:
            continue
        user_id = int(user_id)

        created = activity.get("Created", "")

        if user_id not in first_seen or (
            created and created < first_seen[user_id]["first_seen"]
        ):
            user_info = user_lookup.get(user_id, {})
            first_seen[user_id] = {
                "name": user_info.get("name", str(user_id)),
                "email": user_info.get("email", ""),
                "first_seen": created or "N/A",
            }

    return sorted(first_seen.values(), key=lambda x: str(x.get("first_seen", "")))


def _attendance_from_user_lookup(
    user_lookup: dict[int, dict[str, str]],
) -> list[AttendeeRecord]:
    """Fallback: build attendance from the users list (no timestamps)."""
    records: list[AttendeeRecord] = []
    for _uid, info in user_lookup.items():
        records.append({
            "name": info.get("name", "Unknown"),
            "email": info.get("email", ""),
            "first_seen": "N/A",
        })
    return sorted(records, key=lambda x: x.get("name", "").lower())


# ---------------------------------------------------------------------------
# Markup summary per file — derived from activities
# ---------------------------------------------------------------------------

def build_markup_summary(
    client: BluebeamClient,
    session_id: str,
    files: list[dict[str, Any]],
    *,
    on_progress: Any | None = None,
) -> list[FileMarkupSummary]:
    """
    For each file in the session, summarise markup activity from the activity
    log, grouped by user.

    Since the ``/sessions/{id}/markups`` endpoint does not exist (404),
    we derive markup information from the activities feed.  An activity
    counts as a "markup added" when its ``Message`` matches patterns like
    ``"Added Callout"``, ``"Add Cloud+"``, etc.  Each activity also carries
    a ``DocumentId`` linking it to a specific file.

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
    # Fetch the users list for name resolution
    user_lookup = _build_user_lookup(client, session_id)

    # Fetch all activities once (already paginated)
    try:
        all_activities = _fetch_all_activities(client, session_id)
    except Exception:
        all_activities = []

    # Index activities by DocumentId for fast lookup
    activities_by_doc: dict[int, list[dict[str, Any]]] = {}
    for activity in all_activities:
        doc_id = activity.get("DocumentId")
        if doc_id is not None and int(doc_id) != -1:
            activities_by_doc.setdefault(int(doc_id), []).append(activity)

    result: list[FileMarkupSummary] = []

    for file_info in files:
        file_id = str(file_info.get("Id", file_info.get("id", "")))
        file_name = file_info.get("Name", file_info.get("name", f"File {file_id}"))

        # Find markup-add activities for this file
        file_activities = activities_by_doc.get(int(file_id), []) if file_id else []
        author_stats: dict[int, AuthorStats] = {}

        for activity in file_activities:
            message = str(activity.get("Message", ""))

            # Is this an "Added <markup>" or "Add <markup>" event?
            if not _ADDED_PATTERN.match(message):
                continue
            # Exclude file additions like "Added 'filename.pdf'"
            if _ADDED_EXCLUSION_PATTERN.match(message):
                continue

            user_id = activity.get("UserId")
            if user_id is None:
                continue
            user_id = int(user_id)

            created = activity.get("Created", "")
            user_info = user_lookup.get(user_id, {})
            author_name = user_info.get("name", str(user_id))

            if user_id not in author_stats:
                author_stats[user_id] = {
                    "name": author_name,
                    "count": 0,
                    "latest_date": created,
                }
            author_stats[user_id]["count"] += 1
            if created and (
                not author_stats[user_id]["latest_date"]
                or created > author_stats[user_id]["latest_date"]
            ):
                author_stats[user_id]["latest_date"] = created

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
