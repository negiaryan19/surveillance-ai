"""src.database_manager: CRUD, filters, pagination, stats, migration, retention, threads."""

from __future__ import annotations

import re
import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.database_manager import DatabaseManager, category_for_score, to_iso_z

INCIDENT_KEYS = [
    "id",
    "timestamp",
    "camera",
    "object_type",
    "identity",
    "track_id",
    "threat_score",
    "category",
    "zone_level",
    "emotion",
    "reasons",
    "image_path",
    "clip_path",
    "acknowledged",
]
ISO_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
T0 = datetime(2026, 9, 22, 14, 30, 0, tzinfo=UTC)  # conftest clock start


def log(db, **overrides) -> int:
    fields = {"camera": "alpha", "object_type": "Person", "threat_score": 80}
    fields.update(overrides)
    return db.log_incident(**fields)


def raw_execute(db, sql, params=()):
    conn = sqlite3.connect(db.db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# construction
# --------------------------------------------------------------------------- #
class TestConstruction:
    def test_creates_parent_directory_and_uses_wal(self, tmp_path):
        path = tmp_path / "deep" / "er" / "chanakya.db"
        DatabaseManager(path)
        assert path.is_file()
        conn = sqlite3.connect(path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            indexes = [row[1] for row in conn.execute("PRAGMA index_list(incidents)")]
        finally:
            conn.close()
        assert "idx_incidents_timestamp" in indexes

    def test_default_path_comes_from_settings(self, tmp_path, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "DB_PATH", tmp_path / "from_settings" / "c.db")
        manager = DatabaseManager()
        assert manager.db_path == tmp_path / "from_settings" / "c.db"
        assert manager.db_path.is_file()

    def test_reopening_keeps_the_data(self, db):
        incident_id = log(db)
        assert DatabaseManager(db.db_path).get_incident(incident_id)["id"] == incident_id

    def test_log_incident_is_keyword_only(self, db):
        with pytest.raises(TypeError):
            db.log_incident("alpha", "Person", 80)


# --------------------------------------------------------------------------- #
# CRUD + dict shape
# --------------------------------------------------------------------------- #
class TestCrud:
    def test_minimal_incident_has_exact_keys_and_defaults(self, db):
        incident_id = log(db)
        incident = db.get_incident(incident_id)
        assert list(incident) == INCIDENT_KEYS
        assert incident == {
            "id": incident_id,
            "timestamp": "2026-09-22T14:30:00Z",
            "camera": "alpha",
            "object_type": "Person",
            "identity": None,
            "track_id": None,
            "threat_score": 80,
            "category": "WARNING",
            "zone_level": "SAFE",
            "emotion": None,
            "reasons": [],
            "image_path": None,
            "clip_path": None,
            "acknowledged": False,
        }
        assert isinstance(incident["acknowledged"], bool)

    def test_full_incident_round_trips(self, db, tmp_path):
        snapshot = tmp_path / "snap.jpg"
        incident_id = db.log_incident(
            camera="gate",
            object_type="Person",
            threat_score=95,
            zone_level="CRITICAL",
            category="CRITICAL",
            track_id=7,
            identity="Aryan Negi",
            emotion="Angry",
            reasons=["Breached Critical Zone", "Unknown Identity"],
            image_path=snapshot,
            clip_path=str(tmp_path / "clip.mp4"),
        )
        incident = db.get_incident(incident_id)
        assert incident["track_id"] == 7 and isinstance(incident["track_id"], int)
        assert incident["identity"] == "Aryan Negi"
        assert incident["emotion"] == "Angry"
        assert incident["reasons"] == ["Breached Critical Zone", "Unknown Identity"]
        assert incident["image_path"] == str(snapshot)  # Path stored as str
        assert incident["clip_path"] == str(tmp_path / "clip.mp4")
        assert incident["category"] == "CRITICAL" and incident["zone_level"] == "CRITICAL"

    def test_ids_increase_and_timestamp_is_utc_iso_z_from_the_clock(self, db, clock):
        first = log(db)
        clock.set(T0 + timedelta(seconds=75))
        second = log(db)
        assert second > first
        assert db.get_incident(second)["timestamp"] == "2026-09-22T14:31:15Z"

    def test_real_clock_produces_iso_z(self, tmp_path):
        manager = DatabaseManager(tmp_path / "real.db")
        stamp = manager.get_incident(log(manager))["timestamp"]
        assert ISO_Z.fullmatch(stamp)
        written = datetime.fromisoformat(stamp)
        assert abs((datetime.now(UTC) - written).total_seconds()) < 60

    def test_non_utc_and_naive_clocks_are_normalised(self, tmp_path):
        ist = timezone(timedelta(hours=5, minutes=30))
        aware = DatabaseManager(tmp_path / "a.db", clock=lambda: datetime(2026, 9, 22, 20, 0, tzinfo=ist))
        assert aware.get_incident(log(aware))["timestamp"] == "2026-09-22T14:30:00Z"
        naive = DatabaseManager(tmp_path / "n.db", clock=lambda: datetime(2026, 9, 22, 14, 30))
        assert naive.get_incident(log(naive))["timestamp"] == "2026-09-22T14:30:00Z"

    def test_get_unknown_incident(self, db):
        assert db.get_incident(999) is None

    def test_set_clip_path(self, db, tmp_path):
        incident_id = log(db)
        assert db.set_clip_path(incident_id, tmp_path / "clip.mp4") is None
        assert db.get_incident(incident_id)["clip_path"] == str(tmp_path / "clip.mp4")
        db.set_clip_path(999, "/nowhere.mp4")  # unknown id: silently ignored

    def test_acknowledge(self, db):
        incident_id = log(db)
        assert db.acknowledge(incident_id) is True
        assert db.get_incident(incident_id)["acknowledged"] is True
        assert db.acknowledge(incident_id, False) is True
        assert db.get_incident(incident_id)["acknowledged"] is False
        assert db.acknowledge(999) is False

    def test_sql_metacharacters_are_data(self, db):
        nasty = "Robert'); DROP TABLE incidents;--"
        incident_id = log(db, object_type=nasty, identity=nasty, reasons=[nasty])
        incident = db.get_incident(incident_id)
        assert incident["object_type"] == nasty and incident["reasons"] == [nasty]
        assert db.list_incidents(camera=nasty) == ([], 0)


class TestReasonsAlwaysAList:
    @pytest.mark.parametrize("given", [None, [], ()])
    def test_empty_inputs(self, db, given):
        assert db.get_incident(log(db, reasons=given))["reasons"] == []

    def test_non_string_items_are_stringified(self, db):
        assert db.get_incident(log(db, reasons=["a", 5]))["reasons"] == ["a", "5"]

    @pytest.mark.parametrize("stored", [None, "", "not json", '{"a": 1}', '"text"', "12", "null"])
    def test_null_or_invalid_json_in_the_column(self, db, stored):
        incident_id = log(db, reasons=["real"])
        raw_execute(db, "UPDATE incidents SET reasons = ? WHERE id = ?", (stored, incident_id))
        assert db.get_incident(incident_id)["reasons"] == []
        items, _ = db.list_incidents()
        assert items[0]["reasons"] == []


# --------------------------------------------------------------------------- #
# listing
# --------------------------------------------------------------------------- #
@pytest.fixture
def populated(db, clock):
    """Six incidents, one minute apart, oldest first; returns their ids."""
    rows = [
        dict(camera="alpha", threat_score=20, zone_level="SAFE", category="LOW"),
        dict(camera="alpha", threat_score=50, zone_level="WARNING", category="WARNING"),
        dict(camera="bravo", threat_score=70, zone_level="CRITICAL", category="CRITICAL"),
        dict(camera="bravo", threat_score=90, zone_level="CRITICAL", category="CRITICAL"),
        dict(camera=None, threat_score=100, zone_level="WARNING", category="CRITICAL"),
        dict(camera="alpha", threat_score=75, zone_level="PERIMETER", category="CRITICAL"),
    ]
    ids = []
    for minute, row in enumerate(rows):
        clock.set(T0 + timedelta(minutes=minute))
        ids.append(log(db, **row))
    return ids


class TestListIncidents:
    def test_empty_database(self, db):
        assert db.list_incidents() == ([], 0)

    def test_newest_first(self, db, populated):
        items, total = db.list_incidents()
        assert total == 6
        assert [item["id"] for item in items] == list(reversed(populated))
        assert list(items[0]) == INCIDENT_KEYS

    def test_same_second_ties_break_by_id(self, db):
        ids = [log(db) for _ in range(3)]  # the fake clock does not advance
        items, _ = db.list_incidents()
        assert [item["id"] for item in items] == list(reversed(ids))

    def test_pagination_total_is_the_match_count_not_the_page_size(self, db, populated):
        newest_first = list(reversed(populated))
        page1, total1 = db.list_incidents(limit=4, offset=0)
        page2, total2 = db.list_incidents(limit=4, offset=4)
        page3, total3 = db.list_incidents(limit=4, offset=8)
        assert (total1, total2, total3) == (6, 6, 6)
        assert [i["id"] for i in page1] == newest_first[:4]
        assert [i["id"] for i in page2] == newest_first[4:]
        assert page3 == []

    def test_limit_zero_returns_only_the_total(self, db, populated):
        assert db.list_incidents(limit=0) == ([], 6)

    def test_negative_limit_and_offset_are_clamped(self, db, populated):
        assert db.list_incidents(limit=-1) == ([], 6)  # never SQLite's "no limit"
        items, _ = db.list_incidents(offset=-5)
        assert len(items) == 6

    def test_min_threat_is_inclusive(self, db, populated):
        items, total = db.list_incidents(min_threat=70)
        assert total == 4
        assert sorted(i["threat_score"] for i in items) == [70, 75, 90, 100]

    def test_zone_filter(self, db, populated):
        items, total = db.list_incidents(zone="CRITICAL")
        assert total == 2 and {i["zone_level"] for i in items} == {"CRITICAL"}

    def test_camera_filter(self, db, populated):
        items, total = db.list_incidents(camera="alpha")
        assert total == 3 and {i["camera"] for i in items} == {"alpha"}
        assert db.list_incidents(camera="nope") == ([], 0)

    def test_acknowledged_filter(self, db, populated):
        db.acknowledge(populated[0])
        db.acknowledge(populated[3])
        acked, acked_total = db.list_incidents(acknowledged=True)
        open_, open_total = db.list_incidents(acknowledged=False)
        assert acked_total == 2 and {i["id"] for i in acked} == {populated[0], populated[3]}
        assert open_total == 4 and all(i["acknowledged"] is False for i in open_)

    def test_since_is_inclusive_and_accepts_str_or_datetime(self, db, populated):
        cutoff = T0 + timedelta(minutes=3)
        for since in ("2026-09-22T14:33:00Z", "2026-09-22T20:03:00+05:30", cutoff, cutoff.replace(tzinfo=None)):
            items, total = db.list_incidents(since=since)
            assert total == 3, since
            assert [i["id"] for i in items] == list(reversed(populated[3:]))

    @pytest.mark.parametrize("bad", ["yesterday", "", "2026-13-45", 12345])
    def test_bad_since_raises_value_error(self, db, bad):
        with pytest.raises(ValueError):
            db.list_incidents(since=bad)

    def test_filters_combine_and_total_respects_them(self, db, populated):
        items, total = db.list_incidents(camera="bravo", min_threat=80, limit=1)
        assert total == 1 and items[0]["threat_score"] == 90
        items, total = db.list_incidents(camera="alpha", acknowledged=False, limit=1)
        assert total == 3 and len(items) == 1

    def test_get_recent_logs_legacy_tuples(self, db, populated):
        logs = db.get_recent_logs(limit=2)
        assert logs == [
            ("2026-09-22T14:35:00Z", "Person", 75, "PERIMETER"),
            ("2026-09-22T14:34:00Z", "Person", 100, "WARNING"),
        ]
        assert all(isinstance(entry, tuple) for entry in logs)
        assert len(db.get_recent_logs()) == 6


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
class TestStats:
    def test_empty_database_is_zero_filled(self, db):
        stats = db.stats()
        assert list(stats) == ["hours", "total", "critical", "unacknowledged", "by_hour", "by_zone", "by_camera"]
        assert (stats["hours"], stats["total"], stats["critical"], stats["unacknowledged"]) == (24, 0, 0, 0)
        assert stats["by_zone"] == {} and stats["by_camera"] == {}
        assert len(stats["by_hour"]) == 24
        assert all(bucket["count"] == 0 for bucket in stats["by_hour"])

    def test_by_hour_is_contiguous_oldest_first_and_ends_at_the_current_hour(self, db):
        hours = [bucket["hour"] for bucket in db.stats(hours=24)["by_hour"]]
        assert hours[0] == "2026-09-21T15:00:00Z"
        assert hours[-1] == "2026-09-22T14:00:00Z"
        parsed = [datetime.fromisoformat(hour) for hour in hours]
        assert all(b - a == timedelta(hours=1) for a, b in zip(parsed, parsed[1:]))
        assert all(ISO_Z.fullmatch(hour) for hour in hours)

    def test_counts(self, db, clock):
        clock.set(T0 - timedelta(hours=30))
        log(db, threat_score=99)  # outside the 24 h window
        clock.set(T0 - timedelta(hours=3, minutes=10))  # 11:20 -> 11:00 bucket
        log(db, threat_score=69, zone_level="WARNING")
        log(db, threat_score=70, zone_level="CRITICAL", camera="bravo")
        clock.set(T0 - timedelta(minutes=5))  # 14:25 -> 14:00 bucket
        acked = log(db, threat_score=100, zone_level="CRITICAL", camera=None)
        db.acknowledge(acked)
        clock.set(T0)

        stats = db.stats(hours=24)
        assert stats["total"] == 3
        assert stats["critical"] == 2  # 70 counts, 69 does not
        assert stats["unacknowledged"] == 2
        assert stats["by_zone"] == {"WARNING": 1, "CRITICAL": 2}
        assert stats["by_camera"] == {"alpha": 1, "bravo": 1, "unknown": 1}
        counts = {bucket["hour"]: bucket["count"] for bucket in stats["by_hour"]}
        assert counts["2026-09-22T11:00:00Z"] == 2
        assert counts["2026-09-22T14:00:00Z"] == 1
        assert sum(counts.values()) == stats["total"]

    def test_window_size_follows_hours(self, db, clock):
        clock.set(T0 - timedelta(hours=2))
        log(db)
        clock.set(T0)
        assert db.stats(hours=1)["total"] == 0 and len(db.stats(hours=1)["by_hour"]) == 1
        assert db.stats(hours=3)["total"] == 1 and len(db.stats(hours=3)["by_hour"]) == 3
        assert len(db.stats(hours=168)["by_hour"]) == 168

    @pytest.mark.parametrize("bad", [0, -1, 10**6])
    def test_bad_hours(self, db, bad):
        with pytest.raises(ValueError):
            db.stats(hours=bad)

    def test_stats_is_json_serialisable(self, db):
        import json

        log(db)
        json.dumps(db.stats())


# --------------------------------------------------------------------------- #
# retention
# --------------------------------------------------------------------------- #
class TestPurge:
    def test_purge_returns_exactly_the_deleted_dicts(self, db, clock, tmp_path):
        clock.set(T0 - timedelta(days=31))
        old = log(db, image_path=str(tmp_path / "old.jpg"), clip_path=str(tmp_path / "old.mp4"), reasons=["r"])
        clock.set(T0 - timedelta(days=29))
        recent = log(db)
        clock.set(T0)
        fresh = log(db)

        deleted = db.purge_older_than(30)
        assert [d["id"] for d in deleted] == [old]
        assert list(deleted[0]) == INCIDENT_KEYS
        assert deleted[0]["image_path"] == str(tmp_path / "old.jpg")
        assert deleted[0]["clip_path"] == str(tmp_path / "old.mp4")
        assert deleted[0]["reasons"] == ["r"]
        assert db.get_incident(old) is None
        assert {i["id"] for i in db.list_incidents()[0]} == {recent, fresh}
        assert db.purge_older_than(30) == []

    @pytest.mark.parametrize("days", [0, -1, None])
    def test_zero_or_less_disables_retention(self, db, clock, days):
        clock.set(T0 - timedelta(days=400))
        log(db)
        clock.set(T0)
        assert db.purge_older_than(days) == []
        assert db.list_incidents()[1] == 1

    def test_ids_are_not_reused_after_a_purge(self, db, clock):
        clock.set(T0 - timedelta(days=40))
        old = log(db)
        clock.set(T0)
        db.purge_older_than(30)
        assert log(db) > old  # AUTOINCREMENT: clip callbacks can never hit a recycled id


# --------------------------------------------------------------------------- #
# legacy migration
# --------------------------------------------------------------------------- #
LEGACY_ROWS = [
    ("2025-01-05 09:15:42", "[ALPHA] Aryan (ID:3, Emotion:Happy 80%)", 85, "CRITICAL", "/abs/snapshots/a.jpg"),
    ("2025-01-05 09:16:00", "[BRAVO] Unknown (ID:4)", 50, "WARNING", "None"),
    ("2025-01-05 09:17:00", "Person", 10, "SAFE", "None"),
    ("2025-01-05 09:18:00", "[not a camera!] thing", 70, "CRITICAL", ""),
    ("2025-01-05 09:19:00", "[Gate_2] Car (ID:9)", 29, "PERIMETER", None),
]


def make_legacy_db(path) -> None:
    """The exact v1 schema, with rows as v1 wrote them."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                object_type TEXT,
                threat_score INTEGER,
                zone_level TEXT,
                image_path TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO incidents (timestamp, object_type, threat_score, zone_level, image_path) "
            "VALUES (?, ?, ?, ?, ?)",
            LEGACY_ROWS,
        )
        conn.execute("INSERT INTO incidents (object_type, threat_score, zone_level) VALUES ('Dog', 40, 'SAFE')")
        conn.commit()
    finally:
        conn.close()


def dump(path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT * FROM incidents ORDER BY id").fetchall()
    finally:
        conn.close()


class TestLegacyMigration:
    @pytest.fixture
    def legacy_path(self, tmp_path):
        path = tmp_path / "chanakya.db"
        make_legacy_db(path)
        return path

    def test_columns_are_added(self, legacy_path):
        DatabaseManager(legacy_path)
        conn = sqlite3.connect(legacy_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(incidents)")}
        finally:
            conn.close()
        assert columns == set(INCIDENT_KEYS)

    def test_rows_are_rewritten(self, legacy_path):
        manager = DatabaseManager(legacy_path)
        items, total = manager.list_incidents(limit=50)
        assert total == 6
        by_id = {item["id"]: item for item in items}

        first = by_id[1]
        assert list(first) == INCIDENT_KEYS
        assert first["timestamp"] == "2025-01-05T09:15:42Z"
        assert first["camera"] == "alpha"
        assert first["object_type"] == "[ALPHA] Aryan (ID:3, Emotion:Happy 80%)"  # untouched
        assert first["category"] == "CRITICAL"
        assert first["image_path"] == "/abs/snapshots/a.jpg"
        assert first["acknowledged"] is False
        assert first["reasons"] == [] and first["clip_path"] is None
        assert first["identity"] is None and first["track_id"] is None

        assert by_id[2]["camera"] == "bravo" and by_id[2]["category"] == "WARNING"
        assert by_id[2]["image_path"] is None  # the *string* "None"
        assert by_id[3]["camera"] is None and by_id[3]["category"] == "LOW"
        assert by_id[4]["camera"] is None  # best effort: not a plausible camera tag
        assert by_id[4]["category"] == "CRITICAL" and by_id[4]["image_path"] is None
        assert by_id[5]["camera"] == "gate_2" and by_id[5]["category"] == "LOW"
        assert all(ISO_Z.fullmatch(item["timestamp"]) for item in items)  # incl. CURRENT_TIMESTAMP row

    def test_migration_is_idempotent(self, legacy_path):
        DatabaseManager(legacy_path)
        once = dump(legacy_path)
        DatabaseManager(legacy_path)
        DatabaseManager(legacy_path)
        assert dump(legacy_path) == once

    def test_migrated_database_is_fully_usable(self, legacy_path, clock):
        manager = DatabaseManager(legacy_path, clock=clock)
        new_id = log(manager, reasons=["x"], track_id=1)
        assert new_id == 7
        items, total = manager.list_incidents()
        assert total == 7 and items[0]["id"] == new_id  # new ISO stamps sort after migrated ones
        assert manager.acknowledge(1) is True
        assert manager.list_incidents(camera="alpha", acknowledged=True)[1] == 1
        assert manager.get_recent_logs(1) == [("2026-09-22T14:30:00Z", "Person", 80, "SAFE")]
        assert [d["id"] for d in manager.purge_older_than(30)] == [1, 2, 3, 4, 5]

    def test_migration_does_not_touch_v2_rows(self, db):
        incident_id = log(db, category="LOW", threat_score=99, object_type="[X] looks legacy", camera="real")
        before = db.get_incident(incident_id)
        assert DatabaseManager(db.db_path).get_incident(incident_id) == before

    def test_migration_is_logged_without_print(self, legacy_path, caplog, capsys):
        with caplog.at_level("INFO", logger="chanakya.database_manager"):
            DatabaseManager(legacy_path)
        assert "Migrated legacy incident table" in caplog.text
        assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# threads
# --------------------------------------------------------------------------- #
class TestConcurrency:
    def test_concurrent_writes_from_threads(self, db):
        writers, per_writer = 8, 25
        errors: list[BaseException] = []
        ids: list[int] = []
        ids_lock = threading.Lock()
        start = threading.Barrier(writers + 1)

        def write(worker: int) -> None:
            try:
                start.wait(timeout=10)
                for n in range(per_writer):
                    new_id = db.log_incident(
                        camera=f"cam{worker}",
                        object_type="Person",
                        threat_score=n,
                        reasons=[f"w{worker}"],
                    )
                    db.acknowledge(new_id)
                    db.set_clip_path(new_id, f"/clips/{new_id}.mp4")
                    with ids_lock:
                        ids.append(new_id)
            except BaseException as exc:  # noqa: BLE001 - surfaced through `errors`
                errors.append(exc)

        def read() -> None:
            try:
                start.wait(timeout=10)
                for _ in range(40):
                    items, total = db.list_incidents(limit=10)
                    assert len(items) == min(10, total)
                    db.stats()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
        threads.append(threading.Thread(target=read))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
        assert len(ids) == len(set(ids)) == writers * per_writer
        items, total = db.list_incidents(limit=1000)
        assert total == writers * per_writer
        assert all(item["acknowledged"] and item["clip_path"] == f"/clips/{item['id']}.mp4" for item in items)
        assert db.stats()["by_camera"] == {f"cam{w}": per_writer for w in range(writers)}

    def test_two_managers_on_one_file(self, db):
        other = DatabaseManager(db.db_path)
        first = log(db)
        second = log(other)
        assert {i["id"] for i in db.list_incidents()[0]} == {first, second}

    def test_connections_are_closed(self, db, tmp_path):
        """A leaked connection per call would exhaust file descriptors in a long run."""
        import gc
        import os

        fd_dir = "/dev/fd"
        if not os.path.isdir(fd_dir):
            pytest.skip("no /dev/fd on this platform")
        gc.collect()
        before = len(os.listdir(fd_dir))
        for _ in range(50):
            log(db)
            db.list_incidents()
            db.stats()
        gc.collect()
        assert len(os.listdir(fd_dir)) <= before + 3


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
class TestHelpers:
    @pytest.mark.parametrize(
        ("score", "category"),
        [(0, "LOW"), (29, "LOW"), (30, "WARNING"), (69, "WARNING"), (70, "CRITICAL"), (100, "CRITICAL")],
    )
    def test_category_for_score(self, score, category):
        assert category_for_score(score) == category

    def test_to_iso_z(self):
        assert to_iso_z("2026-09-22T14:03:11Z") == "2026-09-22T14:03:11Z"
        assert to_iso_z("2026-09-22 14:03:11") == "2026-09-22T14:03:11Z"
        assert to_iso_z("2026-09-22T19:33:11+05:30") == "2026-09-22T14:03:11Z"
        assert to_iso_z(datetime(2026, 9, 22, 14, 3, 11, 999999)) == "2026-09-22T14:03:11Z"
