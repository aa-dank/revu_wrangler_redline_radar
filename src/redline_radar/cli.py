"""
CLI interface for Redline Radar.

Uses **Click** for user input and **Rich** for formatted terminal output,
following the patterns described in ``docs/RESEARCH_cli_ux_patterns.md``.

The flow is a single linear workflow:
  1. Banner
  2. Auth check (OAuth if needed)
  3. Session ID input (supports pasted invitation text)
  4. Fetch session info + confirm
  5. Data collection with progress feedback
  6. Report generation
  7. "Check another session?" loop
"""

from __future__ import annotations

import re
import sys

import click
from rich.align import Align
from rich.console import Console
from rich.panel import Panel

from rich.table import Table

from redline_radar import __version__
from redline_radar.auth import (
    get_authenticated_client,
    clear_tokens,
    load_saved_tokens,
    AuthTimeoutError,
    AuthFlowError,
    ReauthenticationError,
)
from redline_radar.config import ConfigurationError
from redline_radar.api import (
    fetch_session_info,
    fetch_session_files,
    fetch_session_users,
    fetch_session_activities,
    fetch_session_activities_after_id,
    get_activity_count
)
from redline_radar.activity_analysis import build_session_activity_analysis
from redline_radar.activity_workbook import export_activity_workbook
from redline_radar.report import generate_report
from redline_radar.cache import (
    initialize_db,
    save_session_cache,
    load_session_cache, 
    save_activities, 
    load_activities,
    validate_cache, 
    has_session_cache
)

