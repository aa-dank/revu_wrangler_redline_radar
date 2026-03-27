# Development Scripts

Exploratory scripts for validating Bluebeam Studio API behavior against the live service. These scripts answer open questions from the spec before we commit to implementation details.

## Prerequisites

1. **Install revu_wrangler** (from the sibling repo):
   ```bash
   uv pip install -e ../revu_wrangler   # or wherever your local clone lives
   ```
   Or add as a git dependency in your dev environment.

2. **Create a `.env` file** in the project root (it's gitignored):
   ```
   BLUEBEAM_CLIENT_ID=your-client-id
   BLUEBEAM_CLIENT_SECRET=your-client-secret
   BLUEBEAM_REDIRECT_URI=http://localhost:5000/callback
   BLUEBEAM_REGION=US
   ```

3. **Have an active Studio Session** with some markups and multiple attendees. You'll need the session ID (e.g., `117-770-339`).

## Scripts

| Script | Open Question |
|--------|---------------|
| `explore_activities.py` | What activity `Type` values does the API return? What fields are on each activity? |
| `export_session_activities_excel.py` | What does the full session activity stream look like when flattened into a spreadsheet for audit/reconciliation? |
| `explore_markups_pagination.py` | Do markup lists paginate? What does the response envelope look like? |
| `explore_scope_requirements.py` | Can `read_prime` scope access markups/activities, or is `full_user` required? |

## Usage

Each script uses a shared auth helper (`_auth_helper.py`) that handles the OAuth flow with a local callback server. On first run it opens your browser; after that it reuses saved tokens.

```bash
cd development
python explore_activities.py 117-770-339
python export_session_activities_excel.py 117-770-339
python explore_markups_pagination.py 117-770-339
python explore_scope_requirements.py 117-770-339
```

Token state is saved to `tokens.json` in the project root (gitignored).

## Output

Scripts print raw JSON responses to stdout and save structured results to `development/output/` (also gitignored). Review these to update the specs with confirmed field names and behavior.

The activity spreadsheet exporter writes both a timestamped `.xlsx` workbook and the raw JSON payload it was derived from so the flattened rows can be compared back to the source response.
