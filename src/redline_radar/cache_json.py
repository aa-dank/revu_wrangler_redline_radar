from pathlib import Path
from datetime import datetime, UTC
from filelock import FileLock
import json, sys, os
import time

class CacheJSON:
    CACHE_VERSION = 1
    def __init__(self):
        app_dir = get_cache_directory()
        self.cache_path = app_dir / "cache.json"
        self.lock = FileLock(str(self.cache_path) + ".lock")

        if not self.cache_path.exists():
            self._save({
                "version": self.CACHE_VERSION,
                "sessions": {}
            })
# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------
    def _load(self):
        start = time.perf_counter()

        with self.lock:
            waited = time.perf_counter() - start

            # Only report if we actually had to wait for another process
            if waited > 0.1:
                print(f"⏳ Waiting for shared cache... ({waited:.2f}s)")

            with self.cache_path.open("r", encoding="utf-8") as f:
                return json.load(f)


    def _save(self, cache):
        temp_path = self.cache_path.with_suffix(".tmp")

        start = time.perf_counter()

        with self.lock:
            waited = time.perf_counter() - start

            # Only report if another process was already writing
            if waited > 0.1:
                print(f"⏳ Waiting for shared cache... ({waited:.2f}s)")

            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)

            os.replace(temp_path, self.cache_path)

    def _modify_cache(self, callback):
        with self.lock:
            cache = self.load_unlocked()
            callback(cache)
            self.save_unlocked(cache)

# ---------------------------------------------------------------------------
# Get Cache
# ---------------------------------------------------------------------------
    def get_session(self, session_id: str) -> dict | None:
        cache = self._load()
        return cache["sessions"].get(session_id)
    
    def get_activities(self, session_id: str):
        session = self.get_session(session_id)
        if session is None: return []

        return sorted(
            session.get("activities", {}).values(),
            key=lambda activity: int(activity["Id"])
        )

# ---------------------------------------------------------------------------
# Save to Cache
# ---------------------------------------------------------------------------
    def save_activities(self, session_id: str, activities: list[dict]):
        if not activities:return

        cache = self._load()
        session = cache["sessions"].setdefault(
            session_id,
            {"activities": {}}
        )

        # Save activities
        stored = session.setdefault("activities", {})
        for activity in activities:
            stored[str(activity["Id"])] = activity

        # Update metadata
        session["activity_count"] = len(stored)
        session["latest_activity_id"] = max(
            int(activity_id) for activity_id in stored
        )
        session["last_synced"] = datetime.now(UTC).isoformat()

        self._save(cache)

# ---------------------------------------------------------------------------
# Validation 
# ---------------------------------------------------------------------------
    def validate(self, session_id: str, expected_count: int) -> tuple[bool, int]:
        cached_count = len(self.get_activities(session_id))
        return cached_count == expected_count, cached_count 
    
def get_cache_directory() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a bundled executable
        return Path(sys.executable).resolve().parent

    # Running from source
    return Path(__file__).resolve().parent
