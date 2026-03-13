"""
Explore Bluebeam OAuth scope requirements to answer:

  "Can we use the read-only scope (read_prime) to access session markups
   and activities? Or does the app require full_user? If read_prime works,
   we should use the least-privilege scope."

This script:
  1. Authenticates with read_prime + offline_access scopes
  2. Attempts to call session, markups, and activities endpoints
  3. Records which calls succeed (200) and which fail (401/403)
  4. Reports whether read_prime is sufficient or full_user is needed
  5. Saves results to development/output/

IMPORTANT: This script forces a fresh OAuth login (ignores saved tokens)
because scope changes require a new authorization grant. Your browser
will open for a Bluebeam login.

Usage:
    python explore_scope_requirements.py <session_id>
    python explore_scope_requirements.py 117-770-339
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from _auth_helper import (
    get_authenticated_client,
    BLUEBEAM_CLIENT_ID,
    BLUEBEAM_CLIENT_SECRET,
    BLUEBEAM_REDIRECT_URI,
    BLUEBEAM_REGION,
    TOKEN_FILE,
    _run_oauth_flow,
    _validate_config,
)

# Lazy import — will be used for manual client construction
try:
    from revu_wrangler import BluebeamClient
except ImportError:
    print("ERROR: revu_wrangler is not installed.", file=sys.stderr)
    sys.exit(1)

OUTPUT_DIR = Path(__file__).parent / "output"


def _test_endpoint(client, label: str, url: str) -> dict:
    """
    Try a GET request and return result dict with status info.
    Does NOT raise on errors — captures them.
    """
    result = {"endpoint": label, "url": url}
    try:
        resp = client.http.get(url)
        result["status_code"] = resp.status_code
        result["success"] = resp.status_code == 200
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, list):
                result["item_count"] = len(body)
            elif isinstance(body, dict):
                # Try to find the data list
                for key in ["Items", "items", "Markups", "markups", "Activities", "activities",
                             "Records", "records", "Data", "data", "Users", "users"]:
                    if key in body and isinstance(body[key], list):
                        result["item_count"] = len(body[key])
                        break
                result["response_keys"] = list(body.keys())
        else:
            result["error"] = resp.text[:500]
    except Exception as e:
        result["status_code"] = None
        result["success"] = False
        result["error"] = str(e)
    return result


def _test_scope(scope_label: str, scopes: list[str], session_id: str) -> dict:
    """
    Authenticate with specified scopes and test all relevant endpoints.
    Returns a results dict.
    """
    print(f"\n{'='*60}")
    print(f"  Testing scope: {scope_label}  ({', '.join(scopes)})")
    print(f"{'='*60}")

    # Build a fresh client with the specified scopes
    _validate_config()
    client = BluebeamClient(
        client_id=BLUEBEAM_CLIENT_ID,
        client_secret=BLUEBEAM_CLIENT_SECRET,
        redirect_uri=BLUEBEAM_REDIRECT_URI,
        region=BLUEBEAM_REGION,
        scopes=scopes,
    )

    # Force fresh OAuth (scope change requires new grant)
    print(f"\n  Starting OAuth flow for scopes: {scopes}")
    print(f"  (Your browser will open — please log in to Bluebeam)")
    _run_oauth_flow(client)

    base = f"{client.base_url}/publicapi/v1"

    endpoints = [
        ("GET /sessions/{id}", f"{base}/sessions/{session_id}"),
        ("GET /sessions/{id}/users", f"{base}/sessions/{session_id}/users"),
        ("GET /sessions/{id}/activities", f"{base}/sessions/{session_id}/activities"),
        ("GET /sessions/{id}/markups", f"{base}/sessions/{session_id}/markups"),
        ("GET /sessions/{id}/snapshots", f"{base}/sessions/{session_id}/snapshots"),
    ]

    results = []
    for label, url in endpoints:
        print(f"\n  Testing: {label}")
        result = _test_endpoint(client, label, url)
        status = "✔ OK" if result["success"] else f"✘ {result.get('status_code', 'ERR')}"
        print(f"    {status}")
        if not result["success"] and result.get("error"):
            print(f"    Error: {result['error'][:200]}")
        if result.get("item_count") is not None:
            print(f"    Items: {result['item_count']}")
        results.append(result)

    return {
        "scope_label": scope_label,
        "scopes": scopes,
        "endpoints": results,
        "all_passed": all(r["success"] for r in results),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python explore_scope_requirements.py <session_id>")
        print("Example: python explore_scope_requirements.py 117-770-339")
        sys.exit(1)

    session_id = sys.argv[1].strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"  Scope Requirements Explorer")
    print(f"  Session: {session_id}")
    print(f"{'#'*60}")
    print()
    print("  This script tests two scope configurations:")
    print("    1. read_prime + offline_access  (least privilege)")
    print("    2. full_user + offline_access   (full access)")
    print()
    print("  Each test requires a fresh Bluebeam login (browser will open twice).")
    print("  If read_prime passes all endpoints, we can use the lesser scope.")

    # Back up existing tokens — we'll restore after
    saved_token_backup = None
    if TOKEN_FILE.exists():
        saved_token_backup = TOKEN_FILE.read_text()
        print(f"\n  (Backed up existing tokens from {TOKEN_FILE})")

    try:
        # Test 1: read_prime
        result_read = _test_scope(
            scope_label="read_prime",
            scopes=["read_prime", "offline_access"],
            session_id=session_id,
        )

        # Test 2: full_user
        result_full = _test_scope(
            scope_label="full_user",
            scopes=["full_user", "offline_access"],
            session_id=session_id,
        )

    finally:
        # Restore original tokens
        if saved_token_backup:
            TOKEN_FILE.write_text(saved_token_backup)
            print(f"\n  (Restored original tokens to {TOKEN_FILE})")

    # -----------------------------------------------------------------------
    # Compare results
    # -----------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"  RESULTS COMPARISON")
    print(f"{'='*60}")
    print()
    print(f"  {'Endpoint':<40} {'read_prime':<15} {'full_user':<15}")
    print(f"  {'-'*40} {'-'*15} {'-'*15}")

    for ep_read, ep_full in zip(result_read["endpoints"], result_full["endpoints"]):
        label = ep_read["endpoint"]
        read_status = "✔ OK" if ep_read["success"] else f"✘ {ep_read.get('status_code', 'ERR')}"
        full_status = "✔ OK" if ep_full["success"] else f"✘ {ep_full.get('status_code', 'ERR')}"
        print(f"  {label:<40} {read_status:<15} {full_status:<15}")

    # Recommendation
    print()
    if result_read["all_passed"]:
        recommendation = "read_prime is SUFFICIENT — use least-privilege scope."
        print(f"  ✔ RECOMMENDATION: {recommendation}")
    elif result_full["all_passed"]:
        recommendation = "full_user is REQUIRED — read_prime was denied for some endpoints."
        failed = [e["endpoint"] for e in result_read["endpoints"] if not e["success"]]
        print(f"  ✘ RECOMMENDATION: {recommendation}")
        print(f"    Endpoints that failed with read_prime: {failed}")
    else:
        recommendation = "NEITHER scope worked for all endpoints — check API access and session membership."
        print(f"  ⚠ RECOMMENDATION: {recommendation}")

    # -----------------------------------------------------------------------
    # Save summary
    # -----------------------------------------------------------------------
    summary = {
        "session_id": session_id,
        "timestamp": timestamp,
        "read_prime_results": result_read,
        "full_user_results": result_full,
        "recommendation": recommendation,
    }
    summary_file = OUTPUT_DIR / f"scope_requirements_{session_id}_{timestamp}.json"
    summary_file.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  Summary saved to: {summary_file}")
    print(f"\n{'#'*60}")
    print(f"  Done")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
