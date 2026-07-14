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
import logging
import logging.handlers
import os
import secrets
import time
import webbrowser
from datetime import datetime
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
    LOG_DIR,
    AUTH_TIMEOUT_SECONDS,
    CALLBACK_PORT,
    validate_credentials,
    ConfigurationError,
)

# ---------------------------------------------------------------------------
# Debug logging setup
# ---------------------------------------------------------------------------

def _setup_debug_logger(debug_enabled: bool = False) -> logging.Logger:
    """Set up optional debug logging for auth flow troubleshooting."""
    logger = logging.getLogger("redline_radar.auth")
    
    if debug_enabled and not logger.handlers:
        # Create log directory if needed
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Generate timestamped log file name
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_file_path = LOG_DIR / f"redline_radar_{timestamp}.log"
        
        # Set up rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=1024 * 1024,  # 1MB
            backupCount=8,
        )
        
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    return logger

_auth_logger = _setup_debug_logger()

if TYPE_CHECKING:
    from revu_wrangler.auth import OAuthToken


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def load_saved_tokens() -> dict | None:
    """Load tokens from disk if they are still usable for authentication."""
    if not TOKEN_FILE.exists():
        _auth_logger.debug(f"Token file not found at {TOKEN_FILE}")
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token:
            _auth_logger.debug("No access token in saved token file")
            return None

        expires_in = int(data.get("expires_in", 3600) or 3600)
        saved_at = float(data.get("saved_at", 0) or 0)
        now = time.time()
        # Calculate expiration
        token_expires_at = saved_at + expires_in if saved_at else None
        time_until_expiry = token_expires_at - now if token_expires_at else None
        
        _auth_logger.debug(
            f"Token loaded from disk. "
            f"Expires in: {time_until_expiry:.0f}s. "
            f"Has refresh token: {bool(refresh_token)}"
        )
        
        # If token appears expired (with a small safety buffer) and there is
        # no refresh token, force full OAuth instead of returning stale data.
        if saved_at and (saved_at + expires_in - 30) <= now and not refresh_token:
            _auth_logger.debug(
                f"Token expired (no refresh token available). "
                f"Time until expiry: {time_until_expiry:.0f}s"
            )
            return None

        return data
    except (json.JSONDecodeError, KeyError, OSError) as e:
        _auth_logger.debug(f"Error reading token file: {type(e).__name__}: {e}")
        pass
    return None


