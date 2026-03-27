"""Export full session activity data to a workbook using the shared core pipeline."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from _auth_helper import get_authenticated_client
from redline_radar.activity_analysis import build_session_activity_analysis
from redline_radar.activity_workbook import export_activity_workbook
from redline_radar.api import fetch_session_activities, fetch_session_files, fetch_session_users

OUTPUT_DIR = Path(__file__).parent / "output"


def main():
    if len(sys.argv) < 2:
        print("Usage: python export_session_activities_excel.py <session_id>")
        print("Example: python export_session_activities_excel.py 117-770-339")
        sys.exit(1)

    session_id = sys.argv[1].strip()
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    print(f"\n=== Exporting activities workbook for session: {session_id} ===\n")
    client = get_authenticated_client(scopes=["full_user", "offline_access"])

    print("--- Fetching session data ---")
    files = fetch_session_files(client, session_id)
    users = fetch_session_users(client, session_id)
    activities = fetch_session_activities(client, session_id)
    analysis = build_session_activity_analysis(
        activities=activities,
        users=users,
        files=files,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT_DIR / f"activities_raw_{session_id}_{timestamp}.json"
    workbook_path = OUTPUT_DIR / f"activities_export_{session_id}_{timestamp}.xlsx"

    raw_path.write_text(json.dumps({"SessionActivities": activities}, indent=2, default=str), encoding="utf-8")
    export_activity_workbook(
        raw_df=analysis.raw_df,
        activities_df=analysis.activities_df,
        output_path=workbook_path,
    )

    print(f"  Activities returned: {len(analysis.activities_df)}")
    print(f"  Raw JSON saved to: {raw_path}")
    print(f"  Workbook saved to: {workbook_path}")
    print("\n=== Done ===\n")


if __name__ == "__main__":
    main()