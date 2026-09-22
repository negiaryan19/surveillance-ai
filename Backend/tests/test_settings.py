"""config.settings: constants, env overrides, parse_cameras, safe_child, ensure_dirs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from config import settings

SECRET_URL = "rtsp://admin:hunter2@10.0.0.5:554/stream?channel=1&token=s3cr3t"


# --------------------------------------------------------------------------- #
# parse_cameras
# --------------------------------------------------------------------------- #
class TestParseCameras:
    def test_contract_example(self):
        cameras = settings.parse_cameras("alpha=0,gate=rtsp://user:pw@host/s?x=1,demo=/path/clip.mp4")
        assert cameras == [
            {"id": "alpha", "name": "ALPHA", "source": 0},
            {"id": "gate", "name": "GATE", "source": "rtsp://user:pw@host/s?x=1"},
            {"id": "demo", "name": "DEMO", "source": "/path/clip.mp4"},
        ]

    def test_splits_on_first_equals_only(self):
        (camera,) = settings.parse_cameras(f"gate={SECRET_URL}")
        assert camera["source"] == SECRET_URL
        assert camera["source"].count("=") == 2

    def test_digit_only_source_becomes_int(self):
        (camera,) = settings.parse_cameras("cam=12")
        assert camera["source"] == 12 and isinstance(camera["source"], int)

    def test_non_ascii_digits_are_not_a_camera_index(self):
        (camera,) = settings.parse_cameras("cam=٣")  # ARABIC-INDIC DIGIT THREE
        assert isinstance(camera["source"], str)

    def test_mixed_source_stays_a_string(self):
        (camera,) = settings.parse_cameras("cam=0.mp4")
        assert camera["source"] == "0.mp4"

    def test_whitespace_and_trailing_commas_are_tolerated(self):
        cameras = settings.parse_cameras("  alpha = 0 , , bravo=1,")
        assert [c["id"] for c in cameras] == ["alpha", "bravo"]
        assert [c["source"] for c in cameras] == [0, 1]

    def test_percent_encoded_comma_is_preserved(self):
        (camera,) = settings.parse_cameras("cam=http://h/s?a=1%2C2")
        assert camera["source"] == "http://h/s?a=1%2C2"

    def test_id_charset_and_length_limits(self):
        long_id = "a" * 32
        assert settings.parse_cameras(f"{long_id}=0")[0]["id"] == long_id
        assert settings.parse_cameras("front_door-2=0")[0]["name"] == "FRONT_DOOR-2"
        with pytest.raises(ValueError):
            settings.parse_cameras(f"{'a' * 33}=0")

    @pytest.mark.parametrize(
        "spec",
        ["Alpha=0", "al pha=0", "al.pha=0", "=0", "café=0", "a/b=0", "alpha\nbeta=0"],
    )
    def test_bad_ids_are_rejected(self, spec):
        with pytest.raises(ValueError):
            settings.parse_cameras(spec)

    def test_default_id_is_rejected(self):
        with pytest.raises(ValueError, match="default"):
            settings.parse_cameras("alpha=0,default=1")

    def test_duplicate_id_is_rejected_and_named(self):
        with pytest.raises(ValueError, match="gate"):
            settings.parse_cameras(f"gate=0,gate={SECRET_URL}")

    @pytest.mark.parametrize("spec", ["alpha", "alpha=", "alpha=   "])
    def test_missing_source_is_rejected_and_names_the_id(self, spec):
        with pytest.raises(ValueError, match="alpha"):
            settings.parse_cameras(spec)

    @pytest.mark.parametrize("spec", ["", "   ", ",,"])
    def test_empty_spec_is_rejected(self, spec):
        with pytest.raises(ValueError):
            settings.parse_cameras(spec)

    @pytest.mark.parametrize(
        "spec",
        [
            SECRET_URL,  # id forgotten: the URL sits where the id belongs
            f"Gate={SECRET_URL}",  # invalid id
            f"default={SECRET_URL}",  # reserved id
            f"gate={SECRET_URL},gate={SECRET_URL}",  # duplicate
            f"ok=0,{SECRET_URL}",
            f"{SECRET_URL}=0",
        ],
    )
    def test_error_messages_never_echo_the_source(self, spec):
        with pytest.raises(ValueError) as excinfo:
            settings.parse_cameras(spec)
        message = str(excinfo.value)
        for secret in ("hunter2", "admin", "s3cr3t", "10.0.0.5", "rtsp"):
            assert secret not in message
        # "raise ... from None": no chained exception may carry the secret either.
        assert excinfo.value.__cause__ is None
        assert excinfo.value.__suppress_context__ or excinfo.value.__context__ is None


# --------------------------------------------------------------------------- #
# safe_child
# --------------------------------------------------------------------------- #
class TestSafeChild:
    @pytest.fixture
    def root(self, tmp_path) -> Path:
        directory = tmp_path / "snapshots"
        directory.mkdir()
        return directory

    def test_file_inside_root(self, root):
        target = root / "a.jpg"
        target.write_bytes(b"x")
        assert settings.safe_child(target, root) == target.resolve()
        assert settings.safe_child(str(target), str(root)) == target.resolve()

    def test_nested_file_inside_root(self, root):
        nested = root / "2026" / "09"
        nested.mkdir(parents=True)
        target = nested / "a.jpg"
        target.write_bytes(b"x")
        assert settings.safe_child(target, root) == target.resolve()

    def test_sibling_directory_sharing_the_prefix_is_rejected(self, root, tmp_path):
        evil = tmp_path / "snapshots_evil"
        evil.mkdir()
        target = evil / "a.jpg"
        target.write_bytes(b"x")
        assert str(target).startswith(str(root))  # the trap a startswith check falls into
        assert settings.safe_child(target, root) is None

    def test_dotdot_traversal_is_rejected(self, root, tmp_path):
        outside = tmp_path / "secret.key"
        outside.write_bytes(b"k")
        assert settings.safe_child(root / ".." / "secret.key", root) is None

    def test_symlink_escaping_the_root_is_rejected(self, root, tmp_path):
        outside = tmp_path / "secret.key"
        outside.write_bytes(b"k")
        link = root / "innocent.jpg"
        link.symlink_to(outside)
        assert link.is_file()
        assert settings.safe_child(link, root) is None

    def test_symlinked_directory_escaping_the_root_is_rejected(self, root, tmp_path):
        outside_dir = tmp_path / "elsewhere"
        outside_dir.mkdir()
        (outside_dir / "a.jpg").write_bytes(b"x")
        (root / "sub").symlink_to(outside_dir, target_is_directory=True)
        assert settings.safe_child(root / "sub" / "a.jpg", root) is None

    def test_symlink_staying_inside_the_root_is_allowed(self, root):
        target = root / "real.jpg"
        target.write_bytes(b"x")
        link = root / "alias.jpg"
        link.symlink_to(target)
        assert settings.safe_child(link, root) == target.resolve()

    def test_the_root_itself_is_rejected(self, root):
        assert settings.safe_child(root, root) is None
        assert settings.safe_child(root / ".", root) is None

    def test_a_directory_is_rejected(self, root):
        (root / "sub").mkdir()
        assert settings.safe_child(root / "sub", root) is None

    def test_missing_file_is_rejected(self, root):
        assert settings.safe_child(root / "missing.jpg", root) is None

    @pytest.mark.parametrize("falsy", [None, "", 0])
    def test_falsy_path_is_rejected(self, root, falsy):
        assert settings.safe_child(falsy, root) is None

    def test_unresolvable_input_is_rejected_not_raised(self, root):
        assert settings.safe_child("bad\x00name.jpg", root) is None
        assert settings.safe_child(12345, root) is None

    def test_relative_path_resolves_against_base_dir_not_cwd(self, tmp_path, monkeypatch):
        base = tmp_path / "backend"
        cwd = tmp_path / "somewhere_else"
        (base / "snaps").mkdir(parents=True)
        (cwd / "snaps").mkdir(parents=True)
        (base / "snaps" / "in_base.jpg").write_bytes(b"x")
        (cwd / "snaps" / "in_cwd.jpg").write_bytes(b"x")
        monkeypatch.setattr(settings, "BASE_DIR", base)
        monkeypatch.chdir(cwd)

        expected = (base / "snaps" / "in_base.jpg").resolve()
        assert settings.safe_child("snaps/in_base.jpg", base / "snaps") == expected
        assert settings.safe_child("snaps/in_base.jpg", "snaps") == expected
        # Exists relative to the CWD only: must not be found.
        assert settings.safe_child("snaps/in_cwd.jpg", cwd / "snaps") is None
        assert settings.safe_child("snaps/in_cwd.jpg", "snaps") is None


# --------------------------------------------------------------------------- #
# module constants + env overrides (private copies; see conftest.load_settings)
# --------------------------------------------------------------------------- #
class TestDefaults:
    def test_paths(self, load_settings):
        s = load_settings()
        assert s.BASE_DIR == Path(settings.__file__).resolve().parent.parent
        assert s.DATA_DIR == s.BASE_DIR / "database"
        assert s.SNAPSHOTS_DIR == s.DATA_DIR / "snapshots"
        assert s.VIDEOS_DIR == s.DATA_DIR / "videos"
        assert s.REPORTS_DIR == s.DATA_DIR / "reports"
        assert s.KNOWN_FACES_DIR == s.DATA_DIR / "known_faces"
        assert s.ENCODINGS_FILE == s.DATA_DIR / "face_encodings.npz"
        assert s.DB_PATH == s.DATA_DIR / "chanakya.db"
        assert s.ZONES_FILE == s.DATA_DIR / "zones.json"
        assert s.KEY_FILE == s.DATA_DIR / "secret.key"
        assert s.FRONTEND_DIST == s.BASE_DIR.parent / "frontend" / "dist"
        assert s.MODEL_PATH == str(s.BASE_DIR / "models" / "yolov8n.pt")
        assert s.POSE_MODEL_PATH == str(s.BASE_DIR / "yolov8n-pose.pt")
        assert s.DATA_DIR.is_absolute()

    def test_contract_values(self, load_settings):
        s = load_settings()
        assert (s.FRAME_WIDTH, s.FRAME_HEIGHT, s.JPEG_QUALITY) == (640, 480, 80)
        assert s.CAMERAS == [
            {"id": "alpha", "name": "ALPHA", "source": 0},
            {"id": "bravo", "name": "BRAVO", "source": 1},
        ]
        assert s.THREAT_CLASSES == {
            0: "Person",
            2: "Car",
            3: "Motorcycle",
            16: "Dog",
            43: "Weapon (Knife)",
        }
        assert s.CONFIDENCE_LIMIT == 0.65 and s.CLASS_CONFIDENCE == {43: 0.35}
        assert (s.HEAVY_EVERY_N_FRAMES, s.POSE_EVERY_N_FRAMES) == (5, 2)
        assert (s.FACE_TOLERANCE, s.EAR_THRESHOLD) == (0.6, 0.22)
        assert (s.LIVENESS_TTL, s.LIVENESS_GRACE, s.LIVENESS_MAX_VERIFY) == (30.0, 15.0, 45.0)
        assert (s.LOITER_SECONDS, s.TRACK_MAX_AGE, s.PRONE_MIN_SECONDS) == (10.0, 5.0, 1.5)
        assert (s.RUN_SPEED_BH, s.ERRATIC_SPEED_BH) == (2.0, 1.2)
        assert (s.ALERT_MIN_SCORE, s.ALERT_MIN_TRACK_AGE) == (70, 2.0)
        assert (s.ALERT_TRACK_COOLDOWN, s.ALERT_ESCALATION_DELTA) == (60.0, 15)
        assert (s.ALERT_CAMERA_MIN_INTERVAL, s.ALERT_NOTIFY_MIN_INTERVAL) == (3.0, 30.0)
        assert (s.WEAPON_MIN_HITS, s.WEAPON_ALERT_INTERVAL) == (4, 10.0)
        assert s.RETENTION_DAYS == 30
        assert s.API_TOKEN is None
        assert s.CORS_ORIGINS == ["http://127.0.0.1:5173", "http://localhost:5173"]
        assert (s.HOST, s.PORT, s.DEBUG) == ("127.0.0.1", 5001, False)
        assert (s.LOCAL_TZ, s.VERSION) == ("Asia/Kolkata", "2.0.0")


class TestEnvOverrides:
    def test_data_dir_is_expanded_and_absolute(self, load_settings, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = load_settings(CHANAKYA_DATA_DIR="relative/data")
        assert s.DATA_DIR == (tmp_path / "relative" / "data").resolve()
        assert s.DATA_DIR.is_absolute()
        assert s.DB_PATH == s.DATA_DIR / "chanakya.db"
        assert s.SNAPSHOTS_DIR == s.DATA_DIR / "snapshots"

        monkeypatch.setenv("HOME", str(tmp_path))
        s = load_settings(CHANAKYA_DATA_DIR="~/chanakya-data")
        assert s.DATA_DIR == (tmp_path / "chanakya-data").resolve()

    def test_cameras(self, load_settings):
        s = load_settings(CHANAKYA_CAMERAS=f"gate={SECRET_URL},demo=/clips/demo.mp4")
        assert s.CAMERAS == [
            {"id": "gate", "name": "GATE", "source": SECRET_URL},
            {"id": "demo", "name": "DEMO", "source": "/clips/demo.mp4"},
        ]

    def test_blank_cameras_keeps_the_default(self, load_settings):
        assert [c["id"] for c in load_settings(CHANAKYA_CAMERAS="  ").CAMERAS] == ["alpha", "bravo"]

    def test_bad_cameras_fail_loudly_without_leaking_the_source(self, load_settings):
        with pytest.raises(ValueError, match="CHANAKYA_CAMERAS") as excinfo:
            load_settings(CHANAKYA_CAMERAS=f"Gate={SECRET_URL}")
        assert "hunter2" not in str(excinfo.value)

    def test_api_token(self, load_settings):
        assert load_settings(CHANAKYA_API_TOKEN="a-long-enough-token").API_TOKEN == "a-long-enough-token"
        assert load_settings(CHANAKYA_API_TOKEN="").API_TOKEN is None

    def test_cors_origins(self, load_settings):
        s = load_settings(CHANAKYA_CORS_ORIGINS=" https://a.example , ,https://b.example,")
        assert s.CORS_ORIGINS == ["https://a.example", "https://b.example"]
        assert load_settings(CHANAKYA_CORS_ORIGINS=" , ").CORS_ORIGINS == [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]

    def test_host_and_port(self, load_settings):
        s = load_settings(CHANAKYA_HOST="0.0.0.0", CHANAKYA_PORT=" 8080 ")
        assert (s.HOST, s.PORT) == ("0.0.0.0", 8080)

    def test_bad_port_names_the_variable(self, load_settings):
        with pytest.raises(ValueError, match="CHANAKYA_PORT"):
            load_settings(CHANAKYA_PORT="http")

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", " Yes ", "on"])
    def test_debug_truthy(self, load_settings, value):
        assert load_settings(CHANAKYA_DEBUG=value).DEBUG is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "enabled", "2"])
    def test_debug_falsy(self, load_settings, value):
        assert load_settings(CHANAKYA_DEBUG=value).DEBUG is False


# --------------------------------------------------------------------------- #
# import-time behaviour
# --------------------------------------------------------------------------- #
class TestNoImportTimeWork:
    def test_import_creates_no_directories_and_ensure_dirs_does(self, load_settings, tmp_path):
        data_dir = tmp_path / "data"
        s = load_settings(CHANAKYA_DATA_DIR=str(data_dir))
        assert not data_dir.exists()

        s.ensure_dirs()
        for directory in (s.DATA_DIR, s.SNAPSHOTS_DIR, s.VIDEOS_DIR, s.REPORTS_DIR, s.KNOWN_FACES_DIR):
            assert directory.is_dir()
        assert sorted(p.name for p in data_dir.iterdir()) == [
            "known_faces",
            "reports",
            "snapshots",
            "videos",
        ]
        s.ensure_dirs()  # idempotent

    def test_ensure_dirs_reads_the_directories_at_call_time(self, load_settings, tmp_path):
        s = load_settings(CHANAKYA_DATA_DIR=str(tmp_path / "first"))
        s.SNAPSHOTS_DIR = tmp_path / "second" / "snapshots"
        s.ensure_dirs()
        assert (tmp_path / "second" / "snapshots").is_dir()

    def test_settings_source_contains_no_mkdir_outside_ensure_dirs(self):
        """v1 created Backend/data at import; guard against that coming back."""
        source = Path(settings.__file__).read_text(encoding="utf-8")
        assert source.count(".mkdir(") == 1
        assert not hasattr(settings, "LOGS_DIR")

    def test_core_modules_import_without_heavy_dependencies(self, tmp_path):
        """Contract import rule 3, checked in a clean interpreter."""
        code = (
            "import sys\n"
            "import config.settings, src.database_manager, src.zones, src.events, src.threat_assessor\n"
            "heavy = {'cv2', 'torch', 'ultralytics', 'face_recognition', 'PIL', 'dlib'}\n"
            "loaded = sorted(heavy & set(sys.modules))\n"
            "assert not loaded, loaded\n"
        )
        env = {**os.environ, "CHANAKYA_DATA_DIR": str(tmp_path / "data")}
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(settings.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "data").exists()
