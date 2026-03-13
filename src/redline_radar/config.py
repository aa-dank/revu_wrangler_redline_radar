"""
Application configuration, path resolution, and credential loading.

Resolution order for `.env`:
  1. Adjacent to the executable (PyInstaller builds)
  2. Current working directory
  3. Project root (fallback for development)

Required environment variables:
  - BLUEBEAM_CLIENT_ID
  - BLUEBEAM_CLIENT_SECRET

Optional (with defaults):
  - BLUEBEAM_REDIRECT_URI  (default: http://localhost:5000/callback)
  - BLUEBEAM_REGION         (default: US)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# .env resolution
# ---------------------------------------------------------------------------

def _find_and_load_dotenv() -> None:
    """Search for a .env file in priority order and load the first one found."""
    candidates: list[Path] = []

    # 1. Adjacent to the executable (PyInstaller frozen bundle)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / ".env")  # type: ignore[attr-defined]
        candidates.append(Path(sys.executable).parent / ".env")

    # 2. Current working directory
    candidates.append(Path.cwd() / ".env")

    # 3. Project root — walk up from this file until we find pyproject.toml
    current = Path(__file__).resolve().parent
    for _i in range(5):
        candidate = current / ".env"
        candidates.append(candidate)
        if (current / "pyproject.toml").exists():
            break
        current = current.parent

    for env_path in candidates:
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            return

    # No .env found — variables may still be set in the environment
    load_dotenv(override=False)


_find_and_load_dotenv()

# ---------------------------------------------------------------------------
# Credential constants
# ---------------------------------------------------------------------------

BLUEBEAM_CLIENT_ID: str | None = os.environ.get("BLUEBEAM_CLIENT_ID")
BLUEBEAM_CLIENT_SECRET: str | None = os.environ.get("BLUEBEAM_CLIENT_SECRET")
BLUEBEAM_REDIRECT_URI: str = os.environ.get(
    "BLUEBEAM_REDIRECT_URI", "http://localhost:5000/callback"
)
BLUEBEAM_REGION: str = os.environ.get("BLUEBEAM_REGION", "US")

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

#: Directory for persisted OAuth tokens.
TOKEN_DIR: Path = Path.home() / ".redline_radar"

#: Full path to the saved token file.
TOKEN_FILE: Path = TOKEN_DIR / "tokens.json"

#: Default output directory for generated reports.
OUTPUT_DIR: Path = Path.home() / "Downloads"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: OAuth scopes requested.
DEFAULT_SCOPES: list[str] = ["full_user", "offline_access"]

#: How long to wait for the user to complete OAuth in the browser (seconds).
AUTH_TIMEOUT_SECONDS: int = 120

#: Port for the local OAuth callback server.
CALLBACK_PORT: int = 5000

# ---------------------------------------------------------------------------
# Template path resolution
# ---------------------------------------------------------------------------

def get_template_dir() -> Path:
    """Resolve the Jinja2 template directory for both dev and PyInstaller contexts."""
    if getattr(sys, "frozen", False):
        # Running as a PyInstaller bundle
        return Path(sys._MEIPASS) / "redline_radar" / "templates"  # type: ignore[attr-defined]
    else:
        # Running from source
        return Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ConfigurationError(Exception):
    """Raised when required configuration is missing."""


def validate_credentials() -> None:
    """
    Verify that required Bluebeam credentials are present.

    Raises:
        ConfigurationError: If BLUEBEAM_CLIENT_ID or BLUEBEAM_CLIENT_SECRET
            are not set.
    """
    missing: list[str] = []
    if not BLUEBEAM_CLIENT_ID:
        missing.append("BLUEBEAM_CLIENT_ID")
    if not BLUEBEAM_CLIENT_SECRET:
        missing.append("BLUEBEAM_CLIENT_SECRET")
    if missing:
        raise ConfigurationError(
            f"Missing Bluebeam credentials: {', '.join(missing)}.\n"
            "Expected a .env file with BLUEBEAM_CLIENT_ID and BLUEBEAM_CLIENT_SECRET.\n"
            "See README for setup instructions."
        )
