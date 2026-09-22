"""src.zones: defaults, validation, persistence, priority, thread safety."""

from __future__ import annotations

import json
import os
import threading

import numpy as np
import pytest

from src.zones import LEVEL_COLORS_BGR, LEVELS, SecurityZone, ZoneManager, validate_zones


def zone(name="Door", level="CRITICAL", rect=(0.1, 0.1, 0.5, 0.5), **extra) -> dict:
    return {"name": name, "level": level, "rect": list(rect), **extra}


# --------------------------------------------------------------------------- #
# constants + SecurityZone
# --------------------------------------------------------------------------- #
def test_levels_and_colours():
    assert LEVELS == ("SAFE", "PERIMETER", "WARNING", "CRITICAL")
    assert LEVEL_COLORS_BGR == {
        "SAFE": (0, 255, 0),
        "PERIMETER": (255, 200, 0),
        "WARNING": (0, 165, 255),
        "CRITICAL": (0, 0, 255),
    }


def test_security_zone_contains_and_to_dict():
    z = SecurityZone("z1", "Door", "WARNING", (0.25, 0.5, 0.75, 1.0))
    assert z.contains(0.5, 0.75)
    assert z.contains(0.25, 0.5) and z.contains(0.75, 1.0)  # edges inclusive
    assert not z.contains(0.24, 0.75) and not z.contains(0.5, 0.49)
    assert z.to_dict() == {"id": "z1", "name": "Door", "level": "WARNING", "rect": [0.25, 0.5, 0.75, 1.0]}
    json.dumps(z.to_dict())


# --------------------------------------------------------------------------- #
# defaults
# --------------------------------------------------------------------------- #
class TestDefaults:
    def test_default_set(self, zone_manager):
        zones = zone_manager.get_zones("default")
        assert [(z.name, z.level, z.rect) for z in zones] == [
            ("Safe", "SAFE", (0.0, 0.0, 0.4, 1.0)),
            ("Warning", "WARNING", (0.4, 0.0, 0.75, 1.0)),
            ("Critical", "CRITICAL", (0.75, 0.0, 1.0, 1.0)),
        ]
        assert len({z.id for z in zones}) == 3

    def test_unknown_camera_falls_back_to_default(self, zone_manager):
        assert zone_manager.get_zones("alpha") == zone_manager.get_zones("default")

    def test_to_dict_shape(self, zone_manager):
        table = zone_manager.to_dict()
        assert list(table) == ["default"]
        assert [set(z) for z in table["default"]] == [{"id", "name", "level", "rect"}] * 3
        json.dumps(table)

    def test_construction_writes_nothing(self, zones_file):
        ZoneManager(zones_file)
        assert not zones_file.exists() and not zones_file.parent.exists()

    def test_get_zones_returns_a_copy(self, zone_manager):
        zone_manager.get_zones("default").clear()
        assert len(zone_manager.get_zones("default")) == 3

    def test_default_path_comes_from_settings(self, tmp_path, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "ZONES_FILE", tmp_path / "s" / "zones.json")
        manager = ZoneManager()
        manager.set_zones("alpha", [zone()])
        assert (tmp_path / "s" / "zones.json").is_file()


