"""SQLite incident store.

Design notes
------------
* A NEW ``sqlite3`` connection is opened for every call. Camera workers, the
  clip-writer threads and Flask request threads all use one shared
  ``DatabaseManager``; sqlite connections must not cross threads, and a
  connection per call is cheap next to a video frame.
* WAL journal + ``BEGIN IMMEDIATE`` for writes: readers never block the
  writer, and concurrent writers queue on the busy timeout instead of failing
  with ``database is locked`` halfway through a deferred transaction.
* Timestamps are generated in Python as UTC ISO-8601 with a ``Z`` suffix
  (``2026-09-22T14:03:11Z``). That format sorts lexicographically, so range
  filters and ordering are plain string comparisons on an indexed column.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("chanakya.database_manager")

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CRITICAL_SCORE = 70  # same boundary as ThreatAssessor's CRITICAL category
_WARNING_SCORE = 30
_MAX_STATS_HOURS = 24 * 366
_BUSY_TIMEOUT_S = 10.0

# Column name -> DDL. The same DDL serves CREATE TABLE and the legacy
# ``ALTER TABLE ADD COLUMN`` path, so every definition must be legal for ALTER
# (i.e. NOT NULL only together with a constant default). ``category`` is
# nullable on purpose: NULL marks "legacy row, not backfilled yet".
_COLUMNS: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "timestamp": "TEXT",
    "camera": "TEXT",
    "object_type": "TEXT",
    "identity": "TEXT",
    "track_id": "INTEGER",
    "threat_score": "INTEGER",
    "category": "TEXT",
    "zone_level": "TEXT",
    "emotion": "TEXT",
    "reasons": "TEXT",
    "image_path": "TEXT",
    "clip_path": "TEXT",
    "acknowledged": "INTEGER NOT NULL DEFAULT 0",
}
# Column names are module constants, never user input.
_SELECT = "SELECT " + ", ".join(_COLUMNS) + " FROM incidents"  # nosec B608

_LEGACY_TIMESTAMP_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]"
# v1 logged object_type as "[ALPHA] Name (ID:3, Emotion:Happy 80%)".
_LEGACY_CAMERA_RE = re.compile(r"\[([A-Za-z0-9_-]{1,32})\]")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso_z(value: datetime | str) -> str:
    """Normalise a datetime or ISO-8601 string to the stored ``...Z`` form.

    Naive values are taken as UTC. Raises ``ValueError`` on anything that is
    not a timestamp, which lets the API layer answer 400 for a bad ``since``.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("timestamp must be ISO-8601") from None
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be ISO-8601")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime(ISO_FORMAT)


def category_for_score(score: int) -> str:
    """Threat category for a score: <30 LOW, <70 WARNING, else CRITICAL."""
    if score < _WARNING_SCORE:
        return "LOW"
    if score < CRITICAL_SCORE:
        return "WARNING"
    return "CRITICAL"


def _decode_reasons(raw: str | None) -> list[str]:
    """``reasons`` is JSON text; anything unreadable degrades to ``[]``."""
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _row_to_incident(row: sqlite3.Row) -> dict:
    """DB row -> incident dict with the exact contract keys and types."""
    score = int(row["threat_score"] or 0)
    return {
        "id": int(row["id"]),
        "timestamp": str(row["timestamp"] or ""),
        "camera": row["camera"],
        "object_type": str(row["object_type"] or ""),
        "identity": row["identity"],
        "track_id": None if row["track_id"] is None else int(row["track_id"]),
        "threat_score": score,
        "category": row["category"] or category_for_score(score),
        "zone_level": row["zone_level"] or "SAFE",
        "emotion": row["emotion"],
        "reasons": _decode_reasons(row["reasons"]),
        "image_path": row["image_path"],
        "clip_path": row["clip_path"],
        "acknowledged": bool(row["acknowledged"]),
    }


