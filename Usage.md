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

# Running the Application

## Executable

Double-click `redline-radar.exe`

or run from a command prompt:

```text
./redline-radar.exe
```

## Command Line

To automatically generate a report for a known session:

```text
./redline-radar.exe <session_id>
```

Example:

```text
./redline-radar.exe 117-770-339
```

---

# Generated Reports

Each report produces:

- HTML report
- Excel workbook containing all activity records

Reports are saved to the **Downloads** folder on the user's local computer.

---

# Activity Cache

Activity data is cached to reduce repeated API requests and improve program speed. 

## Cache Design

Each Studio Session is stored as an individual JSON file:

```text
redline_radar.exe
cache/
    117-770-339.json
    583-318-681.json
    854-338-514.json
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

---

# Authentication

Authentication uses OAuth.

The application stores refresh tokens locally to avoid repeated browser logins.

The token file is stored at:

```text
C:\Users\<username>\.redline_radar\tokens.json
```

If authentication issues occur, deleting this file will force the application to prompt for a new Bluebeam login the next time it is run.

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
