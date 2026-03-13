"""
Report generation: renders a self-contained HTML file from session data.

Output filename format::

    {session_name_slug}_session_report_{YYYY-MM-DD}_{HHMMSS}.html

Example::

    2303-019_90percent_docs_review_session_report_2026-03-13_121500.html
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from redline_radar import __version__
from redline_radar.config import OUTPUT_DIR, get_template_dir


def _slugify(text: str) -> str:
    """
    Convert a session name to a filesystem-safe slug.

    Rules:
      - Lowercase
      - Replace non-alphanumeric characters (except hyphens) with underscores
      - Collapse multiple underscores
      - Strip leading/trailing underscores
      - Truncate to 80 characters
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\-]+", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    slug = slug.strip("_")
    return slug[:80]


def generate_report(
    *,
    session_info: dict[str, Any],
    attendance: list[dict[str, Any]],
    files: list[dict[str, Any]],
    output_dir: Path | None = None,
) -> Path:
    """
    Render the Jinja2 HTML template and write it to disk.

    Args:
        session_info: Session metadata dict (must have at least ``Name``).
        attendance: List of attendee dicts with ``name``, ``email``, ``first_seen``.
        files: List of file markup summary dicts with ``name``, ``markup_authors``.
        output_dir: Override the default output directory (user's Downloads).

    Returns:
        Path to the generated HTML file.

    Raises:
        OSError: If the output directory is not writable.
    """
    dest_dir = output_dir or OUTPUT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Build filename
    session_name = session_info.get("Name", "session")
    slug = _slugify(session_name)
    now = datetime.now()
    timestamp_file = now.strftime("%Y-%m-%d_%H%M%S")
    timestamp_display = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"{slug}_session_report_{timestamp_file}.html"
    output_path = dest_dir / filename

    # Compute summary stats
    total_markups = sum(
        sum(a.get("count", 0) for a in f.get("markup_authors", []))
        for f in files
    )
    files_with_no_markups = sum(
        1 for f in files if not f.get("markup_authors")
    )

    # Render template
    template_dir = get_template_dir()
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
    template = env.get_template("report.html")

    html = template.render(
        session=session_info,
        session_id=session_info.get("Id", ""),
        attendance=attendance,
        files=files,
        version=__version__,
        timestamp=timestamp_display,
        total_markups=total_markups,
        files_with_no_markups=files_with_no_markups,
    )

    # Write
    output_path.write_text(html, encoding="utf-8")

    return output_path
