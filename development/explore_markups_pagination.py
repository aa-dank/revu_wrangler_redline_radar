"""
Explore the Session Markups endpoint to answer:

  "Do markup lists paginate? If yes, what are the pagination params
   (offset/limit, cursor, page/pageSize)? Need to test with a session
   that has a large number of markups."

This script:
  1. Authenticates with Bluebeam
  2. Fetches markups for a session (first page / default response)
  3. Inspects the response envelope for pagination fields
  4. If pagination exists, attempts a second fetch to verify navigation
  5. Logs field names, counts, and pagination mechanics
  6. Saves raw response + summary to development/output/

Usage:
    python explore_markups_pagination.py <session_id>
    python explore_markups_pagination.py 117-770-339
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from _auth_helper import get_authenticated_client

OUTPUT_DIR = Path(__file__).parent / "output"


def _fetch_markups(client, session_id: str, params: dict | None = None) -> dict | list:
    """Fetch markups, handling both SDK method and raw HTTP fallback."""
    try:
        return client.sessions.list_markups(session_id, **(params or {}))
    except (AttributeError, TypeError):
        # list_markups may not exist yet or may not accept kwargs — raw HTTP
        url = f"{client.base_url}/publicapi/v1/sessions/{session_id}/markups"
        resp = client.http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _extract_items(response) -> tuple[list, dict]:
    """
    Return (items_list, envelope_metadata).
    Handles bare list or wrapped envelope responses.
    """
    if isinstance(response, list):
        return response, {}

    for key in ["Markups", "markups", "Items", "items", "Records", "records", "Data", "data"]:
        if key in response and isinstance(response[key], list):
            envelope = {k: v for k, v in response.items() if k != key}
            return response[key], envelope

    # Couldn't find a list — return empty and the whole thing as envelope
    return [], dict(response) if isinstance(response, dict) else {}


def _find_pagination_fields(envelope: dict) -> dict:
    """Pull out anything that smells like pagination."""
    pagination = {}
    for key, value in envelope.items():
        lower = key.lower()
        if any(term in lower for term in [
            "page", "total", "count", "next", "cursor", "offset",
            "limit", "has_more", "hasmore", "skip", "continuation",
        ]):
            pagination[key] = value
    return pagination


def main():
    if len(sys.argv) < 2:
        print("Usage: python explore_markups_pagination.py <session_id>")
        print("Example: python explore_markups_pagination.py 117-770-339")
        sys.exit(1)

    session_id = sys.argv[1].strip()
    print(f"\n=== Exploring Markup Pagination for Session: {session_id} ===\n")

    client = get_authenticated_client()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Fetch 1 — default request (no pagination params)
    # -----------------------------------------------------------------------
    print("\n--- Fetch 1: Default (no pagination params) ---")
    try:
        resp1 = _fetch_markups(client, session_id)
    except Exception as e:
        print(f"  ERROR fetching markups: {e}")
        print("  This may indicate the endpoint path is different or requires beta access.")
        return

    raw_file = OUTPUT_DIR / f"markups_raw_default_{session_id}_{timestamp}.json"
    raw_file.write_text(json.dumps(resp1, indent=2, default=str))
    print(f"  Raw response saved to: {raw_file}")

    items1, envelope1 = _extract_items(resp1)
    pagination1 = _find_pagination_fields(envelope1)

    print(f"\n  Response type: {'bare list' if isinstance(resp1, list) else 'object envelope'}")
    if envelope1:
        print(f"  Envelope keys: {list(envelope1.keys())}")
    print(f"  Markup count (this response): {len(items1)}")

    if pagination1:
        print(f"\n  Pagination fields found:")
        for k, v in pagination1.items():
            print(f"    {k}: {v}")
    else:
        print(f"\n  No pagination fields detected in response envelope.")

    # Inspect first markup structure
    if items1:
        print(f"\n--- First markup fields ---")
        first = items1[0]
        for key, value in first.items():
            val_preview = str(value)[:100]
            print(f"  {key}: {val_preview}  (type: {type(value).__name__})")

    # -----------------------------------------------------------------------
    # Fetch 2 — attempt explicit pagination if there's signal
    # -----------------------------------------------------------------------
    print("\n--- Fetch 2: Probing pagination behavior ---")

    # Strategy: try common patterns and see what changes
    page_attempts = [
        {"label": "offset=0&limit=5", "params": {"offset": "0", "limit": "5"}},
        {"label": "page=1&pageSize=5", "params": {"page": "1", "pageSize": "5"}},
        {"label": "skip=0&take=5", "params": {"skip": "0", "take": "5"}},
    ]

    for attempt in page_attempts:
        print(f"\n  Trying: {attempt['label']}")
        try:
            resp2 = _fetch_markups(client, session_id, params=attempt["params"])
            items2, envelope2 = _extract_items(resp2)
            pagination2 = _find_pagination_fields(envelope2)

            print(f"    Status: OK")
            print(f"    Markup count: {len(items2)}")
            if len(items2) != len(items1):
                print(f"    *** Count differs from default ({len(items1)}) — pagination is working! ***")
            if pagination2:
                print(f"    Pagination fields: {pagination2}")
            if envelope2:
                print(f"    Envelope keys: {list(envelope2.keys())}")

            # Save this successful probe
            probe_file = OUTPUT_DIR / f"markups_probe_{attempt['label'].replace('&', '_').replace('=', '')}_{session_id}_{timestamp}.json"
            probe_file.write_text(json.dumps(resp2, indent=2, default=str))
            print(f"    Saved to: {probe_file}")

        except Exception as e:
            print(f"    Failed: {e}")

    # -----------------------------------------------------------------------
    # Fetch 3 — if we detected a 'next' cursor or URL, follow it
    # -----------------------------------------------------------------------
    next_url = None
    for key in ["Next", "next", "NextLink", "nextLink", "ContinuationToken", "continuationToken"]:
        if key in envelope1 and envelope1[key]:
            next_url = envelope1[key]
            break

    if next_url:
        print(f"\n--- Fetch 3: Following '{key}' = {next_url} ---")
        try:
            if next_url.startswith("http"):
                resp3 = client.http.get(next_url)
                resp3.raise_for_status()
                resp3_data = resp3.json()
            else:
                # It's a token — try passing as query param
                resp3_data = _fetch_markups(client, session_id, params={"cursor": next_url})
            items3, _ = _extract_items(resp3_data)
            print(f"  Next-page markup count: {len(items3)}")
            next_file = OUTPUT_DIR / f"markups_next_page_{session_id}_{timestamp}.json"
            next_file.write_text(json.dumps(resp3_data, indent=2, default=str))
            print(f"  Saved to: {next_file}")
        except Exception as e:
            print(f"  Failed to follow next page: {e}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    summary = {
        "session_id": session_id,
        "timestamp": timestamp,
        "default_markup_count": len(items1),
        "response_type": "bare list" if isinstance(resp1, list) else "object envelope",
        "envelope_keys": list(envelope1.keys()) if envelope1 else [],
        "pagination_fields": pagination1,
        "markup_field_names": list(items1[0].keys()) if items1 else [],
        "pagination_probes_tried": [a["label"] for a in page_attempts],
        "conclusion": (
            "Pagination detected — see pagination_fields"
            if pagination1
            else "No pagination envelope detected. Markups may be returned as a flat list."
        ),
    }
    summary_file = OUTPUT_DIR / f"markups_pagination_summary_{session_id}_{timestamp}.json"
    summary_file.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  Summary saved to: {summary_file}")
    print("\n=== Done ===\n")


if __name__ == "__main__":
    main()
