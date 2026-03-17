"""
OAuth Authorization Code flow for Bluebeam Studio API.

Handles:
  - Token persistence to ``~/.redline_radar/tokens.json``
  - Automatic token refresh on subsequent runs
  - Local callback HTTP server for the OAuth redirect
  - Browser launch for user authorization
"""

from __future__ import annotations

import json
import secrets
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING
from urllib.parse import urlparse, parse_qs

from revu_wrangler import BluebeamClient, AuthenticationError

from redline_radar.config import (
    BLUEBEAM_CLIENT_ID,
    BLUEBEAM_CLIENT_SECRET,
    BLUEBEAM_REDIRECT_URI,
    BLUEBEAM_REGION,
    DEFAULT_SCOPES,
    TOKEN_DIR,
    TOKEN_FILE,
    AUTH_TIMEOUT_SECONDS,
    CALLBACK_PORT,
    validate_credentials,
    ConfigurationError,
)

if TYPE_CHECKING:
    from revu_wrangler.auth import OAuthToken


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def load_saved_tokens() -> dict | None:
    """Load tokens from disk if they exist and contain an access_token."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        if data.get("access_token"):
            return data
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def save_tokens(
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
) -> None:
    """Persist tokens to disk for reuse on subsequent runs."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "saved_at": time.time(),
    }
    TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Best-effort: restrict file permissions to owner only
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def clear_tokens() -> None:
    """Remove saved token file (used when re-auth is required)."""
    try:
        TOKEN_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Local OAuth callback server
# ---------------------------------------------------------------------------

_captured_code: str | None = None
_captured_error: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect from Bluebeam, captures the auth code."""

    def do_GET(self) -> None:
        global _captured_code, _captured_error
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _captured_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body>"
                b"<h2>Authorization successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            desc = params.get("error_description", [""])[0]
            _captured_error = f"{error}: {desc}"
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"<html><body>"
                f"<h2>Authorization failed</h2>"
                f"<p>{error}: {desc}</p>"
                f"</body></html>".encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress noisy default logging."""
        pass


class AuthTimeoutError(Exception):
    """Raised when the user does not complete OAuth within the timeout."""


class AuthFlowError(Exception):
    """Raised when the OAuth flow encounters an error."""


def run_oauth_flow(client: BluebeamClient) -> None:
    """
    Execute the full OAuth Authorization Code flow:

    1. Start a local HTTP server on the configured callback port
    2. Open the user's browser to the Bluebeam authorize URL
    3. Wait for the redirect callback with the auth code
    4. Exchange the code for access + refresh tokens
    5. Persist tokens to disk

    Args:
        client: A pre-configured BluebeamClient (no token yet).

    Raises:
        AuthTimeoutError: If the user does not complete auth within the timeout.
        AuthFlowError: If Bluebeam returns an error in the callback.
    """
    global _captured_code, _captured_error
    _captured_code = None
    _captured_error = None

    # Parse port from redirect URI (default to configured port)
    parsed_uri = urlparse(BLUEBEAM_REDIRECT_URI)
    port = parsed_uri.port or CALLBACK_PORT

    # Diagnostic: show the exact redirect URI used in the auth request.
    print(f"OAuth redirect URI: {BLUEBEAM_REDIRECT_URI}")

    # Start callback server in a background thread
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = AUTH_TIMEOUT_SECONDS
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()

    # Generate CSRF state
    state = secrets.token_urlsafe(32)

    # Open browser
    auth_url = client.get_authorization_url(state=state)
    webbrowser.open(auth_url)

    # Wait for the callback
    thread.join(timeout=AUTH_TIMEOUT_SECONDS + 10)
    server.server_close()

    if _captured_error:
        raise AuthFlowError(f"Authorization denied: {_captured_error}")

    if not _captured_code:
        raise AuthTimeoutError(
            "Authorization timed out. No response received within "
            f"{AUTH_TIMEOUT_SECONDS} seconds."
        )

    # Exchange code for tokens
    token = client.set_token_from_code(code=_captured_code)

    save_tokens(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_authenticated_client() -> BluebeamClient:
    """
    Return an authenticated :class:`BluebeamClient` ready for API calls.

    Tries saved tokens first.  Falls back to the full OAuth browser flow
    if no valid tokens are available.

    Returns:
        A BluebeamClient with a valid access token.

    Raises:
        ConfigurationError: If credentials are missing from the environment.
        AuthTimeoutError: If the OAuth flow times out.
        AuthFlowError: If Bluebeam returns an auth error.
    """
    validate_credentials()

    # These are guaranteed non-None after validate_credentials()
    assert BLUEBEAM_CLIENT_ID is not None
    assert BLUEBEAM_CLIENT_SECRET is not None

    client = BluebeamClient(
        client_id=BLUEBEAM_CLIENT_ID,
        client_secret=BLUEBEAM_CLIENT_SECRET,
        redirect_uri=BLUEBEAM_REDIRECT_URI,
        region=BLUEBEAM_REGION,
        scopes=DEFAULT_SCOPES,
    )

    # Try saved tokens
    saved = load_saved_tokens()
    if saved:
        try:
            client.set_token(
                access_token=saved["access_token"],
                refresh_token=saved.get("refresh_token"),
                expires_in=saved.get("expires_in", 3600),
            )
            # Token refresh is handled automatically by the client's auth
            # hook on the next API call if the token is expired.
            return client
        except (AuthenticationError, Exception):
            # Saved tokens invalid — fall through to full OAuth
            clear_tokens()

    # Full OAuth flow
    run_oauth_flow(client)
    return client
