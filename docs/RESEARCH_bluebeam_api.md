# Research: Bluebeam Studio API — Endpoints Relevant to Redline Radar

> Compiled 2026-03-13. Sources: [Bluebeam Developer Portal](https://developers.bluebeam.com/s/studio), [Studio Session Guide](https://support.bluebeam.com/developer/studio-session-guide.html), [Authentication Guide](https://support.bluebeam.com/developer/authentication-guide.html), [Bluebeam Postman Workspace](https://www.postman.com/bluebeam-developers/workspace/bluebeam-api/overview), and the existing [revu_wrangler](https://github.com/aa-dank/revu_wrangler) SDK (formerly bluebeam_py).

---

## 1. API Overview

The Bluebeam Studio API is RESTful with JSON request/response bodies over HTTPS. All calls are made under the context of an authenticated user via OAuth 2.0.

**Base URLs (region-specific):**

| Region | Base URL |
|--------|----------|
| US | `https://api.bluebeam.com` |
| DE | `https://api.bluebeamstudio.de` |
| AU | `https://api.bluebeamstudio.com.au` |
| UK | `https://api.bluebeamstudio.co.uk` |
| SE | `https://api.bluebeamstudio.se` |

**API Root:** `/publicapi/v1`

**Required headers on every request:**
- `Authorization: Bearer {access_token}`
- `client_id: {your_client_id}`
- `Content-Type: application/json` (for requests with bodies)

---

## 2. Authentication

### OAuth 2.0 Authorization Code Flow

The API uses a standard three-legged OAuth flow:

1. **Redirect user to authorize:**
   ```
   GET {base_url}/oauth2/authorize?response_type=code&client_id={id}&redirect_uri={uri}&scope={scopes}&state={csrf}
   ```
2. **User logs in, grants access** → Bluebeam redirects to `redirect_uri` with `?code={auth_code}&state={csrf}`
3. **Exchange code for tokens:**
   ```
   POST {base_url}/oauth2/token
   grant_type=authorization_code&code={code}&redirect_uri={uri}&client_id={id}&client_secret={secret}
   ```
   Response: `{ access_token, refresh_token, expires_in, token_type, scope }`
4. **Refresh when expired:**
   ```
   POST {base_url}/oauth2/token
   Authorization: Basic {base64(client_id:client_secret)}
   grant_type=refresh_token&refresh_token={token}
   ```

### Scopes

| Scope | Description |
|-------|-------------|
| `read_prime` | Read-only access to Projects and Sessions (reporting) |
| `full_user` | Full access to user-owned Projects and Sessions |
| `jobs` | Access automated Jobs in Projects |
| `offline_access` | Receive a refresh_token (required for token persistence) |

**For this app:** We need `full_user` (or `read_prime` if sufficient for read-only reporting) + `offline_access`.

### Token Lifecycle
- Access tokens expire in ~1 hour (`expires_in` seconds)
- Refresh tokens stay valid as long as used at least once every **7 days**
- Exchanging a refresh token yields both a new access_token AND a new refresh_token

---

## 3. Session Endpoints — Currently in revu_wrangler

These endpoints are already implemented in the SDK:

| Endpoint | Method | SDK Method | Notes |
|----------|--------|------------|-------|
| `/publicapi/v1/sessions` | POST | `create_session()` | Create a session |
| `/publicapi/v1/sessions` | GET | `list_sessions()` | List all sessions (paginated) |
| `/publicapi/v1/sessions/{id}` | GET | `get_session()` | Get session metadata |
| `/publicapi/v1/sessions/{id}` | DELETE | `delete_session()` | Delete a session |
| `/publicapi/v1/sessions/{id}/files` | POST | `_create_file_placeholder()` | Upload step 1 |
| `/publicapi/v1/sessions/{id}/files` | GET | `list_files()` | List files in session |
| `/publicapi/v1/sessions/{id}/files/{fid}` | GET | `get_file()` | Get file metadata |
| `/publicapi/v1/sessions/{id}/files/{fid}/confirm-upload` | POST | `_confirm_upload()` | Upload step 3 |
| `/publicapi/v1/sessions/{id}/files/{fid}/snapshot` | POST | `request_snapshot()` | Request snapshot |
| `/publicapi/v1/sessions/{id}/files/{fid}/snapshot` | GET | `get_snapshot_status()` | Poll snapshot status |

---

## 4. Session Endpoints — MISSING from revu_wrangler (Needed for This App)

### 4a. Session Users

| Endpoint | Method | Purpose | Priority |
|----------|--------|---------|----------|
| `/publicapi/v1/sessions/{id}/users` | GET | **List all users/attendees in session** | **CRITICAL** |
| `/publicapi/v1/sessions/{id}/users/{uid}` | GET | Get single user details | Nice-to-have |
| `/publicapi/v1/sessions/{id}/users` | POST | Add user to session | Not needed |
| `/publicapi/v1/sessions/{id}/invite` | POST | Invite user by email | Not needed |
| `/publicapi/v1/sessions/{id}/users/{uid}` | PUT | Update user in session | Not needed |

**Expected response for GET users** (based on API patterns and Postman collection):
```json
{
  "Users": [
    {
      "Id": "user-guid",
      "Email": "user@example.com",
      "Name": "Jane Doe",
      "Role": "Host|Attendee",
      "Status": "Active|Invited",
      ...
    }
  ]
}
```

### 4b. Session Activities

| Endpoint | Method | Purpose | Priority |
|----------|--------|---------|----------|
| `/publicapi/v1/sessions/{id}/activities` | GET | **List all session activities (join/leave/markup events)** | **CRITICAL** |
| `/publicapi/v1/sessions/{id}/activities/{aid}` | GET | Get single activity | Nice-to-have |
| `/publicapi/v1/sessions/{id}/activities` | POST | Create activity | Not needed |

**Expected activity types** (based on Bluebeam Session Record UI):
- User joined session
- User left session
- Markup placed
- Markup alert sent
- File added
- Chat message

**Expected activity data fields:**
```json
{
  "Activities": [
    {
      "Id": "activity-id",
      "Type": "UserJoined|UserLeft|MarkupPlaced|...",
      "User": "user@example.com",
      "UserName": "Jane Doe",
      "Timestamp": "2026-03-13T10:30:00Z",
      "Details": "...",
      ...
    }
  ]
}
```

### 4c. Session Markups (Beta)

These were discovered in the Postman collection under "Beta (Projects)" but the naming references Sessions:

| Endpoint | Method | Purpose | Priority |
|----------|--------|---------|----------|
| `GET` | Returns detailed list of markups on the Session | **CRITICAL** | **CRITICAL** |
| `GET` | Returns list of markups on a Session document (per-file) | **CRITICAL** | **CRITICAL** |
| `PUT` | Updates the status of a Session markup | Not needed | — |
| `GET` | Returns list of valid statuses for markups on Session | Nice-to-have | — |

**Expected markup data fields** (based on Bluebeam Markups List UI and community reports):
```json
{
  "Markups": [
    {
      "Id": "markup-guid",
      "Subject": "Cloud|Rectangle|Text|Highlight|...",
      "Author": "Jane Doe",
      "AuthorEmail": "user@example.com",
      "Date": "2026-03-13T10:30:00Z",
      "ModifiedDate": "2026-03-13T11:00:00Z",
      "Status": "None|Accepted|Rejected|...",
      "Label": "...",
      "Page": 3,
      "Comment": "Review this section...",
      "Color": "#FF0000",
      ...
    }
  ]
}
```

> **NOTE:** The exact endpoint paths for session markups are not fully documented in public resources. The Postman collection shows these under a "Beta" folder, which suggests the URL pattern may include `/beta/` or may use the standard path with beta-level stability. **This needs to be validated against the actual API during development.**

### 4d. Session Update

| Endpoint | Method | Purpose | Priority |
|----------|--------|---------|----------|
| `/publicapi/v1/sessions/{id}` | PUT | Update session (e.g., set status to "Finalizing") | Low for this app |

---

## 5. Data We Need for the Report

### Report Section 1: "Who Has Entered the Session"

**Data needed:** For each person who has joined the session, their name/email and the first time they joined.

**Best source:** Session Activities endpoint (filter for join events) OR Session Users endpoint (may include a "joined" timestamp).

**Fallback:** If activities don't include timestamps, the Users list at minimum tells us who is in the session currently or was added.

### Report Section 2: "Who Has Left Markup on Each File"

**Data needed:** Per-file in the session, which users have placed markups and when they most recently did so.

**Best source:** Session Markups endpoint (per-file), grouped by author, taking `max(Date)` per author per file.

**Data flow:**
```
list_files(session_id) → for each file_id:
    get_markups(session_id, file_id) → group by author → max(date) per author
```

---

## 6. Known Risks and Unknowns

1. **Markup endpoints are Beta** — may change without notice or have inconsistent behavior
2. **Exact endpoint paths for session markups are unclear** — Postman collection descriptions reference "Session" but are filed under "Projects (Beta)". Need to test both:
   - `/publicapi/v1/sessions/{id}/files/{fid}/markups` (intuitive guess)
   - Some beta-prefixed path
3. **Activity endpoint response schema is undocumented publicly** — we know it exists from the Postman collection but don't know exact field names until we call it
4. **Rate limiting** — API returns 429 with `Retry-After` header; the SDK handles this with retries, but bulk queries across many files could trigger it
5. **`read_prime` vs `full_user` scope** — unclear if read-only scope is sufficient for markup and activity reads. May need `full_user`.
6. **Pagination** — markup lists for large sessions (hundreds of markups per file) may be paginated. Need to handle cursor/page iteration.

---

## 7. Bluebeam Session Concepts Reference

For developers unfamiliar with Bluebeam Studio:

- **Studio Session**: A "digital conference room" where one or more PDF files are shared for real-time or async markup/review. Identified by a 9-digit Session ID (e.g., `117-770-339`).
- **Host**: The user who created the session. Has full control.
- **Attendee**: Any user who has joined or been invited to the session.
- **Markup**: An annotation placed on a PDF — could be a cloud, rectangle, text note, highlight, etc. Each markup has an author, date, subject type, optional status, and optional comments.
- **Snapshot**: A flattened PDF combining the base document with all its markups into a single file. Used for downloading/archiving.
- **Session Record/Report**: A built-in Bluebeam feature that shows a chronological history of markups, comments, and chat messages. Our app is essentially an API-driven version of a subset of this.
- **Restricted Session**: Only explicitly invited email addresses can join.
- **Session End Date**: Auto-removes attendees when reached.

---

## 8. Session ID Format

The 9-digit Session ID follows the pattern `NNN-NNN-NNN` where each segment is 3 digits.

**Common formats PMs may provide:**
- Plain ID: `117-770-339`
- Session URL: `https://studio.bluebeam.com/hyperlink.html?link=studio.bluebeam.com/sessions/117-770-339`
- Invitation text block containing the ID embedded in multi-line text

**Regex to extract:** `\d{3}-\d{3}-\d{3}`