# --------------------------------------------------------------------------- #
# set_zones semantics
# --------------------------------------------------------------------------- #
class TestSetZones:
    def test_camera_specific_set_overrides_default(self, zone_manager):
        result = zone_manager.set_zones("alpha", [zone("Door", "CRITICAL", (0.1, 0.2, 0.3, 0.4))])
        assert [(z.name, z.level, z.rect) for z in result] == [("Door", "CRITICAL", (0.1, 0.2, 0.3, 0.4))]
        assert zone_manager.get_zones("alpha") == result
        assert len(zone_manager.get_zones("bravo")) == 3  # others still on default
        assert set(zone_manager.to_dict()) == {"default", "alpha"}

    def test_empty_list_deletes_the_camera_set_and_falls_back(self, zone_manager, zones_file):
        zone_manager.set_zones("alpha", [zone()])
        result = zone_manager.set_zones("alpha", [])
        assert result == zone_manager.get_zones("default")
        assert "alpha" not in zone_manager.to_dict()
        assert "alpha" not in json.loads(zones_file.read_text())
        assert zone_manager.set_zones("never_set", []) == zone_manager.get_zones("default")

    def test_default_set_cannot_be_emptied(self, zone_manager):
        with pytest.raises(ValueError, match="default"):
            zone_manager.set_zones("default", [])
        assert len(zone_manager.get_zones("default")) == 3

    def test_default_set_can_be_replaced(self, zone_manager):
        zone_manager.set_zones("default", [zone("Everything", "PERIMETER", (0, 0, 1, 1))])
        assert [z.level for z in zone_manager.get_zones("anything")] == ["PERIMETER"]

    def test_ints_are_accepted_and_stored_as_floats(self, zone_manager):
        (z,) = zone_manager.set_zones("alpha", [zone(rect=(0, 0, 1, 1))])
        assert z.rect == (0.0, 0.0, 1.0, 1.0) and all(isinstance(v, float) for v in z.rect)

    def test_name_is_stripped_and_unicode_allowed(self, zone_manager):
        (z,) = zone_manager.set_zones("alpha", [zone(name="  द्वार Door  ")])
        assert z.name == "द्वार Door"

    def test_unknown_keys_are_dropped(self, zone_manager, zones_file):
        zone_manager.set_zones("alpha", [zone(color="red", __proto__={"x": 1})])
        assert set(zone_manager.to_dict()["alpha"][0]) == {"id", "name", "level", "rect"}
        assert set(json.loads(zones_file.read_text())["alpha"][0]) == {"id", "name", "level", "rect"}

    def test_twelve_zones_allowed(self, zone_manager):
        assert len(zone_manager.set_zones("alpha", [zone(name=f"Z{i}") for i in range(12)])) == 12


class TestIds:
    def test_valid_client_id_is_kept(self, zone_manager):
        (z,) = zone_manager.set_zones("alpha", [zone(id="Front_door-1")])
        assert z.id == "Front_door-1"

    @pytest.mark.parametrize("bad", [None, "", "has space", "a" * 33, "../x", 7, "x\n", ["a"]])
    def test_invalid_client_id_is_replaced(self, zone_manager, bad):
        (z,) = zone_manager.set_zones("alpha", [zone(id=bad)])
        assert z.id != bad and isinstance(z.id, str) and z.id

    def test_duplicate_ids_are_made_unique_first_holder_wins(self, zone_manager):
        result = zone_manager.set_zones("alpha", [zone(id="dup"), zone(id="dup"), zone(), zone()])
        ids = [z.id for z in result]
        assert ids[0] == "dup" and len(set(ids)) == 4

    def test_ids_are_stable_across_a_save_round_trip(self, zone_manager):
        saved = zone_manager.set_zones("alpha", [zone(), zone(name="Two")])
        resaved = zone_manager.set_zones("alpha", [z.to_dict() for z in saved])
        assert [z.id for z in resaved] == [z.id for z in saved]


