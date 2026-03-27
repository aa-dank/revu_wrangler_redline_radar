"""DataFrame-based activity analysis used by both report and workbook output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from redline_radar.activity_signals import classify_activity


@dataclass
class SessionActivityAnalysis:
    """Canonical analyzed session activity dataset and derived report records."""

    raw_df: pd.DataFrame
    activities_df: pd.DataFrame
    attendance: list[dict[str, Any]]
    file_summary: list[dict[str, Any]]
    unknown_messages: list[str]


def build_session_activity_analysis(
    *,
    activities: list[dict[str, Any]],
    users: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> SessionActivityAnalysis:
    """Normalize raw session activity data into DataFrames and report records."""
    raw_df = pd.DataFrame(activities)
    if raw_df.empty:
        raw_df = pd.DataFrame(columns=["Id", "DocumentId", "UserId", "Message", "Created"])

    activities_df = raw_df.copy()
    activities_df["activity_id"] = _to_nullable_int(activities_df.get("Id"))
    activities_df["document_id"] = _to_nullable_int(activities_df.get("DocumentId"))
    activities_df["user_id"] = _to_nullable_int(activities_df.get("UserId"))
    activities_df["message"] = activities_df.get("Message", pd.Series(dtype="object")).fillna("").astype(str)
    activities_df["created"] = activities_df.get("Created", pd.Series(dtype="object")).fillna("").astype(str)
    activities_df["created_at"] = pd.to_datetime(activities_df["created"], utc=True, errors="coerce")
    activities_df["has_document_context"] = activities_df["document_id"].notna() & (activities_df["document_id"] != -1)

    users_df = _build_users_df(users)
    files_df = _build_files_df(files)

    activities_df = activities_df.merge(users_df, on="user_id", how="left")
    activities_df = activities_df.merge(files_df, on="document_id", how="left")

    classification_df = pd.DataFrame(
        [
            classify_activity(message=row.message, document_id=_as_python_int(row.document_id))
            for row in activities_df.itertuples(index=False)
        ]
    )
    activities_df = pd.concat([activities_df.reset_index(drop=True), classification_df], axis=1)
    activities_df["user_name"] = activities_df.get("user_name", pd.Series(dtype="object")).fillna(activities_df["user_id"].astype("string"))
    activities_df["user_email"] = activities_df.get("user_email", pd.Series(dtype="object")).fillna("")
    activities_df["file_name"] = activities_df.get("file_name", pd.Series(dtype="object")).fillna("")

    attendance = _build_attendance_records(activities_df, users_df)
    file_summary = _build_file_summary(activities_df, files_df)
    unknown_messages = sorted(
        {
            message
            for message in activities_df.loc[
                activities_df["activity_signal"] == "unclassified", "message"
            ].dropna()
            if message
        }
    )

    return SessionActivityAnalysis(
        raw_df=raw_df,
        activities_df=activities_df,
        attendance=attendance,
        file_summary=file_summary,
        unknown_messages=unknown_messages,
    )


def _build_users_df(users: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for user in users:
        user_id = user.get("Id") or user.get("id") or user.get("UserId")
        if user_id is None:
            continue
        rows.append(
            {
                "user_id": _coerce_int(user_id),
                "user_name": (
                    user.get("Name")
                    or user.get("name")
                    or user.get("DisplayName")
                    or user.get("Email")
                    or user.get("email")
                    or str(user_id)
                ),
                "user_email": user.get("Email") or user.get("email") or "",
            }
        )
    if not rows:
        return pd.DataFrame(columns=["user_id", "user_name", "user_email"])
    users_df = pd.DataFrame(rows)
    users_df["user_id"] = _to_nullable_int(users_df["user_id"])
    return users_df.drop_duplicates(subset=["user_id"])


def _build_files_df(files: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for file_info in files:
        file_id = file_info.get("Id") or file_info.get("id")
        if file_id is None:
            continue
        rows.append(
            {
                "document_id": _coerce_int(file_id),
                "file_id": str(file_id),
                "file_name": file_info.get("Name") or file_info.get("name") or f"File {file_id}",
            }
        )
    if not rows:
        return pd.DataFrame(columns=["document_id", "file_id", "file_name"])
    files_df = pd.DataFrame(rows)
    files_df["document_id"] = _to_nullable_int(files_df["document_id"])
    return files_df.drop_duplicates(subset=["document_id"])


def _build_attendance_records(
    activities_df: pd.DataFrame,
    users_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    join_df = activities_df.loc[
        activities_df["activity_signal"] == "attendee.joined_session"
    ].copy()

    if not join_df.empty:
        join_df = join_df.sort_values(by=["created_at", "created"], na_position="last")
        first_seen_df = join_df.drop_duplicates(subset=["user_id"], keep="first")
        first_seen_df = first_seen_df.sort_values(by=["created_at", "created"], na_position="last")
        return [
            {
                "name": row.user_name if row.user_name else str(row.user_id),
                "email": row.user_email or "",
                "first_seen": row.created or "N/A",
            }
            for row in first_seen_df.itertuples(index=False)
            if row.user_id is not pd.NA
        ]

    if users_df.empty:
        return []

    fallback_df = users_df.sort_values(by=["user_name", "user_email"], na_position="last")
    return [
        {
            "name": row.user_name or "Unknown",
            "email": row.user_email or "",
            "first_seen": "N/A",
        }
        for row in fallback_df.itertuples(index=False)
    ]


def _build_file_summary(
    activities_df: pd.DataFrame,
    files_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    markup_df = activities_df.loc[
        activities_df["is_markup_activity"]
        & activities_df["document_id"].notna()
        & (activities_df["document_id"] != -1)
    ].copy()

    if not markup_df.empty:
        author_counts_df = (
            markup_df.groupby(
                ["document_id", "file_name", "user_id", "user_name", "user_email"],
                dropna=False,
            )
            .agg(
                count=("activity_id", "size"),
                latest_date=("created", "max"),
            )
            .reset_index()
            .sort_values(by=["latest_date", "count"], ascending=[False, False])
        )
    else:
        author_counts_df = pd.DataFrame(
            columns=["document_id", "file_name", "user_id", "user_name", "user_email", "count", "latest_date"]
        )

    summary: list[dict[str, Any]] = []
    for row in files_df.sort_values(by=["file_name"]).itertuples(index=False):
        author_rows = author_counts_df.loc[author_counts_df["document_id"] == row.document_id]
        markup_authors = [
            {
                "name": author_row.user_name if author_row.user_name else str(author_row.user_id),
                "count": int(author_row.count),
                "latest_date": author_row.latest_date or "",
            }
            for author_row in author_rows.itertuples(index=False)
        ]
        summary.append(
            {
                "name": row.file_name,
                "file_id": row.file_id,
                "markup_authors": markup_authors,
            }
        )
    return summary


def _to_nullable_int(series: Any) -> pd.Series:
    if series is None:
        return pd.Series(dtype="Int64")
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_python_int(value: Any) -> int | None:
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None