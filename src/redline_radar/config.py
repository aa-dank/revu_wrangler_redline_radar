"""
Configuration management for Redline Radar.

Handles loading credentials from environment variables and/or a ``.env``
file, and exposes a ``validate_credentials()`` helper that raises
``ConfigurationError`` with actionable guidance if required values are
missing.

Required environment variables
-------------------------------
``BLUEBEAM_CLIENT_ID``
    OAuth application client ID.
``BLUEBEAM_CLIENT_SECRET``
    OAuth application client secret.

Optional environment variables
-------------------------------
``BLUEBEAM_AUTH_URL``
    Override the OAuth authorisation endpoint
    (default: ``https://authserver.bluebeam.com/auth/oauth/authorize``).
``BLUEBEAM_TOKEN_URL``
    Override the token exchange endpoint
    (default: ``https://authserver.bluebeam.com/auth/oauth/token``).
``BLUEBEAM_REDIRECT_URI``
    Override the local callback URI used during the OAuth flow
    (default: ``http://localhost:8765/callback``).
``BLUEBEAM_SCOPE``
    Space-separated OAuth scopes to request
    (default: ``read_prime``).
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Load .env (optional)
# ---------------------------------------------------------------------------

_ENV_FILE = Path(".env")

if load_dotenv is not None and _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_AUTH_URL = "https://authserver.bluebeam.com/auth/oauth/authorize"
DEFAULT_TOKEN_URL = "https://authserver.bluebeam.com/auth/oauth/token"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_SCOPE = "read_prime"


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------

def get_client_id() -> str:
    """Return the Bluebeam OAuth client ID from the environment."""
    return os.environ.get("BLUEBEAM_CLIENT_ID", "")


def get_client_secret() -> str:
    """Return the Bluebeam OAuth client secret from the environment."""
    return os.environ.get("BLUEBEAM_CLIENT_SECRET", "")


def get_auth_url() -> str:
    """Return the OAuth authorisation endpoint URL."""
    return os.environ.get("BLUEBEAM_AUTH_URL", DEFAULT_AUTH_URL)


def get_token_url() -> str:
    """Return the OAuth token exchange endpoint URL."""
    return os.environ.get("BLUEBEAM_TOKEN_URL", DEFAULT_TOKEN_URL)


def get_redirect_uri() -> str:
    """Return the local OAuth callback URI."""
    return os.environ.get("BLUEBEAM_REDIRECT_URI", DEFAULT_REDIRECT_URI)


def get_scope() -> str:
    """Return the OAuth scope string."""
    return os.environ.get("BLUEBEAM_SCOPE", DEFAULT_SCOPE)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ConfigurationError(Exception):
    """Raised when required configuration values are missing or invalid."""


def validate_credentials() -> None:
    """
    Raise ``ConfigurationError`` if required credentials are not set.

    Checks:
      - ``BLUEBEAM_CLIENT_ID`` is non-empty
      - ``BLUEBEAM_CLIENT_SECRET`` is non-empty

    The error message includes actionable guidance for the user.
    """
    missing: list[str] = []

    if not get_client_id():
        missing.append("BLUEBEAM_CLIENT_ID")
    if not get_client_secret():
        missing.append("BLUEBEAM_CLIENT_SECRET")

    if missing:
        vars_str = ", ".join(missing)
        raise ConfigurationError(
            f"Missing required environment variable(s): {vars_str}.\n"
            "  Set them in your shell or in a .env file in the project root.\n"
            "  Example:\n"
            "    BLUEBEAM_CLIENT_ID=your-client-id\n"
            "    BLUEBEAM_CLIENT_SECRET=your-client-secret"
        )