class TestValidation:
    @pytest.mark.parametrize(
        "rect",
        [
            [float("nan"), 0, 1, 1],
            [0, 0, float("inf"), 1],
            [0, float("-inf"), 1, 1],
            [True, 0, 1, 1],
            [0, 0, 1, True],
            [False, False, True, True],
            ["0", "0", "1", "1"],
            [None, 0, 1, 1],
            [0, 0, 1],
            [0, 0, 1, 1, 1],
            [],
            "0,0,1,1",
            None,
            {"x1": 0},
            [-0.01, 0, 1, 1],
            [0, 0, 1.01, 1],
            [0.5, 0, 0.5, 1],  # zero width
            [0.6, 0, 0.5, 1],  # inverted
            [0, 0.5, 1, 0.5],  # zero height
            [0, 0.6, 1, 0.5],
            [[0], 0, 1, 1],
            [1e400, 0, 1, 1],
        ],
    )
    def test_bad_rects(self, zone_manager, rect):
        with pytest.raises(ValueError, match="rect"):
            zone_manager.set_zones(
                "alpha", [zone(rect=rect) if isinstance(rect, (list, tuple)) else {**zone(), "rect": rect}]
            )

    def test_json_decoded_nan_infinity_and_true_are_rejected(self, zone_manager):
        """json.loads accepts all three; this is the path a request body takes."""
        for literal in ("NaN", "Infinity", "-Infinity", "true"):
            body = json.loads('{"zones": [{"name": "A", "level": "SAFE", "rect": [0, 0, %s, 1]}]}' % literal)
            with pytest.raises(ValueError, match="rect"):
                zone_manager.set_zones("alpha", body["zones"])
        assert "alpha" not in zone_manager.to_dict()

    @pytest.mark.parametrize("level", ["critical", "DANGER", "", None, 3, ["SAFE"]])
    def test_bad_levels(self, zone_manager, level):
        with pytest.raises(ValueError, match="level"):
            zone_manager.set_zones("alpha", [zone(level=level)])

    @pytest.mark.parametrize(
        "name",
        ["", "   ", "x" * 41, "tab\there", "new\nline", "nul\x00", "esc\x1b[31m", "\u202eevil", None, 5, ["a"]],
    )
    def test_bad_names(self, zone_manager, name):
        with pytest.raises(ValueError, match="name"):
            zone_manager.set_zones("alpha", [zone(name=name)])

    def test_name_of_exactly_forty_chars(self, zone_manager):
        assert zone_manager.set_zones("alpha", [zone(name="x" * 40)])[0].name == "x" * 40

    @pytest.mark.parametrize("zones", [None, {}, "[]", 5, (zone(),)])
    def test_zones_must_be_a_list(self, zone_manager, zones):
        with pytest.raises(ValueError, match="list"):
            zone_manager.set_zones("alpha", zones)

    @pytest.mark.parametrize("item", [None, "zone", 5, [zone()]])
    def test_items_must_be_objects(self, zone_manager, item):
        with pytest.raises(ValueError, match="zone 1"):
            zone_manager.set_zones("alpha", [zone(), item])

    def test_too_many_zones(self, zone_manager):
        with pytest.raises(ValueError, match="12"):
            zone_manager.set_zones("alpha", [zone(name=f"Z{i}") for i in range(13)])

    @pytest.mark.parametrize("camera_id", ["", "Alpha", "a b", "../etc", "a" * 33, None, 5, "cam\n"])
    def test_bad_camera_ids(self, zone_manager, camera_id):
        with pytest.raises(ValueError, match="camera_id"):
            zone_manager.set_zones(camera_id, [zone()])

    def test_a_failed_validation_changes_nothing(self, zone_manager, zones_file):
        zone_manager.set_zones("alpha", [zone(name="Keep")])
        on_disk = zones_file.read_text()
        with pytest.raises(ValueError):
            zone_manager.set_zones("alpha", [zone(name="New"), zone(rect=[0, 0, 2, 2])])
        assert [z.name for z in zone_manager.get_zones("alpha")] == ["Keep"]
        assert zones_file.read_text() == on_disk

    def test_validate_zones_is_pure(self):
        given = [zone(id="a", extra=1)]
        snapshot = json.dumps(given)
        validate_zones(given)
        assert json.dumps(given) == snapshot


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
class TestPersistence:
    def test_reload_restores_everything(self, zone_manager, zones_file):
        alpha = zone_manager.set_zones("alpha", [zone("Door", "CRITICAL", (0.1, 0.2, 0.3, 0.4), id="door")])
        zone_manager.set_zones("default", [zone("All", "PERIMETER", (0, 0, 1, 1), id="all")])
        reloaded = ZoneManager(zones_file)
        assert reloaded.get_zones("alpha") == alpha
        assert reloaded.to_dict() == zone_manager.to_dict()
        assert reloaded.get_zones("bravo")[0].id == "all"

    def test_file_is_the_to_dict_shape(self, zone_manager, zones_file):
        zone_manager.set_zones("alpha", [zone()])
        assert json.loads(zones_file.read_text()) == zone_manager.to_dict()

    def test_write_is_atomic_via_os_replace(self, zone_manager, zones_file, monkeypatch):
        replaced = []
        real_replace = os.replace

        def spy(src, dst):
            # The complete new content must already be in the temp file.
            replaced.append((str(src), str(dst), json.loads(open(src).read())))
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy)
        zone_manager.set_zones("alpha", [zone(id="door")])
        assert len(replaced) == 1
        src, dst, content = replaced[0]
        assert dst == str(zones_file) and src != dst
        assert os.path.dirname(src) == os.path.dirname(dst)  # same filesystem => atomic rename
        assert content["alpha"][0]["id"] == "door"
        assert sorted(p.name for p in zones_file.parent.iterdir()) == ["zones.json"]  # no temp litter

    def test_failed_write_keeps_old_state_on_disk_and_in_memory(self, zone_manager, zones_file, monkeypatch):
        zone_manager.set_zones("alpha", [zone(name="Old")])
        on_disk = zones_file.read_text()

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            zone_manager.set_zones("alpha", [zone(name="New")])
        assert [z.name for z in zone_manager.get_zones("alpha")] == ["Old"]
        assert zones_file.read_text() == on_disk
        assert sorted(p.name for p in zones_file.parent.iterdir()) == ["zones.json"]

    @pytest.mark.parametrize(
        "content",
        [b"", b"{not json", b"[1, 2, 3]", b"\xff\xfe\x00garbage", b'"a string"', b"null", b"[" * 100000],
    )
    def test_corrupt_file_falls_back_to_defaults_with_a_warning(self, zones_file, caplog, content):
        zones_file.parent.mkdir(parents=True)
        zones_file.write_bytes(content)
        with caplog.at_level("WARNING", logger="chanakya.zones"):
            manager = ZoneManager(zones_file)
        assert [z.level for z in manager.get_zones("alpha")] == ["SAFE", "WARNING", "CRITICAL"]
        assert any(record.levelname == "WARNING" for record in caplog.records)
        # ... and the manager still works and repairs the file on the next save.
        manager.set_zones("alpha", [zone()])
        assert "alpha" in ZoneManager(zones_file).to_dict()

    def test_missing_file_is_not_a_warning(self, zones_file, caplog):
        with caplog.at_level("WARNING", logger="chanakya.zones"):
            ZoneManager(zones_file)
        assert caplog.records == []

    def test_one_invalid_camera_entry_does_not_discard_the_others(self, zones_file, caplog):
        zones_file.parent.mkdir(parents=True)
        zones_file.write_text(
            json.dumps(
                {
                    "default": [zone("All", "PERIMETER", (0, 0, 1, 1), id="all")],
                    "alpha": [zone("Door", "CRITICAL", (0.1, 0.1, 0.2, 0.2), id="door")],
                    "bravo": [zone(rect=(0, 0, 5, 5))],
                    "BAD ID": [zone()],
                    "charlie": "nonsense",
                    "delta": [],
                }
            )
        )
        with caplog.at_level("WARNING", logger="chanakya.zones"):
            manager = ZoneManager(zones_file)
        assert set(manager.to_dict()) == {"default", "alpha"}
        assert manager.get_zones("alpha")[0].id == "door"
        assert manager.get_zones("bravo")[0].id == "all"
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 4

    def test_file_with_nan_is_rejected_on_load(self, zones_file):
        zones_file.parent.mkdir(parents=True)
        zones_file.write_text('{"default": [{"name": "A", "level": "CRITICAL", "rect": [0, 0, NaN, 1]}]}')
        assert [z.name for z in ZoneManager(zones_file).get_zones("default")] == ["Safe", "Warning", "Critical"]

    def test_invalid_default_in_file_falls_back_to_builtin_default(self, zones_file):
        zones_file.parent.mkdir(parents=True)
        zones_file.write_text(json.dumps({"default": [], "alpha": [zone(id="door")]}))
        manager = ZoneManager(zones_file)
        assert len(manager.get_zones("default")) == 3
        assert manager.get_zones("alpha")[0].id == "door"


