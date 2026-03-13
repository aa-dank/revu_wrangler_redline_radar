# Spec: bluebeam_py Extensions Required for Redline Radar

> This document specifies the minimum additions needed in [bluebeam_py](https://github.com/aa-dank/bluebeam_py) before the Redline Radar app can be built. It is a parallel spec — implement these in bluebeam_py; the app spec assumes they exist.

---

## 1. Bug Fixes (Pre-Requisites)

### 1a. Add httpx to dependencies

**File:** `pyproject.toml`

```toml
dependencies = ["httpx>=0.27"]
```

Currently `dependencies = []` but httpx is imported everywhere.

### 1b. Fix OAuth endpoint paths

**File:** `config.py`

The current code uses:
```python
OAUTH_AUTHORIZE_PATH = "/oauth/authorize"
OAUTH_TOKEN_PATH = "/oauth/token"
```

The Bluebeam developer docs (as of the 2024 platform migration) show:
```python
OAUTH_AUTHORIZE_PATH = "/oauth2/authorize"
OAUTH_TOKEN_PATH = "/oauth2/token"
```

**Verify which is correct for the current platform** — the `/oauth/` paths may be legacy. The [Authentication Guide](https://support.bluebeam.com/developer/authentication-guide.html) shows `/oauth2/` paths.

### 1c. README region code mismatch

README references `"EU"` and `"ANZ"` but config.py only maps `"US"`, `"DE"`, `"AU"`, `"UK"`, `"SE"`. Either add aliases or fix the README.

---

## 2. New Endpoint: List Session Users

### Purpose
Get all users (attendees) in a Studio Session — needed to show who has entered the session.

### API Endpoint
```
GET /publicapi/v1/sessions/{session_id}/users
```

### SDK Method
```python
# In SessionsAPI class (sessions.py)

@retry(...)
def list_users(self, session_id: str) -> Dict[str, Any]:
    """List all users/attendees in a Studio Session."""
    url = f"{self.base_url}{API_ROOT}/sessions/{session_id}/users"
    resp = self._http.get(url)
    raise_for_status_mapped(resp)
    return resp.json()
```

### Expected Response Shape
```json
{
  "Users": [
    {
      "Id": "user-guid-or-email",
      "Email": "user@ucsc.edu",
      "Name": "Jane Doe",
      ...
    }
  ]
}
```

> **NOTE:** Exact response fields need to be validated against the live API. The Postman collection confirms this endpoint exists.

---

## 3. New Endpoint: List Session Activities

### Purpose
Get the activity log for a session — join/leave events, markup events, etc. Needed to determine *when* each user first entered the session.

### API Endpoint
```
GET /publicapi/v1/sessions/{session_id}/activities
```

### SDK Method
```python
@retry(...)
def list_activities(self, session_id: str) -> Dict[str, Any]:
    """List all activities in a Studio Session (join, leave, markup events, etc.)."""
    url = f"{self.base_url}{API_ROOT}/sessions/{session_id}/activities"
    resp = self._http.get(url)
    raise_for_status_mapped(resp)
    return resp.json()
```

### Expected Response Shape
```json
{
  "Activities": [
    {
      "Id": "activity-id",
      "Type": "UserJoined",
      "User": "user@ucsc.edu",
      "Timestamp": "2026-03-13T10:30:00Z",
      ...
    }
  ]
}
```

### Pagination
Activities may be paginated for busy sessions. Consider adding optional `page` / `page_size` params if the API supports them (like `list_sessions` does).

---

## 4. New Endpoints: Session Markups (Beta)

### Purpose
List markups on a per-file basis within a session — needed to identify who has left markup on which files and when.

### API Endpoints

The Postman collection lists these under "Beta":

**a. List all markups on the session (across all files):**
```
GET /publicapi/v1/sessions/{session_id}/markups
```
(or possibly under a `/beta/` prefix — needs validation)

**b. List markups on a specific session file:**
```
GET /publicapi/v1/sessions/{session_id}/files/{file_id}/markups
```

**c. List valid markup statuses:**
```
GET /publicapi/v1/sessions/{session_id}/markups/statuses
```

### SDK Methods
```python
@retry(...)
def list_markups(self, session_id: str, file_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List markups in a session.

    If file_id is provided, returns markups for that specific file.
    If file_id is None, returns markups across all files in the session.
    """
    if file_id:
        url = f"{self.base_url}{API_ROOT}/sessions/{session_id}/files/{file_id}/markups"
    else:
        url = f"{self.base_url}{API_ROOT}/sessions/{session_id}/markups"
    resp = self._http.get(url)
    raise_for_status_mapped(resp)
    return resp.json()

@retry(...)
def list_markup_statuses(self, session_id: str) -> Dict[str, Any]:
    """List valid statuses for markups in a session."""
    url = f"{self.base_url}{API_ROOT}/sessions/{session_id}/markups/statuses"
    resp = self._http.get(url)
    raise_for_status_mapped(resp)
    return resp.json()
```

### Expected Markup Response Shape
```json
{
  "Markups": [
    {
      "Id": "markup-guid",
      "Subject": "Cloud",
      "Author": "Jane Doe",
      "Date": "2026-03-13T10:30:00Z",
      "ModifiedDate": "2026-03-13T11:00:00Z",
      "Status": "None",
      "Page": 3,
      "Comment": "Review this detail",
      ...
    }
  ]
}
```

> **IMPORTANT:** These are Beta endpoints. The exact paths and response schemas may differ from what's documented. The development process should include exploratory API calls to validate the actual behavior.

---

## 5. Optional: Get Single Session User

### API Endpoint
```
GET /publicapi/v1/sessions/{session_id}/users/{user_id}
```

### SDK Method
```python
@retry(...)
def get_user(self, session_id: str, user_id: str) -> Dict[str, Any]:
    """Get details for a single user in a Studio Session."""
    url = f"{self.base_url}{API_ROOT}/sessions/{session_id}/users/{user_id}"
    resp = self._http.get(url)
    raise_for_status_mapped(resp)
    return resp.json()
```

Lower priority — only needed if the list endpoint doesn't return sufficient detail.

---

## 6. Summary of Changes

| Area | Change | Priority |
|------|--------|----------|
| `pyproject.toml` | Add `httpx` to dependencies | **Must** |
| `config.py` | Verify/fix OAuth paths (`/oauth/` vs `/oauth2/`) | **Must** |
| `sessions.py` | Add `list_users()` | **Must** |
| `sessions.py` | Add `list_activities()` | **Must** |
| `sessions.py` | Add `list_markups()` | **Must** |
| `sessions.py` | Add `list_markup_statuses()` | Nice-to-have |
| `sessions.py` | Add `get_user()` | Nice-to-have |
| `README.md` | Fix region code documentation | Should |

### Testing Approach

Since these are new API integrations against a live service, the recommended approach is:

1. Implement each method with the expected endpoint path
2. Write a small test script (not committed to public repo) that:
   - Authenticates with a real BBID
   - Creates or uses an existing session with known state
   - Calls each new method and prints the raw response
3. Validate response shapes against this spec
4. Adjust field names and paths as needed
5. Consider adding response type hints (TypedDict or dataclass) once shapes are confirmed