def save_tokens(
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
    scopes: list[str] | None = None,
) -> None:
    """Persist tokens to disk for reuse on subsequent runs."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "access_token": access_token,
        "expires_in": expires_in,
        "saved_at": time.time(),
    }
    if scopes:
        data["scopes"] = list(scopes)
    if refresh_token:
        data["refresh_token"] = refresh_token
    TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    _auth_logger.debug(
        f"Tokens saved to {TOKEN_FILE}. "
        f"Expires in: {expires_in}s. "
        f"Has refresh token: {bool(refresh_token)}. "
        f"Scopes: {scopes}"
    )

    # Best-effort: restrict file permissions to owner only
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def clear_tokens() -> None:
    """Remove saved token file (used when re-auth is required)."""
    try:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink(missing_ok=True)
            _auth_logger.debug(f"Token file cleared: {TOKEN_FILE}")
        else:
            _auth_logger.debug(f"Token file does not exist: {TOKEN_FILE}")
    except OSError as e:
        _auth_logger.debug(f"Error clearing token file: {e}")


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


class ReauthenticationError(Exception):
    """Raised when automatic re-authentication cannot recover access."""


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

    _auth_logger.debug("Starting OAuth flow")
    
    # Parse port from redirect URI (default to configured port)
    parsed_uri = urlparse(BLUEBEAM_REDIRECT_URI)
    port = parsed_uri.port or CALLBACK_PORT

    # Diagnostic: show the exact redirect URI used in the auth request.
    print(f"OAuth redirect URI: {BLUEBEAM_REDIRECT_URI}")
    _auth_logger.debug(f"OAuth redirect URI: {BLUEBEAM_REDIRECT_URI}, port: {port}")

    # Start callback server in a background thread
    _auth_logger.debug(f"Starting callback server on port {port}")
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = AUTH_TIMEOUT_SECONDS
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()

    # Generate CSRF state
    state = secrets.token_urlsafe(32)

    # Open browser
    auth_url = client.get_authorization_url(state=state)
    _auth_logger.debug("Opening browser for authorization")
    webbrowser.open(auth_url)

    # Wait for the callback
    _auth_logger.debug(f"Waiting for OAuth callback (timeout: {AUTH_TIMEOUT_SECONDS}s)")
    thread.join(timeout=AUTH_TIMEOUT_SECONDS + 10)
    server.server_close()

    if _captured_error:
        _auth_logger.debug(f"OAuth error received: {_captured_error}")
        raise AuthFlowError(f"Authorization denied: {_captured_error}")

    if not _captured_code:
        _auth_logger.debug(f"OAuth timeout - no code received after {AUTH_TIMEOUT_SECONDS}s")
        raise AuthTimeoutError(
            "Authorization timed out. No response received within "
            f"{AUTH_TIMEOUT_SECONDS} seconds."
        )

    _auth_logger.debug("OAuth code received, exchanging for tokens")
    # Exchange code for tokens
    token = client.set_token_from_code(code=_captured_code)

    save_tokens(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_in=token.expires_in,
        scopes=list(getattr(client, "scopes", []) or []),
    )
    _auth_logger.debug("OAuth flow completed successfully")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_authenticated_client(scopes: list[str] | None = None, debug: bool = False) -> BluebeamClient:
    """
    Return an authenticated :class:`BluebeamClient` ready for API calls.

    Tries saved tokens first.  Falls back to the full OAuth browser flow
    if no valid tokens are available.

    Args:
        scopes: List of OAuth scopes to request.
        debug: Enable debug logging to file.

    Returns:
        A BluebeamClient with a valid access token.

    Raises:
        ConfigurationError: If credentials are missing from the environment.
        AuthTimeoutError: If the OAuth flow times out.
        AuthFlowError: If Bluebeam returns an auth error.
    """
    # Initialize debug logger with the provided flag
    global _auth_logger
    _auth_logger = _setup_debug_logger(debug_enabled=debug)
    
    _auth_logger.debug("get_authenticated_client() called")
    validate_credentials()

    # These are guaranteed non-None after validate_credentials()
    assert BLUEBEAM_CLIENT_ID is not None
    assert BLUEBEAM_CLIENT_SECRET is not None

    requested_scopes = scopes or DEFAULT_SCOPES
    _auth_logger.debug(f"Requested scopes: {requested_scopes}")

    client = BluebeamClient(
        client_id=BLUEBEAM_CLIENT_ID,
        client_secret=BLUEBEAM_CLIENT_SECRET,
        redirect_uri=BLUEBEAM_REDIRECT_URI,
        region=BLUEBEAM_REGION,
        scopes=requested_scopes,
    )

    # Try saved tokens
    _auth_logger.debug("Attempting to load saved tokens")
    saved = load_saved_tokens()
    if saved:
        saved_scopes = set(saved.get("scopes") or [])
        _auth_logger.debug(f"Saved scopes: {saved_scopes}")
        if not saved_scopes or saved_scopes != set(requested_scopes):
            _auth_logger.debug("Scope mismatch, clearing saved tokens")
            clear_tokens()
            saved = None
        else:
            _auth_logger.debug("Scope match confirmed")

    if saved:
        try:
            _auth_logger.debug("Setting client token from saved tokens")
            client.set_token(
                access_token=saved["access_token"],
                refresh_token=saved.get("refresh_token"),
                expires_in=saved.get("expires_in", 3600),
            )
            # Token refresh is handled automatically by the client's auth
            # hook on the next API call if the token is expired.
            _auth_logger.debug("Successfully authenticated with saved tokens")
            return client
        except (AuthenticationError, Exception) as e:
            # Saved tokens invalid — fall through to full OAuth
            _auth_logger.debug(f"Failed to use saved tokens: {type(e).__name__}: {e}")
            clear_tokens()

    # Full OAuth flow
    _auth_logger.debug("Proceeding to OAuth flow")
    run_oauth_flow(client)
    return client


def try_reauthenticate(client: BluebeamClient) -> bool:
    """
    Try to recover authentication for an existing client.

    Strategy:
      1. If a refresh token is available, attempt refresh.
      2. If refresh fails (or no refresh token), run full OAuth flow.

    Returns:
        True if the client has a refreshed/new access token.
    """
    _auth_logger.debug("try_reauthenticate() called")
    token = getattr(client.auth, "token", None)
    refresh_token = getattr(token, "refresh_token", None) if token else None
    saved = load_saved_tokens() or {}
    persisted_refresh = saved.get("refresh_token")
    effective_refresh = refresh_token or persisted_refresh
    
    _auth_logger.debug(f"In-memory refresh token: {bool(refresh_token)}, Persisted refresh token: {bool(persisted_refresh)}")

    if effective_refresh:
        try:
            _auth_logger.debug("Attempting token refresh")
            refreshed = client.refresh_token(effective_refresh)
            next_refresh = getattr(refreshed, "refresh_token", None) or effective_refresh
            save_tokens(
                access_token=refreshed.access_token,
                refresh_token=next_refresh,
                expires_in=refreshed.expires_in,
                scopes=list(getattr(client, "scopes", []) or []),
            )
            _auth_logger.debug("Token refresh successful")
            return True
        except Exception as e:
            # Fall back to full OAuth below.
            _auth_logger.debug(f"Token refresh failed: {type(e).__name__}: {e}")
            pass

    try:
        _auth_logger.debug("Attempting full OAuth flow for re-authentication")
        run_oauth_flow(client)
        return True
    except (AuthTimeoutError, AuthFlowError, Exception) as e:
        _auth_logger.debug(f"Re-authentication failed: {type(e).__name__}: {e}")
        return False


def ensure_valid_client(client: BluebeamClient) -> None:
    """
    Ensure the given client can authenticate API requests.

    Raises:
        ReauthenticationError if no recovery path succeeds.
    """
    _auth_logger.debug("ensure_valid_client() called")
    if try_reauthenticate(client):
        _auth_logger.debug("Client re-authentication successful")
        return
    _auth_logger.debug("Unable to re-authenticate - raising ReauthenticationError")
    raise ReauthenticationError("Unable to re-authenticate with Bluebeam.")
