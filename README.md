# Redline Radar

A CLI tool that generates standalone HTML summary reports for Bluebeam Studio Sessions. Built for UCSC PPDO (Physical Planning, Development & Operations) project managers to quickly see who has entered a session and who has markup activity on each file.

## Documentation

- [App Specification](docs/SPEC_redline_radar.md) — Full spec for Redline Radar
- [Bluebeam API Research](docs/RESEARCH_bluebeam_api.md) — Research on relevant Studio API endpoints
- [CLI/UX Patterns](docs/RESEARCH_cli_ux_patterns.md) — Reference CLI interaction patterns
- [bluebeam_py Extensions Spec](docs/SPEC_bluebeam_py_extensions.md) — Required additions to the bluebeam_py dependency

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for package management.

```bash
uv sync
```

Each generated HTML report is paired with an Excel workbook containing the raw flattened activity feed and an enriched activity sheet derived from the same canonical data pipeline used for the report.
