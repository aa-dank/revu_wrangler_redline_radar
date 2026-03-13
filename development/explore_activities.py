"""
Explore the Session Activities endpoint to answer:

  "What are the exact Type values returned by the activities endpoint?
   Need to test to determine filtering logic."

This script:
  1. Authenticates with Bluebeam
  2. Fetches all activities for a given session
  3. Prints the raw response to inspect field names
  4. Summarizes unique activity types and their field structures
  5. Saves raw response + summary to development/output/

Usage:
    python explore_activities.py <session_id>
    python explore_activities.py 117-770-339
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from _auth_helper import get_authenticated_client

OUTPUT_DIR = Path(__file__).parent / "output"


def main():
    if len(sys.argv) < 2:
        print("Usage: python explore_activities.py <session_id>")
        print("Example: python explore_activities.py 117-770-339")
        sys.exit(1)

    session_id = sys.argv[1].strip()
    print(f"\n=== Exploring Activities for Session: {session_id} ===\n")

    client = get_authenticated_client()

    # -----------------------------------------------------------------------
    # Fetch activities
    # -----------------------------------------------------------------------
    print("\n--- Fetching activities ---")
    try:
        activities_resp = client.sessions.list_activities(session_id)
    except AttributeError:
        # list_activities may not exist yet in revu_wrangler — fall back to raw HTTP
        print("  list_activities() not found on client.sessions — using raw HTTP call")
        url = f"{client.base_url}/publicapi/v1/sessions/{session_id}/activities"
        resp = client.http.get(url)
        resp.raise_for_status()
        activities_resp = resp.json()

    # -----------------------------------------------------------------------
    # Save raw response
    # -----------------------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_file = OUTPUT_DIR / f"activities_raw_{session_id}_{timestamp}.json"
    raw_file.write_text(json.dumps(activities_resp, indent=2, default=str))
    print(f"  Raw response saved to: {raw_file}")

    # -----------------------------------------------------------------------
    # Analyze the response
    # -----------------------------------------------------------------------
    print("\n--- Response envelope keys ---")
    print(f"  Top-level keys: {list(activities_resp.keys())}")

    # Try to find the activities list (could be under various keys)
    activities = []
    for key in ["Activities", "activities", "Items", "items", "Records", "records"]:
        if key in activities_resp and isinstance(activities_resp[key], list):
            activities = activities_resp[key]
            print(f"  Activities found under key: '{key}'")
            break
    else:
        # Maybe the response IS the list
        if isinstance(activities_resp, list):
            activities = activities_resp
            print("  Response is a bare list (no envelope)")
        else:
            print("  WARNING: Could not locate activities list in response!")
            print(f"  Full response: {json.dumps(activities_resp, indent=2, default=str)[:2000]}")

    print(f"\n  Total activities returned: {len(activities)}")

    if not activities:
        print("\n  No activities found. Is this session active with users?")
        return

    # -----------------------------------------------------------------------
    # Inspect field names on first activity
    # -----------------------------------------------------------------------
    print("\n--- Fields on first activity ---")
    first = activities[0]
    for key, value in first.items():
        val_preview = str(value)[:100]
        print(f"  {key}: {val_preview}  (type: {type(value).__name__})")

    # -----------------------------------------------------------------------
    # Unique activity types
    # -----------------------------------------------------------------------
    # Try common field names for "type"
    type_field = None
    for candidate in ["Type", "type", "ActivityType", "activityType", "Action", "action"]:
        if candidate in first:
            type_field = candidate
            break

    if type_field:
        type_counts = Counter(a.get(type_field) for a in activities)
        print(f"\n--- Unique activity types (field: '{type_field}') ---")
        for activity_type, count in type_counts.most_common():
            print(f"  {activity_type}: {count} occurrences")

        # Show one example of each type
        print(f"\n--- Example of each activity type ---")
        seen_types = set()
        for a in activities:
            atype = a.get(type_field)
            if atype not in seen_types:
                seen_types.add(atype)
                print(f"\n  [{atype}]")
                print(f"  {json.dumps(a, indent=4, default=str)}")
    else:
        print("\n  WARNING: Could not identify a 'type' field.")
        print(f"  Available fields: {list(first.keys())}")
        print(f"\n  First 3 activities:")
        for a in activities[:3]:
            print(f"  {json.dumps(a, indent=4, default=str)}")

    # -----------------------------------------------------------------------
    # Check for user identification fields
    # -----------------------------------------------------------------------
    print("\n--- User identification fields ---")
    user_fields = [k for k in first.keys() if any(
        term in k.lower() for term in ["user", "email", "name", "author", "actor"]
    )]
    print(f"  User-related fields found: {user_fields}")
    if user_fields:
        for field in user_fields:
            unique_values = set(str(a.get(field)) for a in activities)
            print(f"  '{field}' unique values ({len(unique_values)}): {list(unique_values)[:10]}")

    # -----------------------------------------------------------------------
    # Check for timestamp fields
    # -----------------------------------------------------------------------
    print("\n--- Timestamp fields ---")
    time_fields = [k for k in first.keys() if any(
        term in k.lower() for term in ["time", "date", "created", "when", "stamp"]
    )]
    print(f"  Timestamp fields found: {time_fields}")
    if time_fields:
        for field in time_fields:
            sample_values = [str(a.get(field)) for a in activities[:3]]
            print(f"  '{field}' samples: {sample_values}")

    # -----------------------------------------------------------------------
    # Check for pagination indicators
    # -----------------------------------------------------------------------
    print("\n--- Pagination indicators ---")
    pagination_fields = [k for k in activities_resp.keys() if any(
        term in k.lower() for term in ["page", "total", "count", "next", "cursor", "offset", "limit"]
    )]
    if pagination_fields:
        for field in pagination_fields:
            print(f"  '{field}': {activities_resp[field]}")
    else:
        print("  No pagination fields found in response envelope")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    summary = {
        "session_id": session_id,
        "timestamp": timestamp,
        "total_activities": len(activities),
        "envelope_keys": list(activities_resp.keys()),
        "activity_field_names": list(first.keys()) if activities else [],
        "type_field": type_field,
        "unique_types": dict(Counter(a.get(type_field) for a in activities)) if type_field else {},
        "user_fields": user_fields,
        "time_fields": time_fields,
        "pagination_fields": {k: activities_resp[k] for k in pagination_fields} if pagination_fields else {},
    }
    summary_file = OUTPUT_DIR / f"activities_summary_{session_id}_{timestamp}.json"
    summary_file.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  Summary saved to: {summary_file}")
    print("\n=== Done ===\n")


if __name__ == "__main__":
    main()
