from pathlib import Path
from datetime import datetime, UTC
from filelock import FileLock
from contextlib import contextmanager
import json, sys, os
import time

class CacheJSON:
    CACHE_VERSION = 1
    def __init__(self):
        app_dir = get_cache_directory()
        self.cache_dir = app_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------
    def _cache_path(self, session_id: str) -> Path:
        return self.cache_dir / f"{session_id}.json"

    def _lock(self, session_id: str):
        return FileLock(str(self._cache_path(session_id)) + ".lock")
    
    @contextmanager
    def _session_lock(self, session_id: str):
        start = time.perf_counter()
        lock = self._lock(session_id)
        lock.acquire()
        
        try:
            waited = time.perf_counter() - start
            if waited > 1.0:
                print(f"⏳ Waiting for shared cache... ({waited:.2f}s)")
            yield
        finally:
            lock.release()

    def _load(self, session_id: str):
        cache_path = self._cache_path(session_id)

        if not cache_path.exists():
            return {
                "activity_count": 0,
                "latest_activity_id": 0,
                "activities": {}
            }
        
        with cache_path.open("r", encoding="utf-8") as f:
            return json.load(f)


    def _save(self, session_id: str, cache: dict):
        cache_path = self._cache_path(session_id)
        temp = cache_path.with_suffix(".tmp")

        with temp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)

        os.replace(temp, cache_path)

# ---------------------------------------------------------------------------
# Get Cache
# ---------------------------------------------------------------------------
    def get_activities(self, session_id: str):
        with self._session_lock(session_id):
            cache = self._load(session_id)

        return sorted(
            cache["activities"].values(),
            key=lambda a: int(a["Id"])
        )
    
    def get_session(self, session_id: str) -> dict:
        with self._session_lock(session_id):
            cache = self._load(session_id)
        
        return {
            "activity_count": cache["activity_count"],
            "latest_activity_id": cache["latest_activity_id"]
        }

# ---------------------------------------------------------------------------
# Save to Cache
# ---------------------------------------------------------------------------
    def save_activities(self, session_id: str, activities: list[dict]):
        with self._session_lock(session_id):
            cache = self._load(session_id)
            
            stored = cache.setdefault("activities", {})

            for activity in activities:
                stored[str(activity["Id"])] = activity

            cache["activity_count"] = len(stored)
            cache["latest_activity_id"] = max(
                (int(activity_id) for activity_id in stored.keys()),
                default=0,
            )

            self._save(session_id, cache)

# ---------------------------------------------------------------------------
# Validation 
# ---------------------------------------------------------------------------
    def validate(self, session_id: str, expected_count: int) -> tuple[bool, int]:
        with self._session_lock(session_id):
            cache = self._load(session_id)
            cached_count = cache["activity_count"]

        return cached_count == expected_count, cached_count 
    
def get_cache_directory() -> Path:
    if getattr(sys, "frozen", False):
        # Running as a bundled executable
        return Path(sys.executable).resolve().parent

    # Running from source
    return Path(__file__).resolve().parent
