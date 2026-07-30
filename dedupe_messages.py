# Webhook dedup: Blooio retries deliveries, so an identical (number, message)
# arriving again within this window is treated as a duplicate and dropped.
# SQLite-backed: the DB is just a file, so every worker process on this
# machine shares it, with atomicity from SQLite's own cross-process locking —
# no server to run, no network calls. (Multiple MACHINES/instances would
# still need a shared store like Redis.)

import asyncio
import sqlite3
import time
from pathlib import Path

DEDUP_TTL_SECONDS = 120
DEDUP_DB_PATH = Path(__file__).parent / "dedup.sqlite3"


def _is_duplicate_sync(number: str, message: str) -> bool:
    # Wall clock, not monotonic: timestamps are shared across processes, and
    # monotonic clocks aren't comparable between them.
    now = time.time()
    with sqlite3.connect(DEDUP_DB_PATH, timeout=5) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS dedup ("
            " number TEXT NOT NULL,"
            " message TEXT NOT NULL,"
            " seen_at REAL NOT NULL,"
            " PRIMARY KEY (number, message))"
        )
        # Prune on every request (keeps the table tiny), then try to claim
        # the key. All in one transaction; SQLite serializes writers
        # across processes, so INSERT OR IGNORE is our atomic "NX".
        conn.execute(
            "DELETE FROM dedup WHERE seen_at < ?",
            (now - DEDUP_TTL_SECONDS,),
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO dedup (number, message, seen_at) VALUES (?, ?, ?)",
            (number, message, now),
        )
        if cur.rowcount == 1:
            return False  # row inserted -> first sighting

        # Key already there -> duplicate. Sliding window: restart its clock,
        # so the key stays blocked until DEDUP_TTL_SECONDS of silence.
        conn.execute(
            "UPDATE dedup SET seen_at = ? WHERE number = ? AND message = ?",
            (now, number, message),
        )
        return True


async def is_duplicate(number: str, message: str) -> bool:
    """True if this exact (number, message) was seen within the TTL.
    Sliding window: every duplicate restarts the clock, so the key stays
    blocked until a full TTL passes with no repeats.
    Runs in the threadpool so SQLite's file I/O never blocks the event
    loop. Fails open if the DB is somehow unusable."""
    try:
        return await asyncio.to_thread(_is_duplicate_sync, number, message)
    except sqlite3.Error as e:
        print(f"sqlite dedup unavailable, failing open: {e}")
        return False
