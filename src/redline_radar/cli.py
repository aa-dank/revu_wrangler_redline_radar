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
    run_oauth_flow,
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
    build_attendance,
    build_markup_summary,
)
from redline_radar.report import generate_report

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_ID_PATTERN = re.compile(r"\d{3}-\d{3}-\d{3}")

console = Console()

BANNER = rf"""
[bold yellow]╔══════════════════════════════════════════════════╗
║                                                  ║
║   ██████  ███████ ██████  ██      ██ ███  ██ ███ ║
║   ██   ██ ██      ██   ██ ██      ██ ████ ██ ██  ║
║   ██████  █████   ██   ██ ██      ██ ██ ████ ███ ║
║   ██   ██ ██      ██   ██ ██      ██ ██  ███ ██  ║
║   ██   ██ ███████ ██████  ███████ ██ ██   ██ ███ ║
║                                                  ║
║          [italic dim]Redline Radar v{__version__}[/italic dim]                     ║
║       [italic dim]Bluebeam Session Summary Reporter[/italic dim]           ║
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
def main() -> None:
    """Redline Radar — Bluebeam Studio Session Summary Reporter."""
    try:
        _run()
    except KeyboardInterrupt:
        console.print("\n[bold red]\u2716 Interrupted.[/bold red]")
        sys.exit(0)
    except click.Abort:
        console.print("\n[bold red]\u2716 Cancelled.[/bold red]")
        sys.exit(0)


def _run() -> None:
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
    while True:
        console.print()
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

        if not click.confirm("Generate report for this session?", default=True):
            console.print("[bold red]\u2716 Cancelled[/bold red]")
            if click.confirm("Check another session?", default=False):
                continue
            break

        # ── Data collection ──
        attendance, markup_summary, markup_error = _collect_data(
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
                attendance=attendance,
                files=markup_summary,
            )
            console.print(
                f"\n[bold green]\u2714 Report generated:[/bold green] [cyan]{output_path.name}[/cyan]"
            )
            console.print(f"  Saved to: [cyan]{output_path}[/cyan]")
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
            client = get_authenticated_client()
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
        client = get_authenticated_client()
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

    Markup data is now derived from the activities feed (the dedicated
    markups endpoint does not exist).  Activities are fetched with
    pagination and indexed by DocumentId.

    Returns:
        Tuple of (attendance_list, markup_summary_list, markup_error_message_or_None).
    """
    attendance: list = []
    markup_summary: list = []
    markup_error: str | None = None

    # Attendance (fetches activities + users internally)
    with console.status("[bold green]Fetching session data...", spinner="dots"):
        try:
            attendance = build_attendance(client, session_id)
        except Exception as exc:
            console.print(f"[yellow]\u26a0 Could not fetch attendance: {exc}[/yellow]")

    console.print(
        f"[bold green]\u2714[/bold green] Attendance: {len(attendance)} user(s) found."
    )

    # Files + markup summary (derived from activities)
    try:
        with console.status("[bold green]Fetching session files...", spinner="dots"):
            files = fetch_session_files(client, session_id)

        console.print(
            f"[bold green]\u2714[/bold green] Files: {len(files)} file(s) in session."
        )

        if files:
            with console.status(
                "[bold green]Analysing markup activity...", spinner="dots"
            ):
                markup_summary = build_markup_summary(
                    client, session_id, files
                )

            console.print("[bold green]\u2714[/bold green] Markup data collected.")

    except Exception as exc:
        markup_error = str(exc)
        # Still return whatever attendance we have
        try:
            files = fetch_session_files(client, session_id)
            markup_summary = [
                {
                    "name": f.get("Name", f"File {f.get('Id', '?')}"),
                    "file_id": str(f.get("Id", "")),
                    "markup_authors": [],
                }
                for f in files
            ]
        except Exception:
            markup_summary = []

    return attendance, markup_summary, markup_error


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