# --------------------------------------------------------------------------- #
# level_at
# --------------------------------------------------------------------------- #
class TestLevelAt:
    def test_default_layout(self, zone_manager):
        assert zone_manager.level_at("alpha", 100, 240, 640, 480) == "SAFE"
        assert zone_manager.level_at("alpha", 300, 240, 640, 480) == "WARNING"
        assert zone_manager.level_at("alpha", 600, 240, 640, 480) == "CRITICAL"

    def test_is_resolution_independent(self, zone_manager):
        assert zone_manager.level_at("alpha", 1800, 500, 1920, 1080) == "CRITICAL"
        assert zone_manager.level_at("alpha", 180, 500, 1920, 1080) == "SAFE"

    def test_shared_border_resolves_to_the_higher_priority(self, zone_manager):
        assert zone_manager.level_at("alpha", 256, 100, 640, 480) == "WARNING"  # x = 0.4 exactly
        assert zone_manager.level_at("alpha", 480, 100, 640, 480) == "CRITICAL"  # x = 0.75 exactly

    def test_frame_edges_are_inside(self, zone_manager):
        """The worker clamps the feet point to the frame; y may equal frame_h."""
        assert zone_manager.level_at("alpha", 0, 0, 640, 480) == "SAFE"
        assert zone_manager.level_at("alpha", 640, 480, 640, 480) == "CRITICAL"

    @pytest.mark.parametrize("order", [(0, 1, 2, 3), (3, 2, 1, 0), (2, 0, 3, 1)])
    def test_highest_priority_wins_regardless_of_list_order(self, zone_manager, order):
        overlapping = [
            zone("Whole", "SAFE", (0, 0, 1, 1)),
            zone("Yard", "PERIMETER", (0.2, 0.2, 0.8, 0.8)),
            zone("Porch", "WARNING", (0.3, 0.3, 0.7, 0.7)),
            zone("Door", "CRITICAL", (0.4, 0.4, 0.6, 0.6)),
        ]
        zone_manager.set_zones("alpha", [overlapping[i] for i in order])
        assert zone_manager.level_at("alpha", 50, 50, 100, 100) == "CRITICAL"
        assert zone_manager.level_at("alpha", 35, 35, 100, 100) == "WARNING"
        assert zone_manager.level_at("alpha", 25, 25, 100, 100) == "PERIMETER"
        assert zone_manager.level_at("alpha", 5, 5, 100, 100) == "SAFE"

    def test_point_in_no_zone_is_safe(self, zone_manager):
        zone_manager.set_zones("alpha", [zone("Door", "CRITICAL", (0.4, 0.4, 0.6, 0.6))])
        assert zone_manager.level_at("alpha", 5, 5, 100, 100) == "SAFE"

    def test_uses_the_camera_specific_set(self, zone_manager):
        zone_manager.set_zones("alpha", [zone("All", "PERIMETER", (0, 0, 1, 1))])
        assert zone_manager.level_at("alpha", 600, 240, 640, 480) == "PERIMETER"
        assert zone_manager.level_at("bravo", 600, 240, 640, 480) == "CRITICAL"

    @pytest.mark.parametrize("size", [(0, 480), (640, 0), (-1, -1)])
    def test_degenerate_frame_is_safe(self, zone_manager, size):
        assert zone_manager.level_at("alpha", 10, 10, *size) == "SAFE"