from redline_radar.cache_json import (
    CacheJSON
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_ID_PATTERN = re.compile(r"\d{3}-\d{3}-\d{3}")

console = Console()
REPORT_SCOPES = ["full_user", "offline_access"]

BANNER = rf"""
[bold yellow]╔══════════════════════════════════════════════════╗
║                                                  ║
║   ██████  ███████ ██████  ██      ██ ███  ██ ███ ║
║   ██   ██ ██      ██   ██ ██      ██ ████ ██ ██  ║
║   ██████  █████   ██   ██ ██      ██ ██ ████ ███ ║
║   ██   ██ ██      ██   ██ ██      ██ ██  ███ ██  ║
║   ██   ██ ███████ ██████  ███████ ██ ██   ██ ███ ║
║                                                  ║
║          [italic dim]Redline Radar v{__version__}[/italic dim]                    ║
║       [italic dim]Bluebeam Session Summary Reporter[/italic dim]          ║
╚══════════════════════════════════════════════════╝[/bold yellow]
"""


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def extract_session_id(raw_input: str) -> str | None:
    """
    Extract a Bluebeam Session ID (``NNN-NNN-NNN``) from arbitrary text.

    Handles:
      - Plain IDs: ``117-770-339``
      - Session URLs containing the ID
      - Multi-line invitation text with the ID somewhere inside
    """
    match = SESSION_ID_PATTERN.search(raw_input)
    return match.group(0) if match else None


def prompt_session_id() -> str:
    """
    Prompt the user for a session ID, accepting multi-line paste.

    Collects lines until either a session ID is found or the user
    submits a blank line.
    """
    console.rule("[bold yellow]Session Input[/bold yellow]", style="yellow")
    console.print(
        "Paste a Session ID, URL, or invitation text.\n"
        "Press [bold]Enter[/bold] on a blank line when done.",
        style="dim",
    )

    collected_lines: list[str] = []

    while True:
        try:
            line = click.prompt("", default="", show_default=False, prompt_suffix="> ")
        except (EOFError, click.Abort):
            break

        # Check immediately for a session ID in this line
        session_id = extract_session_id(line)
        if session_id:
            # Also store the line in case there's more context, but we have what we need
            collected_lines.append(line)
            console.print(
                f"[bold green]\u2714 Session ID extracted:[/bold green] [cyan]{session_id}[/cyan]"
            )
            return session_id

        if line.strip() == "" and collected_lines:
            # Blank line after some input — check everything collected
            break

        if line.strip() == "" and not collected_lines:
            # Nothing entered yet — keep prompting
            continue

        collected_lines.append(line)

    # Try the full collected text
    full_text = "\n".join(collected_lines)
    session_id = extract_session_id(full_text)

    if session_id:
        console.print(
            f"[bold green]\u2714 Session ID extracted:[/bold green] [cyan]{session_id}[/cyan]"
        )
        return session_id

    # No ID found
    console.print(
        "[red]\u2716 Could not find a valid Session ID (format: NNN-NNN-NNN).[/red]\n"
        "[dim]  Tip: Copy the full invitation text or the Session ID directly.[/dim]"
    )
    return ""


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

@click.command()
@click.argument("session_id", required=False)
def main(session_id: str | None = None) -> None:
    """Redline Radar — Bluebeam Studio Session Summary Reporter."""
    try: 
        _run(session_id)
    except KeyboardInterrupt:
        console.print("\n[bold red]\u2716 Interrupted.[/bold red]")
        sys.exit(0)
    except click.Abort:
        console.print("\n[bold red]\u2716 Cancelled.[/bold red]")
        sys.exit(0)


def _run(session_id: str | None = None) -> None:
    """Core application loop."""

    # ── Banner ──
    console.print(BANNER, highlight=False)
    console.print(
        Align.center(
            "Press [bold red][CTRL+C][/bold red] at any time to exit.",
            style="dim",
        )
    )
    console.print()

    # ── Credentials check ──
    try:
        from redline_radar.config import validate_credentials
        validate_credentials()
    except ConfigurationError as exc:
        console.print(f"[bold red]\u2716 {exc}[/bold red]")
        sys.exit(1)

    # ── Authentication ──
    client = _authenticate()
    if client is None:
        sys.exit(1)

    # ── Session loop ──
    auto_generate = session_id is not None
    cli_session_id = session_id
    while True:
        console.print()
        #session_id = prompt_session_id()
        if cli_session_id:
            session_id = cli_session_id
            cli_session_id = None
            console.print(
                f"[green]\u2714 Using Session ID from command line:[/green] "
                f"[cyan]{session_id}[/cyan]"
            )
        else:
            session_id = prompt_session_id()
        if not session_id:
            if not click.confirm("Try again?", default=True):
                break
            continue

        # ── Fetch session info ──
        try:
            with console.status("[bold green]Fetching session info...", spinner="dots"):
                session_info = fetch_session_info(client, session_id)
        except Exception as exc:
            _handle_api_error(exc, session_id)
            if click.confirm("Try another session?", default=True):
                continue
            break

        # ── Display and confirm ──
        _display_session_info(session_info, session_id)
        if not auto_generate:
            if not click.confirm("Generate report for this session?", default=True):
                console.print("[bold red]\u2716 Cancelled[/bold red]")
                if click.confirm("Check another session?", default=False):
                    continue
                break

        # ── Data collection ──
        analysis, markup_error = _collect_data(
            client, session_id
        )

        if markup_error:
            console.print(
                f"[bold yellow]\u26a0 Markup data unavailable:[/bold yellow] {markup_error}\n"
                "[dim]  Attendance data will still be included in the report.[/dim]"
            )

        # ── Report generation ──
        try:
            output_path = generate_report(
                session_info=session_info,
                attendance=analysis.attendance,
                files=analysis.file_summary,
            )
            workbook_path = export_activity_workbook(
                raw_df=analysis.raw_df,
                activities_df=analysis.activities_df,
                output_path=output_path.with_name(f"{output_path.stem}_activities.xlsx"),
            )
            console.print(
                f"\n[bold green]\u2714 Report generated:[/bold green] [cyan]{output_path.name}[/cyan]"
            )
            console.print(f"  Saved to: [cyan]{output_path}[/cyan]")
            console.print(f"  Activity workbook: [cyan]{workbook_path}[/cyan]")
        except Exception as exc:
            console.print(f"[bold red]\u2716 Failed to generate report:[/bold red] {exc}")

        # ── Loop ──
        console.print()
        if not click.confirm("Check another session?", default=False):
            break

    # ── Goodbye ──
    console.print()
    console.print(
        Align.center("[dim]Goodbye.[/dim]")
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _authenticate():
    """Handle authentication, returning a BluebeamClient or None."""
    with console.status(
        "[bold green]Checking authentication...", spinner="dots"
    ):
        saved = load_saved_tokens()

    if saved:
        console.print("[green]\u2022 Loaded saved token file.[/green]")
        try:
            client = get_authenticated_client(scopes=REPORT_SCOPES)
            console.print("[bold green]\u2714 Authentication ready.[/bold green]")
            return client
        except Exception:
            console.print(
                "[yellow]\u26a0 Saved credentials are invalid. Re-authenticating...[/yellow]"
            )
            clear_tokens()

    # Need to do OAuth
    console.print(
        "[yellow]\u26a0 No saved credentials found. Starting Bluebeam login...[/yellow]"
    )
    console.print("  Opening browser for Bluebeam authorization...")
    console.print(
        f"  Waiting for authorization (timeout: 2 minutes)..."
    )

    try:
        client = get_authenticated_client(scopes=REPORT_SCOPES)
        console.print("[bold green]\u2714 Authorized successfully.[/bold green]")
        return client
    except AuthTimeoutError:
        console.print(
            "[bold red]\u2716 Authorization timed out.[/bold red]\n"
            "  Please try again and complete the login in your browser."
        )
        return None
    except AuthFlowError as exc:
        console.print(f"[bold red]\u2716 Authorization failed:[/bold red] {exc}")
        return None
    except ConfigurationError as exc:
        console.print(f"[bold red]\u2716 {exc}[/bold red]")
        return None
    except Exception as exc:
        console.print(f"[bold red]\u2716 Authentication error:[/bold red] {exc}")
        return None


# ---------------------------------------------------------------------------
# Session display
# ---------------------------------------------------------------------------

def _display_session_info(session_info: dict, session_id: str) -> None:
    """Display a summary panel for the fetched session."""
    name = session_info.get("Name", "Unknown Session")
    status = session_info.get("Status", "Unknown")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="#8691F6")
    table.add_column("Value", style="white")
    table.add_row("Session", name)
    table.add_row("ID", session_id)
    table.add_row("Status", status)

    panel = Panel(table, border_style="green", expand=False)
    console.print(panel)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _collect_data(client, session_id: str):
    """
    Fetch attendance and markup data.

    Session summary data is now derived from the canonical activity feed.

    Returns:
        Tuple of (analysis, error_message_or_None).
    """
    analysis = build_session_activity_analysis(activities=[], users=[], files=[])
    data_error: str | None = None
    files: list[dict] = []
    users: list[dict] = []
    activities: list[dict] = []
    cache_hit: bool = False
    cache_valid: bool = False
    cached_count: int = 0
    new_activity_count: int = 0

    with console.status("[bold green]Fetching session data...", spinner="dots"):
        errors: list[str] = []

        try:
            files = fetch_session_files(client, session_id)
        except Exception as exc:
            errors.append(f"files: {exc}")

        try:
            users = fetch_session_users(client, session_id)
        except Exception as exc:
            errors.append(f"users: {exc}")

        try:
            (
                activities, 
                cache_hit,
                cache_valid, 
                cached_count,
                new_activity_count
            ) = get_session_activities_JSON(client, session_id)
        except Exception as exc:
            errors.append(f"activities/cache: {exc}")

        analysis = build_session_activity_analysis(
            activities=activities,
            users=users,
            files=files,
        )
        if errors:
            data_error = "; ".join(errors)

    console.print(
        f"[bold green]\u2714[/bold green] Attendance: {len(analysis.attendance)} user(s) found."
    )
    console.print(
        f"[bold green]\u2714[/bold green] Files: {len(analysis.file_summary)} file(s) in session."
    )
    console.print(
        f"[bold green]\u2714[/bold green] Activities: {len(analysis.activities_df)} row(s) analyzed."
    )
    if cache_hit:
        activity_label = "activity" if len(activities) == 1 else "activities"
        console.print(
                f"[bold green]\u2714[/bold green] Loaded {len(activities)} {activity_label} from cache."
            )
    elif new_activity_count > 0:
        activity_label = "activity" if new_activity_count == 1 else "activities"
        total_label = "activity" if cached_count == 1 else "activities"
        console.print(
            f"[bold green]\u2714[/bold green] Cache updated: {new_activity_count} new {activity_label} stored ({cached_count} {total_label})."
        )  
    elif cache_valid:
        activity_label = "activity" if cached_count == 1 else "activities"
        console.print(
            f"[bold green]\u2714[/bold green] Cache validated: {cached_count} {activity_label} stored."
        )  
    if analysis.unknown_messages:
        console.print(
            f"[yellow]\u26a0 Unclassified activity messages:[/yellow] {len(analysis.unknown_messages)}"
        )

    return analysis, data_error

# ---------------------------------------------------------------------------
# Activity Retrieval / Caching USING SQLITE
# ---------------------------------------------------------------------------
def get_session_activities(
    client,
    session_id: str,
) -> tuple[list[dict], bool, bool, int, int]:
    """
    Retrieve activities for a session, using the local cache when possible.
    Cache validation is performed using the session activity count reported
    by the Bluebeam API. 
    Cache is saved on user's local computer, so cache is individual to 
    each user - not shared. 

    If session_id is cached and the cached activity count matches 
    the API's TotalCount value, activities are loaded from cache. 
    If session-id is cached but activity count does not match API's 
    TotalCount, fetch session activities with ids larger than latest 
    session activity id in cache. 
    Otherwise the entire activity history is fetched and saved to cache.

    Return: activities, cache_hit, cache_valid, cached_count, new_activity_count
    """
    cache_hit: bool = False
    cache_valid: bool = False
    cached_count: int = 0
    new_activity_count: int = 0
    initialize_db()

    # Existing cache found
    if has_session_cache(session_id):
        expected_count = get_activity_count(client, session_id)
        cache_valid, cached_count = validate_cache(session_id, expected_count)

        # Cache must contain same number activities reported in Bluebeam API, then load from SQLite
        if cache_valid:
            cache_hit = True
            activities = load_activities(session_id)
            return (activities, cache_hit, cache_valid, cached_count, 0)
        
        # Cache exists but is missing activities, so fetch only activities newer than latest activity
        cache_info = load_session_cache(session_id)
        if cache_info is None:
            raise RuntimeError(
                f"Cache metadata missing for session {session_id}"
            )
        _, latest_activity_id, _ = cache_info
        new_activities = fetch_session_activities_after_id(
            client, session_id, latest_activity_id)
        new_activity_count = len(new_activities)
        save_activities(session_id,new_activities)
        activities = load_activities(session_id)
        save_session_cache(session_id,activities)
        cache_valid, cached_count = validate_cache(session_id, expected_count)
            
        return (activities, False, cache_valid, cached_count, new_activity_count)
        
    # Cache missing or invalid, fetch complete activity from Bluebeam and save to cache
    activities = fetch_session_activities(client, session_id)
    save_activities(session_id,activities)
    save_session_cache(session_id,activities)

    expected_count = get_activity_count(client, session_id)
    cache_valid, cached_count = validate_cache(session_id, expected_count)
    return (activities, False, cache_valid, cached_count, 0)

# ---------------------------------------------------------------------------
# Activity Retrieval / Caching USING JSON
# ---------------------------------------------------------------------------
def get_session_activities_JSON(
    client,
    session_id: str,
) -> tuple[list[dict], bool, bool, int, int]:
    """
    Functionality mirrors `get_session_activities`; the only difference is how the
    cache is stored.

    The cache is persisted as a shared JSON file located alongside the application.
    A file lock is used to ensure that only one process can modify the cache at a
    time, preventing concurrent writes from corrupting the file.
    """
    cache_hit: bool = False
    cache_valid: bool = False
    cached_count: int = 0
    new_activity_count: int = 0
    cache = CacheJSON()

    #Existing cache found
    cache_info = cache.get_session(session_id)
    if (cache_info is not None):
        expected_count = get_activity_count(client, session_id)
        cache_valid, cached_count = cache.validate(session_id, expected_count)

        # Cache must contain same number activities reported in Bluebeam API, then load from SQLite
        if cache_valid:
            cache_hit = True
            activities = cache.get_activities(session_id)
            return (activities, cache_hit, cache_valid, cached_count, 0)
        # Cache exists but is missing activities, so fetch only activities newer than latest activity
        else:
            if cache_info is None:
                raise RuntimeError(
                    f"Cache metadata missing for session {session_id}"
                )
            latest_activity_id = cache_info["latest_activity_id"]
            expected_count = get_activity_count(client, session_id)

            new_activities = fetch_session_activities_after_id(
                client, session_id, latest_activity_id)
            new_activity_count = len(new_activities)
            cache.save_activities(session_id, new_activities)
            activities = cache.get_activities(session_id)
            cache_valid, cached_count = cache.validate(session_id, expected_count)

            return (activities, False, cache_valid, cached_count, new_activity_count)
    # Cache missing or invalid, fetch complete activity from Bluebeam and save to cache
    activities = fetch_session_activities(client, session_id)
    cache.save_activities(session_id,activities)

    expected_count = get_activity_count(client, session_id)
    cache_valid, cached_count = cache.validate(session_id, expected_count)
    return (activities, False, cache_valid, cached_count, 0)

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def _handle_api_error(exc: Exception, session_id: str) -> None:
    """Print a user-friendly error message for API errors."""
    msg = str(exc)
    if "404" in msg or "not found" in msg.lower():
        console.print(
            f"[bold red]\u2716 Session not found:[/bold red] {session_id}\n"
            "[dim]  Check the Session ID and try again.[/dim]"
        )
    elif "401" in msg or "403" in msg or "unauthorized" in msg.lower():
        console.print(
            "[bold red]\u2716 Authentication error.[/bold red]\n"
            "[dim]  Session recovery failed after automatic re-authentication attempt.[/dim]"
        )
    elif isinstance(exc, ReauthenticationError):
        console.print(
            "[bold red]\u2716 Authentication recovery failed.[/bold red]\n"
            "[dim]  Automatic re-authentication was attempted but did not succeed.[/dim]"
        )
    else:
        console.print(f"[bold red]\u2716 Failed to fetch session:[/bold red] {exc}")
