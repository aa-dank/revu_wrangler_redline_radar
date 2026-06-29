# Revu Wrangler Redline Radar

## Overview

Revu Wrangler Redline Radar generates attendance and markup activity reports for Bluebeam Studio Sessions.

The application retrieves session information from the Bluebeam API, caches activity data locally, and generates HTML and Excel reports.

---

# Requirements

- Bluebeam Studio account
- Network access to the shared cache location (if applicable)
- Valid API credentials
- Internet connection

---

# Running the Application

## Executable

Double-click `redline-radar.exe`

or run from a command prompt:

```text
redline-radar.exe
```

## Command Line

To automatically generate a report for a known session:

```text
redline-radar.exe <session_id>
```

Example:

```text
redline-radar.exe 854-338-514
```

If no session ID is supplied, the application will prompt for one.

---

# Entering a Session

A session can be entered as:

- Session ID
- Studio Session URL
- Invitation text containing the Session ID

Examples:

```text
854-338-514
```

or

```text
https://studio.bluebeam.com/.../854-338-514
```

---

# Generated Reports

Each report produces:

- HTML report
- Excel workbook containing all activity records

Reports are saved to the configured output directory.

---

# Activity Cache

Activity data is cached to reduce repeated API requests.

## Cache Design

Each Studio Session is stored as an individual JSON file:

```text
cache/
    117-770-339.json
    583-318-681.json
    854-338-514.json
```

Each cache file contains:

- Cached activities
- Latest activity ID
- Activity count
- Last synchronized timestamp

Only new activities are downloaded when an existing cache is present.

---

# Shared Cache

The cache is designed to be shared between multiple users.

Each session has its own lock file:

```text
854-338-514.json.lock
```

File locking ensures only one process updates a session cache at a time while allowing different sessions to be processed simultaneously.

---

# Updating Cached Data

When generating a report:

1. Check whether a cache exists.
2. Compare cached activity count with the Bluebeam API.
3. If the cache is current, load activities from cache.
4. Otherwise, download only new activities.
5. Update the cache.

---

# Authentication

Authentication uses OAuth.

The application stores refresh tokens locally to avoid repeated browser logins.

---

# Troubleshooting

## No activities found

Verify the Studio Session contains activity and that your account has permission to view it.

## Authentication failed

Delete the saved token file and authenticate again.

## Cache issues

Deleting the appropriate session JSON file forces the application to retrieve all activities again.

---

# Notes

- Activity caching significantly reduces report generation time for previously processed sessions.
- Only new activities are downloaded after the initial cache is created.
- The shared cache supports multiple concurrent users.