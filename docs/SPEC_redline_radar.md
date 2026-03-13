# Spec: Redline Radar — Bluebeam Studio Session Reporter

> **Project:** [revu_wrangler_redline_radar](https://github.com/aa-dank/revu_wrangler_redline_radar)
> **Author:** Aaron Dankert, UCSC PPDO Construction
> **Date:** 2026-03-13
> **Status:** Draft

---

## 1. Purpose

Redline Radar is a CLI tool that generates a standalone HTML summary report for a Bluebeam Studio Session. The report shows project managers (PMs) at UCSC PPDO:

1. **Who has entered the session** — and when they first joined (to confirm stakeholders and the EDP have at least opened the session)
2. **Who has left markup on which files** — and when they most recently placed markup (to see who has actively reviewed which documents)

The tool is packaged as a Windows executable (via PyInstaller) for non-technical PM users.

---

## 2. User Story

> As a UCSC PPDO Project Manager, I am running a Bluebeam Studio Session for a capital project document review (e.g., "90% Docs Review"). I have invited campus stakeholders and the Executive Design Professional (EDP/architect) to review construction drawings and specs. I need to quickly see who has actually looked at the documents and who has provided redline feedback, without manually checking each file in Revu.

---

## 3. Project Structure

```
revu_wrangler_redline_radar/
├── pyproject.toml              # uv project config
├── README.md
├── docs/
│   ├── RESEARCH_bluebeam_api.md
│   ├── RESEARCH_cli_ux_patterns.md
│   ├── SPEC_bluebeam_py_extensions.md
│   └── SPEC_redline_radar.md   # (this file)
├── src/
│   └── redline_radar/
│       ├── __init__.py
│       ├── __main__.py         # Entry point: `python -m redline_radar`
│       ├── cli.py              # CLI logic (Click + Rich)
│       ├── auth.py             # OAuth flow with local callback server
│       ├── api.py              # Data fetching & aggregation layer
│       ├── report.py           # Jinja2 HTML report generation
│       ├── config.py           # App configuration, paths, defaults
│       └── templates/
│           └── report.html     # Jinja2 HTML template
├── assets/                     # Optional: CSS, images for HTML report
└── tests/
    └── ...
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `bluebeam-py` | Bluebeam Studio API wrapper (git dependency) |
| `click` | CLI user input |
| `rich` | Formatted terminal output |
| `jinja2` | HTML report templating |
| `pyinstaller` | Packaging as .exe (dev dependency) |

**Python version:** 3.13+ (matching bluebeam_py)

**Project manager:** uv

---

## 4. Authentication Flow

### First Run
```
1. CLI starts
2. Check for saved token file (~/.redline_radar/tokens.json)
3. No token found → initiate OAuth:
   a. Start local HTTP server on http://localhost:5000
   b. Open browser to Bluebeam authorize URL
   c. User logs in to Bluebeam, grants access
   d. Bluebeam redirects to http://localhost:5000/callback?code=...
   e. Local server captures the auth code
   f. Exchange code for access_token + refresh_token
   g. Save tokens to ~/.redline_radar/tokens.json
   h. Shut down local server
4. Proceed to session input
```

### Subsequent Runs
```
1. CLI starts
2. Load tokens from ~/.redline_radar/tokens.json
3. If access_token expired:
   a. Use refresh_token to get new tokens
   b. Save updated tokens
4. Proceed to session input
```

### Token File Location
- Windows: `%USERPROFILE%\.redline_radar\tokens.json`
- Structure: `{ "access_token": "...", "refresh_token": "...", "expires_at": 1234567890 }`

### Security Notes (Public Repo Awareness)
- **client_id and client_secret must NOT be hardcoded in source**
- Options:
  - Environment variables: `BLUEBEAM_CLIENT_ID`, `BLUEBEAM_CLIENT_SECRET`
  - Config file: `~/.redline_radar/config.json` (created on first setup)
  - Bundled with exe but obfuscated (least secure, but pragmatic for internal tool)
- Token file should be user-read-only permissions where possible
- The redirect_uri (`http://localhost:5000/callback`) must be registered in the Bluebeam Developer Portal

### Local Callback Server

Minimal HTTP server (stdlib `http.server` or a lightweight approach):
```python
# Pseudocode
class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse ?code=... from query string
        # Store auth code
        # Return HTML: "Authorization successful! You can close this tab."
        # Signal main thread to continue
```

The server binds to `127.0.0.1:5000`, handles exactly one request, then shuts down. A timeout (e.g., 120 seconds) prevents hanging if the user never completes auth.

---

## 5. CLI Flow

### Step 1: Launch
```
╔══════════════════════════════════════════════════╗
║  ██████  ███████ ██████  ██      ██ ███  ██ ███  ║
║  ██   ██ ██      ██   ██ ██      ██ ████ ██ ██   ║
║  ██████  █████   ██   ██ ██      ██ ██ ████ ███  ║
║  ██   ██ ██      ██   ██ ██      ██ ██  ███ ██   ║
║  ██   ██ ███████ ██████  ███████ ██ ██   ██ ███  ║
║                                                   ║
║          Redline Radar v0.1.0                     ║
║       Bluebeam Session Summary Reporter           ║
╚══════════════════════════════════════════════════╝
       Press CTRL+C at any time to exit.
```
(ASCII art is aspirational — exact design TBD)

### Step 2: Authentication (if needed)
```
⠋ Checking authentication...
⚠ No saved credentials found. Starting Bluebeam login...
  Opening browser for Bluebeam authorization...
  Waiting for authorization (timeout: 2 minutes)...
✔ Authorized as jane.doe@ucsc.edu
```

### Step 3: Session Input
```
━━━━━━━━━━━━ Session Input ━━━━━━━━━━━━
Paste a Session ID, URL, or invitation text:
> You have been invited by constdoc to join a Bluebeam Studio Session:
> 2303-019 90percent Docs Review, completion 3-16-2026
> Session ID: 117-770-339
> Session URL: https://studio.bluebeam.com/hyperlink.html?...

✔ Session ID extracted: 117-770-339
```

**Input parsing logic:**
```python
import re

def extract_session_id(raw_input: str) -> str | None:
    """Extract a Bluebeam Session ID (NNN-NNN-NNN) from arbitrary text."""
    match = re.search(r'\d{3}-\d{3}-\d{3}', raw_input)
    return match.group(0) if match else None
```

The prompt should accept multi-line paste. Use `click.prompt` or gather lines until a blank line / the regex matches.

### Step 4: Fetch & Confirm
```
⠋ Fetching session info...
┌──────────────────────────────────────────────────┐
│ Session: 2303-019 90percent Docs Review          │
│ ID:      117-770-339                             │
│ Status:  Active                                  │
│ Files:   12                                      │
│ Users:   8                                       │
└──────────────────────────────────────────────────┘
Generate report for this session? [Y/n]:
```

### Step 5: Data Collection
```
⠋ Fetching session attendees...          ✔
⠋ Fetching activity log...               ✔
⠋ Fetching markups for file 1/12...      ✔
⠋ Fetching markups for file 2/12...      ✔
...
⠋ Fetching markups for file 12/12...     ✔
```

Consider using `rich.progress` for the file-by-file markup fetch:
```python
with Progress() as progress:
    task = progress.add_task("Fetching markups...", total=len(files))
    for f in files:
        markups = client.sessions.list_markups(session_id, f["Id"])
        progress.advance(task)
```

### Step 6: Report Generation
```
✔ Report generated: 2303-019_session_report_2026-03-13_121500.html
  Saved to: C:\Users\jdoe\Downloads\2303-019_session_report_2026-03-13_121500.html

Check another session? [y/N]:
```

---

## 6. HTML Report Design

### Filename Format
```
{session_name_slug}_session_report_{YYYY-MM-DD}_{HHMMSS}.html
```
Example: `2303-019_90percent_docs_review_session_report_2026-03-13_121500.html`

### Report Structure

The HTML file is **self-contained** (all CSS inline or in `<style>` tags, no external dependencies) so it can be emailed, shared on a file server, or opened anywhere.

```html
<!DOCTYPE html>
<html>
<head>
    <title>Session Report: {{ session.Name }} — Generated {{ timestamp }}</title>
    <style>/* Bootstrap-inspired minimal CSS */</style>
</head>
<body>

    <!-- Header -->
    <header>
        <h1>Studio Session Report</h1>
        <p>{{ session.Name }}</p>
        <p>Session ID: {{ session.Id }} | Generated: {{ timestamp }}</p>
    </header>

    <!-- Section 1: Session Attendance -->
    <section id="attendance">
        <h2>Session Attendance</h2>
        <p>Who has entered this session and when they were first seen.</p>
        <table>
            <tr><th>Name / Email</th><th>First Seen</th></tr>
            {% for user in attendance %}
            <tr>
                <td>{{ user.name }}</td>
                <td>{{ user.first_seen }}</td>
            </tr>
            {% endfor %}
        </table>
    </section>

    <!-- Section 2: Markup Activity by File -->
    <section id="markups">
        <h2>Markup Activity by File</h2>
        <p>Who has left markup on each file and when they last did so.</p>

        {% for file in files %}
        <h3>{{ file.name }}</h3>
        {% if file.markup_authors %}
        <table>
            <tr><th>Author</th><th>Markup Count</th><th>Most Recent</th></tr>
            {% for author in file.markup_authors %}
            <tr>
                <td>{{ author.name }}</td>
                <td>{{ author.count }}</td>
                <td>{{ author.latest_date }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p class="no-markups">No markups on this file.</p>
        {% endif %}
        {% endfor %}
    </section>

    <!-- Footer -->
    <footer>
        <p>Generated by Redline Radar v{{ version }} | {{ timestamp }}</p>
    </footer>

</body>
</html>
```

### Visual Design Notes
- Use Bootstrap 5 CSS (inline, minified) or a minimal custom stylesheet
- Color coding: files with no markups could be highlighted (e.g., light yellow background)
- The attendance table could use a green checkmark icon for "has entered"
- Responsive layout (PMs may view on various screen sizes)
- Print-friendly: include `@media print` styles

### Alternative Design Ideas
- **Heatmap/matrix view:** Rows = users, columns = files, cells = markup count. Gives an at-a-glance view of coverage. Empty cells show gaps.
- **Accordion per file:** Collapsible sections for each file. Header shows file name + total markup count. Expand to see author details.
- **Summary stats at top:** Total markups, total reviewers active, files with zero markups, etc.

---

## 7. Data Aggregation Logic

### Attendance Data
```python
def build_attendance(activities: list[dict]) -> list[dict]:
    """
    From session activities, extract the first 'join' event per user.
    Returns sorted list of { name, email, first_seen }.
    """
    first_seen = {}
    for activity in activities:
        if activity.get("Type") in ("UserJoined", "Join", ...):  # exact type TBD
            user_key = activity.get("User") or activity.get("Email")
            timestamp = activity.get("Timestamp")
            if user_key not in first_seen or timestamp < first_seen[user_key]["first_seen"]:
                first_seen[user_key] = {
                    "name": activity.get("UserName", user_key),
                    "email": user_key,
                    "first_seen": timestamp,
                }
    return sorted(first_seen.values(), key=lambda x: x["first_seen"])
```

**Fallback:** If the activities endpoint doesn't provide join timestamps, fall back to the users list (presence = has joined, but no timestamp).

### Markup Summary Data
```python
def build_markup_summary(files: list[dict], session_id: str, client) -> list[dict]:
    """
    For each file in the session, fetch markups and aggregate by author.
    Returns list of { name, file_id, markup_authors: [{ name, count, latest_date }] }
    """
    result = []
    for file in files:
        markups_resp = client.sessions.list_markups(session_id, file["Id"])
        markups = markups_resp.get("Markups", [])

        author_stats = {}
        for m in markups:
            author = m.get("Author", "Unknown")
            date = m.get("Date") or m.get("ModifiedDate")
            if author not in author_stats:
                author_stats[author] = {"name": author, "count": 0, "latest_date": date}
            author_stats[author]["count"] += 1
            if date and date > author_stats[author]["latest_date"]:
                author_stats[author]["latest_date"] = date

        result.append({
            "name": file.get("Name", f"File {file['Id']}"),
            "file_id": file["Id"],
            "markup_authors": sorted(
                author_stats.values(),
                key=lambda x: x["latest_date"],
                reverse=True
            ),
        })
    return result
```

---

## 8. Configuration

### Config File: `~/.redline_radar/config.json`
```json
{
    "client_id": "your-bluebeam-client-id",
    "client_secret": "your-bluebeam-client-secret",
    "redirect_uri": "http://localhost:5000/callback",
    "region": "US",
    "output_dir": "~/Downloads"
}
```

### Environment Variable Overrides
| Variable | Purpose |
|----------|---------|
| `BLUEBEAM_CLIENT_ID` | OAuth client ID |
| `BLUEBEAM_CLIENT_SECRET` | OAuth client secret |
| `REDLINE_RADAR_OUTPUT_DIR` | Override default output directory |

**Precedence:** env vars > config file > defaults

### First-Run Setup
If no config file exists and no env vars are set, the CLI should prompt:
```
No configuration found. Let's set up Redline Radar.
Bluebeam Client ID: ___
Bluebeam Client Secret: ___
Save configuration to ~/.redline_radar/config.json? [Y/n]:
```

---

## 9. Packaging with PyInstaller

### Build Command
```bash
pyinstaller --onefile --name redline_radar src/redline_radar/__main__.py
```

### Bundled Assets
The Jinja2 template (`report.html`) needs to be bundled:
```python
# In pyinstaller spec or via --add-data
# --add-data "src/redline_radar/templates;redline_radar/templates"
```

### Template Path Resolution
```python
import sys
from pathlib import Path

def get_template_dir() -> Path:
    """Resolve template directory for both dev and PyInstaller contexts."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS) / "redline_radar" / "templates"
    else:
        # Running from source
        return Path(__file__).parent / "templates"
```

### Distribution
The resulting `redline_radar.exe` is a single file that PMs can put anywhere and double-click (it will open a command prompt window) or run from cmd/PowerShell.

---

## 10. Error Handling

| Scenario | Behavior |
|----------|----------|
| No internet connection | Red error message, prompt to retry |
| Invalid session ID format | Red message, re-prompt |
| Session not found (404) | Red message: "Session 117-770-339 not found. Check the ID and ensure you have access." |
| Auth token expired, refresh fails | Re-initiate OAuth flow |
| Rate limited (429) | Automatic retry (handled by bluebeam_py) + status message |
| Markup endpoint returns error (Beta instability) | Yellow warning, skip markups section, still show attendance |
| File write permission error | Red error with path, suggest alternative |
| User cancels OAuth in browser | Timeout after 120s, red message, option to retry |

---

## 11. Open Questions

1. **Markup endpoint exact paths:** The Beta markup endpoints need to be tested against the live API to confirm URL patterns and response schemas.
2. **Activity types:** What are the exact `Type` values returned by the activities endpoint? Need to test to determine filtering logic.
3. **Pagination:** Do markup lists paginate? If a file has hundreds of markups, does the API return them all or require paging?
4. **`read_prime` scope sufficiency:** Can we use the read-only scope for all data access, or does the markup Beta endpoint require `full_user`?
5. **Multi-line paste in CLI:** `click.prompt` handles single-line input. For pasting invitation text blocks, we may need a custom input loop or instruct users to just paste (the regex will find the ID regardless).
6. **Output directory:** Default to `~/Downloads` or the current working directory?
7. **Session name in filename:** The session name may contain special characters. Need a slug function to sanitize for filenames.

---

## 12. Future Enhancements (Out of Scope for v1)

- CSV/Excel export alongside HTML
- Diff reports (compare two snapshots of the same session over time)
- Scheduled/automated runs (e.g., daily session status emails)
- Web-based version (Flask/FastAPI) instead of CLI+HTML
- Integration with UCSC PPDO project tracking systems
- Support for Studio Projects (not just Sessions)
- Markup detail view (content of markups, not just counts)
