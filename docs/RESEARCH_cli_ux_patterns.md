# Research: CLI/UX Patterns — Reference from xmtl_factory

> Compiled 2026-03-13. Reference project: [xmtl_factory](https://github.com/aa-dank/xmtl_factory). This document captures CLI interaction patterns to replicate in Redline Radar.

---

## 1. Architecture: Click for Input, Rich for Output

The reference project uses a clean separation:

- **Click** (`click.prompt`, `click.confirm`) — handles all user input with readline-style editing
- **Rich** (`Console`, `Table`, `Panel`, `Align`, rules, inline markup) — handles all formatted output
- **No Click command decorators** — the app is a single linear workflow, not a multi-subcommand CLI

This pattern works well for tools with a simple linear flow (launch → collect input → do work → show results → optionally repeat).

---

## 2. Visual Hierarchy

### Color Semantics

| Color | Meaning | Example Usage |
|-------|---------|---------------|
| `bold green` | Success, positive outcomes | `✔ Confirmed`, `✔ Report generated!` |
| `green` | Informational positive | `No EDP info will be included` |
| `bold yellow` | Section headers, emphasis | Rule titles, panel titles |
| `yellow` | Templates, instructions, options | Template key tables |
| `red` | Errors, validation failures | `Missing required fields: [...]` |
| `bold red` | Critical errors, cancellation | `✖ Process Cancelled`, Ctrl+C hint |
| `italic dim` | Version/subtitle, minor hints | Version string, secondary info |
| `dim` | Divider rules, exit hints | Rule separators |
| `cyan` | Filenames, paths, IDs | Inline within success messages |
| `#333FFF` / `#8691F6` | Table field names / values | Data review tables |

### Layout Elements

| Element | Rich Class | Usage |
|---------|-----------|-------|
| ASCII art banner | `console.print(art, highlight=False)` | App launch branding |
| Instructional box | `Panel(text, title=..., border_style="yellow")` | How-to-use info |
| Section divider | `console.rule("Title", style="yellow")` | Between workflow steps |
| Data display | `Table(title=..., add_column(...))` | Review tables, template keys |
| Centered text | `Align.center(text)` | Version, exit hints, goodbye |
| Inline formatting | Rich markup `[bold green]...[/bold green]` | Mixed-style messages |

---

## 3. User Interaction Patterns

### Text Input
```python
value = click.prompt("Enter something (e.g. example)", default="")
```
- Always provide `default=""` for optional fields (Enter to skip)
- Include example values in the prompt text itself
- No fancy validation on input — handle it after collection

### Yes/No Confirmation
```python
click.confirm("Does everything look correct?", default=True)   # Y/n
click.confirm("Generate another?", default=False)               # y/N
```
- Default should match the "safe" or "expected" action

### Selection from a List
Display options as a Rich table, then prompt for a key:
```python
table = Table(border_style="yellow")
table.add_column("Options", style="yellow")
for key in options:
    table.add_row(key)
console.print(table)
choice = click.prompt("Enter your choice", default="")
```
- No arrow-key menus — just display + type

### Progress/Status
The reference project uses simple sequential prints. For our app (which makes API calls), consider using Rich's `Status` spinner:
```python
with console.status("[bold green]Fetching session data...", spinner="dots"):
    data = api_call()
```

---

## 4. Application Flow Pattern

```
┌─────────────────────────────────────┐
│ 1. LAUNCH                           │
│    - Banner / branding              │
│    - Version subtitle               │
│    - How-to-use panel               │
├─────────────────────────────────────┤
│ 2. COLLECT INPUT                    │
│    - Prompt for session ID/URL      │
│    - Validate / extract ID          │
│    - Show what was understood       │
├─────────────────────────────────────┤
│ 3. FETCH DATA (with spinners)       │
│    - Authenticate if needed         │
│    - Fetch session metadata         │
│    - Fetch users / activities       │
│    - Fetch files + markups per file │
├─────────────────────────────────────┤
│ 4. GENERATE REPORT                  │
│    - Render HTML via Jinja2         │
│    - Save to file with timestamp    │
├─────────────────────────────────────┤
│ 5. SUCCESS & REPEAT                 │
│    - Show output path               │
│    - Offer to generate another      │
│    - Or exit with goodbye           │
└─────────────────────────────────────┘
```

---

## 5. Key Patterns to Replicate

### Ctrl+C Exit Hint
```python
console.print(Align.center(
    "Press [bold red][CTRL+C][/bold red] at any time to exit.",
    style="dim"
))
```

### Success with Filename
```python
console.print(f"[bold green]✔ Report '[cyan]{filename}[/cyan]' generated![/bold green]")
```

### Error with Recovery
```python
console.print("Could not connect to Bluebeam API", style="red")
# Don't sys.exit — let the loop retry or prompt again
```

### Confirmation Gate Before Action
Show a summary of what will happen, then confirm:
```python
table = Table(title="Session Summary")
# ... populate with session name, ID, file count ...
console.print(table)
if not click.confirm("Generate report for this session?", default=True):
    console.print("✖ Cancelled\n", style="bold red")
    continue
```

---

## 6. Differences from xmtl_factory

| Aspect | xmtl_factory | Redline Radar |
|--------|-------------|---------------|
| Input complexity | ~12 fields, templates | 1 field (session ID/URL) |
| Processing time | Instant (local PDF) | Seconds (API calls) |
| Progress feedback | None needed | Spinners for API calls |
| Auth requirement | None | OAuth 2.0 flow |
| Output | PDF file | HTML file |
| Repeat loop | Generate another? | Check another session? |
| Error recovery | Re-prompt fields | Retry API / re-enter ID |

The simpler input model means our flow is more linear — the main UX challenge is the OAuth dance on first run and providing clear progress during API data collection.
