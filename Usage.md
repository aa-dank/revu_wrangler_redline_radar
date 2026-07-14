# Revu Wrangler Redline Radar

## Overview

Revu Wrangler Redline Radar generates attendance and markup activity reports for Bluebeam Studio Sessions.

The application retrieves session information from the Bluebeam API, caches activity data locally, and generates HTML and Excel reports.

---

# Requirements

- Bluebeam Studio account
- Valid API credentials
- Internet connection

---

# Permissions

To generate a report, the authenticated Bluebeam account must be a member of the session. 

If the account is able to join and view a session in Bluebeam, it should also be able to generate a report for that session. The application only retrieves session information and does not modify any session data.

The application uses Bluebeam's read-only API permissions and follows the principle of least privilege. No additional administrative privileges or ownership of the Studio Session are required by the application itself. If a report cannot be generated, first verify that the authenticated account has access to the Studio Session.

---

# Running the Application

## Executable

Double-click `redline_radar.exe`

or run from a command prompt:

```text
./redline_radar.exe
```

## Command Line

To automatically generate a report for a known session:

```text
./redline_radar.exe <session_input>
```

Example:

```text
./redline_radar.exe 117-770-339
```

### Command Line Options

**`--debug`** – Enable debug logging

Enables detailed debug logging to a timestamped file for troubleshooting authentication and token issues.

```text
./redline_radar.exe --debug
```

Or with a session ID:

```text
./redline_radar.exe 117-770-339 --debug
```

Debug logs are saved to:

```text
C:\Users\<username>\.redline_radar\logs\redline_radar_YYYY-MM-DD_HHMMSS.log
```

Each run with `--debug` creates a new timestamped log file containing detailed information about the OAuth flow, token persistence, and authentication attempts.

---

# Typical Workflow

1. Launch the application.
2. Authenticate with Bluebeam (first run only).
3. Enter or paste a Studio Session ID, URL, or invitation.
4. The application retrieves session information and activity data.
5. An HTML report and Excel workbook are generated in the Downloads folder.

---

# Session Input

The application accepts any of the following:

- Studio Session ID
- Studio Session URL
- Bluebeam invitation text containing a Session ID

The Session ID is automatically extracted before the report is generated.

---

# Generated Reports

Each report produces:

- HTML report
- Excel workbook containing all activity records

Reports are saved to the **Downloads** folder on the user's local computer.

---

# Activity Cache

Activity data is cached to reduce repeated Bluebeam API requests and improve report generation time.

## Cache Design

Each Studio Session is cached in its own JSON file:

```text
Shared Application Folder/
│
├── redline_radar.exe
└── cache/
    ├── 117-770-339.json
    ├── 583-318-681.json
    └── 854-338-514.json
```

Each cache file contains:

- Cached activities
- Latest activity ID
- Activity count

---

# Shared Cache

The cache is designed to be shared between multiple users. 
If another user is updating the same session cache, the application waits until the update is complete before reading or writing the cache. Users accessing different sessions can continue working simultaneously without blocking one another.

Each session has its own lock file:

```text
854-338-514.json.lock
```

---

# Cache Outputs

When generating a report, the application will display one of the following messages:

- **Loaded _N_ activities from cache** – The cache contains all activity data for the session, and loads activities from cache to output reports.

- **Cache updated: _N_ new activities stored (_T_ activities)** – The cache existed but was missing recent activity, so only the new activities were fetched from Bluebeam and added to the cache.

- **Cache created: _N_ activities stored** – No cache existed for the session. All activities were downloaded from Bluebeam and saved  to cache for future use.

- **Cache unavailable** – The shared cache could not be accessed or updated. The application automatically retrieves all activity data directly from Bluebeam and continues generating the report.

---

# Authentication

Authentication uses OAuth.

On the first run, the application opens a browser window to authenticate with Bluebeam. After successful authentication, a refresh token is stored locally and subsequent launches typically do not require signing in again.

### Token Storage

The token file is stored at:

```text
C:\Users\<username>\.redline_radar\tokens.json
```

If authentication issues occur, deleting this file will force the application to prompt for a new Bluebeam login the next time it is run.

### Debug Logging

To diagnose authentication issues, use the `--debug` flag to enable detailed logging:

```text
./redline_radar.exe --debug
```

Debug logs are saved to:

```text
C:\Users\<username>\.redline_radar\logs\
```

Logs include information about:
- Token loading and expiration
- OAuth flow steps (browser launch, callback, token exchange)
- Token refresh attempts
- Re-authentication procedures

---

# Troubleshooting

## No activities found

Verify the Studio Session contains activity and that your account has permission to view it.

## Authentication failed

Delete the saved token file and authenticate again.

To debug authentication issues, run with the `--debug` flag:

```text
./redline_radar.exe --debug
```

This will create a detailed log file at `C:\Users\<username>\.redline_radar\logs\` showing the complete OAuth flow, token refresh attempts, and any errors that occur during authentication.

## Cache issues

Deleting a session's cache file causes the application to download the complete activity history from Bluebeam the next time a report is generated for that session.

---

# Notes

- Report generation is read-only. The application never modifies Studio Sessions, documents, or markups.
- Activity caching significantly reduces report generation time for previously processed sessions.
- Only new activities are downloaded after the initial cache is created.
- The shared cache supports multiple concurrent users.
