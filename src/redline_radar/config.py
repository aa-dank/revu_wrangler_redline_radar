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
    (default: ``http://localhost:5000/callback``).
``BLUEBEAM_SCOPE``
    Space-separated OAuth scopes to request
    (default: ``read_prime``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Load .env (optional)
# ---------------------------------------------------------------------------

def _candidate_env_files() -> list[Path]:
    """Return likely .env locations for source and bundled executions."""
    candidates: list[Path] = []

    # Current working directory (typical local development run).
    candidates.append(Path.cwd() / ".env")

    # Project root relative to this source file: src/redline_radar/config.py -> root.
    candidates.append(Path(__file__).resolve().parents[2] / ".env")

    # Directory containing the executable/script.
    candidates.append(Path(sys.executable).resolve().parent / ".env")

    # PyInstaller extraction directory (when bundled with --add-data).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / ".env")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


if load_dotenv is not None:
    for env_path in _candidate_env_files():
        if env_path.exists():
            load_dotenv(env_path, override=False)


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_AUTH_URL = "https://authserver.bluebeam.com/auth/oauth/authorize"
DEFAULT_TOKEN_URL = "https://authserver.bluebeam.com/auth/oauth/token"
DEFAULT_REDIRECT_URI = "http://localhost:5000/callback"
DEFAULT_SCOPE = "read_prime"


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a safe fallback."""
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


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
# Backward-compatible exported settings
# ---------------------------------------------------------------------------

# Some modules import these as constants. Keep them available while loading
# from the same .env/environment source.
BLUEBEAM_CLIENT_ID = get_client_id()
BLUEBEAM_CLIENT_SECRET = get_client_secret()
BLUEBEAM_REDIRECT_URI = get_redirect_uri()
BLUEBEAM_REGION = os.environ.get("BLUEBEAM_REGION", "US")

DEFAULT_SCOPES = [scope for scope in get_scope().split() if scope]

TOKEN_DIR = Path.home() / ".redline_radar"
TOKEN_FILE = TOKEN_DIR / "tokens.json"

OUTPUT_DIR = Path.home() / "Downloads"
if not OUTPUT_DIR.exists():
    OUTPUT_DIR = Path.home()

AUTH_TIMEOUT_SECONDS = _int_env("BLUEBEAM_AUTH_TIMEOUT_SECONDS", 120)
CALLBACK_PORT = urlparse(BLUEBEAM_REDIRECT_URI).port or 5000


def get_template_dir() -> Path:
    """Return template directory for source runs and PyInstaller bundles."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "redline_radar" / "templates"
        if bundled.exists():
            return bundled

    source = Path(__file__).resolve().parent / "templates"
    if source.exists():
        return source

    return source


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
