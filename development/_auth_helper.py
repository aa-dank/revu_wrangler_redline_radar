"""
Shared authentication helper for development/exploration scripts.

Handles:
  - Loading credentials from .env via python-dotenv
  - OAuth Authorization Code flow with a local callback server
  - Token persistence to tokens.json for reuse across runs
  - Automatic token refresh when expired

Usage:
    from _auth_helper import get_authenticated_client
    client = get_authenticated_client()
"""

import json
import os
import sys
import time
import webbrowser
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

# Load .env from project root (one level up from development/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Lazy import — revu_wrangler must be installed in the environment
try:
    from revu_wrangler import BluebeamClient
except ImportError:
    print(
        "ERROR: revu_wrangler is not installed.\n"
        "Install it with: uv pip install -e /path/to/revu_wrangler",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration from .env
# ---------------------------------------------------------------------------

BLUEBEAM_CLIENT_ID = os.environ.get("BLUEBEAM_CLIENT_ID")
BLUEBEAM_CLIENT_SECRET = os.environ.get("BLUEBEAM_CLIENT_SECRET")
BLUEBEAM_REDIRECT_URI = os.environ.get("BLUEBEAM_REDIRECT_URI", "http://localhost:5000/callback")
BLUEBEAM_REGION = os.environ.get("BLUEBEAM_REGION", "US")

TOKEN_FILE = _PROJECT_ROOT / "tokens.json"

# ---------------------------------------------------------------------------
# Validate configuration
# ---------------------------------------------------------------------------


def _validate_config():
    missing = []
    if not BLUEBEAM_CLIENT_ID:
        missing.append("BLUEBEAM_CLIENT_ID")
    if not BLUEBEAM_CLIENT_SECRET:
        missing.append("BLUEBEAM_CLIENT_SECRET")
    if missing:
        print(
            f"ERROR: Missing required environment variables: {', '.join(missing)}\n"
            f"Create a .env file in {_PROJECT_ROOT} with:\n"
            f"  BLUEBEAM_CLIENT_ID=your-client-id\n"
            f"  BLUEBEAM_CLIENT_SECRET=your-client-secret\n"
            f"  BLUEBEAM_REDIRECT_URI=http://localhost:5000/callback\n"
            f"  BLUEBEAM_REGION=US",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------


def _load_saved_tokens() -> dict | None:
    """Load tokens from disk if they exist."""
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text())
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            if not access_token:
                return None

            expires_in = int(data.get("expires_in", 3600) or 3600)
            saved_at = float(data.get("saved_at", 0) or 0)
            if saved_at and (saved_at + expires_in - 30) <= time.time() and not refresh_token:
                return None

            return data
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _save_tokens(access_token: str, refresh_token: str | None, expires_in: int):
    """Persist tokens to disk for reuse."""
    data = {
        "access_token": access_token,
        "expires_in": expires_in,
        "saved_at": time.time(),
    }
    if refresh_token:
        data["refresh_token"] = refresh_token
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    print(f"  Tokens saved to {TOKEN_FILE}")


# ---------------------------------------------------------------------------
# Local OAuth callback server
# ---------------------------------------------------------------------------

_captured_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect, extracts the auth code, shows a success page."""

    def do_GET(self):
        global _captured_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            desc = params.get("error_description", [""])[0]
            _captured_code = None
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h2>Authorization failed</h2>"
                f"<p>{error}: {desc}</p></body></html>".encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging to keep terminal clean."""
        pass


def _run_oauth_flow(client: BluebeamClient) -> None:
    """
    Full OAuth Authorization Code flow:
    1. Start local server on the redirect URI port
    2. Open browser to Bluebeam authorize URL
    3. Wait for callback with auth code
    4. Exchange code for tokens
    """
    global _captured_code
    _captured_code = None

    # Parse port from redirect URI
    parsed_uri = urlparse(BLUEBEAM_REDIRECT_URI)
    port = parsed_uri.port or 5000

    # Start callback server in background thread
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 120  # 2 minute timeout
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Open browser
    auth_url = client.get_authorization_url(state=state)
    print(f"  Opening browser for Bluebeam authorization...")
    print(f"  (If browser doesn't open, visit: {auth_url})")
    webbrowser.open(auth_url)

    # Wait for callback
    print(f"  Waiting for authorization (timeout: 2 minutes)...")
    thread.join(timeout=130)
    server.server_close()

    if not _captured_code:
        print("ERROR: Authorization timed out or was denied.", file=sys.stderr)
        sys.exit(1)

    # Exchange code for tokens
    print(f"  Exchanging auth code for tokens...")
    token = client.set_token_from_code(code=_captured_code)

    _save_tokens(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
    )
    print("  OK Authorized successfully")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_authenticated_client(scopes: list[str] | None = None) -> BluebeamClient:
    """
    Return an authenticated BluebeamClient ready for API calls.

    Tries saved tokens first. Falls back to full OAuth flow if needed.

    Args:
        scopes: Override default scopes. Useful for testing scope requirements.
                Default: ["full_user", "offline_access"]
    """
    _validate_config()

    client = BluebeamClient(
        client_id=BLUEBEAM_CLIENT_ID,
        client_secret=BLUEBEAM_CLIENT_SECRET,
        redirect_uri=BLUEBEAM_REDIRECT_URI,
        region=BLUEBEAM_REGION,
        scopes=scopes,
    )

    # Try saved tokens
    saved = _load_saved_tokens()
    if saved:
        print("  Loading saved tokens...")
        try:
            client.set_token(
                access_token=saved["access_token"],
                refresh_token=saved.get("refresh_token"),
                expires_in=saved.get("expires_in", 3600),
            )
            # Token refresh is handled automatically by the client's auth hook
            # on the next API call if the token is expired.
            print("  OK Using saved tokens")
            return client
        except Exception as e:
            print(f"  Saved tokens invalid ({e}), re-authenticating...")

    # Full OAuth flow
    _run_oauth_flow(client)
    return client