class DatabaseManager:
    """Thread-safe incident log backed by one SQLite file."""

    def __init__(self, db_path=None, *, clock: Callable[[], datetime] | None = None):
        """Open (creating or migrating as needed) the database at ``db_path``.

        ``db_path`` None resolves to ``settings.DB_PATH``. ``clock`` returns the
        current time as a datetime (naive = UTC); it exists so retention and
        statistics can be tested without sleeping.
        """
        if db_path is None:
            from config import settings

            db_path = settings.DB_PATH
        self.db_path = Path(db_path)
        self._clock = clock or _utc_now
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    # ------------------------------------------------------------------ #
    # connections
    # ------------------------------------------------------------------ #
    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        """One connection, one transaction, always closed.

        ``sqlite3``'s own ``with conn:`` commits but never closes, which leaks a
        file handle per call; hence this wrapper. Autocommit mode
        (``isolation_level=None``) keeps transaction control explicit.
        """
        conn = sqlite3.connect(self.db_path, timeout=_BUSY_TIMEOUT_S, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield conn
            except BaseException:
                # sqlite may already have rolled back (e.g. on SQLITE_FULL); a
                # second ROLLBACK would raise and mask the original error.
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def _now_iso(self) -> str:
        return to_iso_z(self._clock())

    # ------------------------------------------------------------------ #
    # schema + migration
    # ------------------------------------------------------------------ #
    def _initialise(self) -> None:
        """Create the schema or migrate a v1 database; safe to run repeatedly."""
        conn = sqlite3.connect(self.db_path, timeout=_BUSY_TIMEOUT_S, isolation_level=None)
        try:
            # WAL is a persistent property of the file and cannot be changed
            # inside a transaction, so it is set before the migration begins.
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()
        with self._transaction(write=True) as conn:
            columns_sql = ", ".join(f"{name} {ddl}" for name, ddl in _COLUMNS.items())
            conn.execute(f"CREATE TABLE IF NOT EXISTS incidents ({columns_sql})")
            added = self._add_missing_columns(conn)
            migrated = self._migrate_legacy_rows(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents(timestamp)")
        if added or migrated:
            logger.info(
                "Migrated legacy incident table: %d column(s) added, %d row update(s)",
                len(added),
                migrated,
            )

    @staticmethod
    def _add_missing_columns(conn: sqlite3.Connection) -> list[str]:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)")}
        missing = [name for name in _COLUMNS if name not in existing]
        for name in missing:
            conn.execute(f"ALTER TABLE incidents ADD COLUMN {name} {_COLUMNS[name]}")
        return missing

    @staticmethod
    def _migrate_legacy_rows(conn: sqlite3.Connection) -> int:
        """Bring v1 rows up to the v2 conventions; returns the number of row updates.

        Every statement is guarded by a WHERE clause that only matches rows
        still in legacy form, which is what makes the migration idempotent.
        """
        changed = 0
        # v1 relied on CURRENT_TIMESTAMP, which is UTC "YYYY-MM-DD HH:MM:SS".
        changed += conn.execute(
            "UPDATE incidents SET timestamp = substr(timestamp, 1, 10) || 'T' || "
            "substr(timestamp, 12, 8) || 'Z' WHERE timestamp GLOB ?",
            (_LEGACY_TIMESTAMP_GLOB,),
        ).rowcount
        # v1 stored the *string* "None" when there was no snapshot.
        changed += conn.execute("UPDATE incidents SET image_path = NULL WHERE image_path IN ('None', '')").rowcount
        changed += conn.execute(
            "UPDATE incidents SET category = CASE "
            "WHEN COALESCE(threat_score, 0) < ? THEN 'LOW' "
            "WHEN COALESCE(threat_score, 0) < ? THEN 'WARNING' "
            "ELSE 'CRITICAL' END WHERE category IS NULL",
            (_WARNING_SCORE, CRITICAL_SCORE),
        ).rowcount
        legacy_named = conn.execute(
            "SELECT id, object_type FROM incidents WHERE camera IS NULL AND object_type LIKE '[%]%'"
        ).fetchall()
        camera_updates = []
        for row in legacy_named:
            match = _LEGACY_CAMERA_RE.match(row["object_type"])
            if match:
                camera_updates.append((match.group(1).lower(), row["id"]))
        conn.executemany("UPDATE incidents SET camera = ? WHERE id = ?", camera_updates)
        return changed + len(camera_updates)

    # ------------------------------------------------------------------ #
    # writes
    # ------------------------------------------------------------------ #
    def log_incident(
        self,
        *,
        camera,
        object_type,
        threat_score,
        zone_level="SAFE",
        category="WARNING",
        track_id=None,
        identity=None,
        emotion=None,
        reasons=None,
        image_path=None,
        clip_path=None,
    ) -> int:
        """Insert one incident stamped with the current UTC time; returns its id."""
        values = (
            self._now_iso(),
            camera,
            str(object_type),
            identity,
            None if track_id is None else int(track_id),
            int(threat_score),
            str(category),
            str(zone_level),
            emotion,
            json.dumps([str(reason) for reason in (reasons or [])]),
            None if image_path is None else str(image_path),
            None if clip_path is None else str(clip_path),
        )
        with self._transaction(write=True) as conn:
            cursor = conn.execute(
                "INSERT INTO incidents (timestamp, camera, object_type, identity, track_id, "
                "threat_score, category, zone_level, emotion, reasons, image_path, clip_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            return int(cursor.lastrowid)

    def set_clip_path(self, incident_id, clip_path) -> None:
        """Attach the finished clip to an incident (unknown ids are ignored)."""
        with self._transaction(write=True) as conn:
            conn.execute(
                "UPDATE incidents SET clip_path = ? WHERE id = ?",
                (None if clip_path is None else str(clip_path), incident_id),
            )

    def acknowledge(self, incident_id, acknowledged=True) -> bool:
        """Set the acknowledged flag; False when ``incident_id`` does not exist."""
        with self._transaction(write=True) as conn:
            cursor = conn.execute(
                "UPDATE incidents SET acknowledged = ? WHERE id = ?",
                (1 if acknowledged else 0, incident_id),
            )
            return cursor.rowcount > 0

    def purge_older_than(self, days) -> list[dict]:
        """Delete incidents older than ``days`` days and return the deleted dicts.

        The caller needs the dicts to unlink the snapshot/clip files. Select
        and delete share one write transaction so the returned list is exactly
        what was removed. ``days <= 0`` disables retention and deletes nothing.
        """
        if not days or days <= 0:
            return []
        cutoff = to_iso_z(_as_utc(self._clock()) - timedelta(days=days))
        with self._transaction(write=True) as conn:
            rows = conn.execute(f"{_SELECT} WHERE timestamp < ? ORDER BY id", (cutoff,)).fetchall()
            conn.execute("DELETE FROM incidents WHERE timestamp < ?", (cutoff,))
        return [_row_to_incident(row) for row in rows]

    # ------------------------------------------------------------------ #
    # reads
    # ------------------------------------------------------------------ #
    def get_incident(self, incident_id) -> dict | None:
        with self._transaction(write=False) as conn:
            row = conn.execute(f"{_SELECT} WHERE id = ?", (incident_id,)).fetchone()
        return None if row is None else _row_to_incident(row)

    def list_incidents(
        self,
        *,
        limit=50,
        offset=0,
        min_threat=None,
        zone=None,
        camera=None,
        since=None,
        acknowledged=None,
    ) -> tuple[list[dict], int]:
        """Newest-first page of incidents plus the total number matching the filters.

        ``since`` is a datetime or ISO-8601 string (inclusive lower bound);
        a malformed value raises ``ValueError``.
        """
        clauses: list[str] = []
        params: list = []
        if min_threat is not None:
            clauses.append("threat_score >= ?")
            params.append(int(min_threat))
        if zone is not None:
            clauses.append("zone_level = ?")
            params.append(zone)
        if camera is not None:
            clauses.append("camera = ?")
            params.append(camera)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(to_iso_z(since))
        if acknowledged is not None:
            clauses.append("acknowledged = ?")
            params.append(1 if acknowledged else 0)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        page = (max(0, int(limit)), max(0, int(offset)))
        # One read transaction so the page and the total describe the same snapshot.
        with self._transaction(write=False) as conn:
            # `where` joins fixed clause literals; every value travels in `params`.
            total = conn.execute(f"SELECT COUNT(*) FROM incidents{where}", params).fetchone()[0]  # nosec B608
            rows = conn.execute(
                f"{_SELECT}{where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",  # nosec B608
                (*params, *page),
            ).fetchall()
        return [_row_to_incident(row) for row in rows], int(total)

    def get_recent_logs(self, limit=10) -> list[tuple]:
        """Legacy shape: ``(timestamp, object_type, threat_score, zone_level)`` tuples."""
        with self._transaction(write=False) as conn:
            rows = conn.execute(
                "SELECT timestamp, object_type, threat_score, zone_level FROM incidents "
                "ORDER BY timestamp DESC, id DESC LIMIT ?",
                (max(0, int(limit)),),
            ).fetchall()
        return [tuple(row) for row in rows]

    def stats(self, hours=24) -> dict:
        """Aggregate counts over the last ``hours`` hour buckets.

        The window is aligned to whole UTC hours: it ends with the current
        (partial) hour and contains exactly ``hours`` buckets, so
        ``sum(by_hour counts) == total`` and a chart of ``by_hour`` always
        accounts for every incident in the headline number.
        """
        hours = int(hours)
        if not 1 <= hours <= _MAX_STATS_HOURS:
            raise ValueError(f"hours must be between 1 and {_MAX_STATS_HOURS}")
        current_hour = _as_utc(self._clock()).replace(minute=0, second=0, microsecond=0)
        buckets = [current_hour - timedelta(hours=age) for age in range(hours - 1, -1, -1)]
        since = to_iso_z(buckets[0])
        with self._transaction(write=False) as conn:
            total, critical, unacknowledged = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(threat_score >= ?), 0), "
                "COALESCE(SUM(acknowledged = 0), 0) FROM incidents WHERE timestamp >= ?",
                (CRITICAL_SCORE, since),
            ).fetchone()
            per_hour = dict(
                conn.execute(
                    "SELECT substr(timestamp, 1, 13), COUNT(*) FROM incidents WHERE timestamp >= ? GROUP BY 1",
                    (since,),
                ).fetchall()
            )
            by_zone = conn.execute(
                "SELECT COALESCE(zone_level, 'SAFE'), COUNT(*) FROM incidents WHERE timestamp >= ? GROUP BY 1",
                (since,),
            ).fetchall()
            by_camera = conn.execute(
                "SELECT COALESCE(camera, 'unknown'), COUNT(*) FROM incidents WHERE timestamp >= ? GROUP BY 1",
                (since,),
            ).fetchall()
        return {
            "hours": hours,
            "total": int(total),
            "critical": int(critical),
            "unacknowledged": int(unacknowledged),
            "by_hour": [
                {
                    "hour": to_iso_z(bucket),
                    "count": int(per_hour.get(bucket.strftime("%Y-%m-%dT%H"), 0)),
                }
                for bucket in buckets
            ],
            "by_zone": {zone: int(count) for zone, count in by_zone},
            "by_camera": {camera: int(count) for camera, count in by_camera},
        }


def _as_utc(moment: datetime) -> datetime:
    """Clock values may be naive (taken as UTC) or aware; normalise to aware UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