# --------------------------------------------------------------------------- #
# draw
# --------------------------------------------------------------------------- #
class TestDraw:
    def test_draws_in_place_with_level_colours(self, zone_manager):
        pytest.importorskip("cv2")
        zone_manager.set_zones("alpha", [zone("Door ☃", "CRITICAL", (0.25, 0.25, 0.75, 0.75))])
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        assert zone_manager.draw(frame, "alpha") is None
        assert frame.any()
        left_edge_x, mid_y = int(0.25 * 639), 300
        assert tuple(int(v) for v in frame[mid_y, left_edge_x]) == LEVEL_COLORS_BGR["CRITICAL"]
        assert not frame[:100, :100].any()  # nothing outside the rectangle

    def test_default_zones_fit_any_resolution(self, zone_manager):
        pytest.importorskip("cv2")
        for shape in [(480, 640, 3), (1080, 1920, 3), (2, 2, 3)]:
            frame = np.zeros(shape, dtype=np.uint8)
            zone_manager.draw(frame, "whatever")
            assert frame.any()


# --------------------------------------------------------------------------- #
# thread safety
# --------------------------------------------------------------------------- #
def test_concurrent_readers_and_writers(zone_manager, zones_file):
    errors: list[BaseException] = []
    stop = threading.Event()
    start = threading.Barrier(7)

    def writer(camera_id: str) -> None:
        try:
            start.wait(timeout=10)
            for n in range(40):
                level = LEVELS[n % len(LEVELS)]
                if n % 10 == 9:
                    zone_manager.set_zones(camera_id, [])
                else:
                    zone_manager.set_zones(camera_id, [zone(f"{camera_id}-{n}", level, (0, 0, 1, 1))] * (n % 3 + 1))
        except BaseException as exc:  # noqa: BLE001 - surfaced through `errors`
            errors.append(exc)

    def reader() -> None:
        try:
            start.wait(timeout=10)
            while not stop.is_set():
                for camera_id in ("cam0", "cam1", "cam2", "other"):
                    assert zone_manager.level_at(camera_id, 320, 240, 640, 480) in LEVELS
                    zones = zone_manager.get_zones(camera_id)
                    assert zones and len({z.id for z in zones}) == len(zones)
                json.dumps(zone_manager.to_dict())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    writers = [threading.Thread(target=writer, args=(f"cam{i}",)) for i in range(3)]
    readers = [threading.Thread(target=reader) for _ in range(4)]
    for thread in writers + readers:
        thread.start()
    for thread in writers:
        thread.join(timeout=60)
    stop.set()
    for thread in readers:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in writers + readers)
    assert errors == []
    # Last write per camera was n=39 -> an empty list -> camera set deleted.
    assert set(zone_manager.to_dict()) == {"default"}
    # The file was never left torn, and matches memory.
    assert json.loads(zones_file.read_text()) == zone_manager.to_dict()
    assert ZoneManager(zones_file).to_dict() == zone_manager.to_dict()
    assert sorted(p.name for p in zones_file.parent.iterdir()) == ["zones.json"]
