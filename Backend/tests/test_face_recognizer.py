"""FaceRecognizer logic with a fake dlib (default run) plus real-dlib tests marked slow."""

import io
import json
import sys
import threading

import numpy as np
import pytest
from PIL import Image

from src import face_recognizer as fr
from src.face_recognizer import FaceRecognizer, FaceResult, canonical_name

ENC = 128


def _enc(seed: float):
    v = np.zeros(ENC)
    v[0] = seed
    return v


class FakeDlib:
    """Records calls; `faces` maps an image shape -> list of css boxes to report."""

    def __init__(self):
        self.calls = []
        self.locations = [(10, 60, 60, 10)]  # top, right, bottom, left
        self.encoding = _enc(0.1)
        self.landmarks = {"left_eye": [(0, 0)] * 6, "right_eye": [(0, 0)] * 6}

    def face_locations(self, img, number_of_times_to_upsample=1, model="hog"):
        self.calls.append(("locations", img.shape, number_of_times_to_upsample))
        return list(self.locations)

    def face_encodings(self, img, known_face_locations=None, num_jitters=1, model="small"):
        self.calls.append(("encodings", known_face_locations))
        return [self.encoding] if known_face_locations else []

    def face_landmarks(self, img, face_locations=None, model="large"):
        self.calls.append(("landmarks", face_locations))
        return [dict(self.landmarks)] if face_locations else []

    @staticmethod
    def face_distance(known, enc):
        if len(known) == 0:
            return np.zeros(0)
        return np.linalg.norm(np.asarray(known) - enc, axis=1)


@pytest.fixture
def dlib(monkeypatch):
    fake = FakeDlib()
    monkeypatch.setitem(sys.modules, "face_recognition", fake)
    return fake


@pytest.fixture
def db(tmp_path):
    return tmp_path / "faces", tmp_path / "enc.npz"


def png_bytes(size=(200, 200), color=(120, 90, 60), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def make_person(root, name, count=1):
    folder = root / name.replace(" ", "_")
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (folder / f"{i}.jpg").write_bytes(png_bytes(fmt="JPEG"))


def frame(w=640, h=480):
    return np.full((h, w, 3), 90, np.uint8)


# --------------------------------------------------------------------- names
@pytest.mark.parametrize(
    "raw,expected",
    [("Aryan_Negi", "Aryan Negi"), ("  Aryan   Negi ", "Aryan Negi"), ("a__b", "a b"), ("", ""), ("Aryan\n", "Aryan")],
)
def test_canonical_name(raw, expected):
    assert canonical_name(raw) == expected


def test_scan_maps_loose_files_and_folders(dlib, db):
    root, enc = db
    root.mkdir()
    (root / "Aryan_Negi.jpg").write_bytes(png_bytes(fmt="JPEG"))
    make_person(root, "Student One", 2)
    (root / ".hidden.jpg").write_bytes(b"x")
    r = FaceRecognizer(root, enc)
    assert r.list_people() == [{"name": "Aryan Negi", "images": 1}, {"name": "Student One", "images": 2}]
    assert r.known_names == ["Aryan Negi", "Student One", "Student One"]


# --------------------------------------------------------------------- cache
def test_cache_round_trip_and_atomic_write(dlib, db):
    root, enc = db
    make_person(root, "Aryan", 1)
    FaceRecognizer(root, enc)
    assert enc.is_file() and not enc.with_name(enc.name + ".tmp").exists()
    with np.load(enc, allow_pickle=False) as data:
        assert data["encodings"].shape == (1, ENC) and list(data["names"]) == ["Aryan"]
        json.loads(str(data["signature"]))
    dlib.calls.clear()
    r = FaceRecognizer(root, enc)  # second construction uses the cache
    assert r.known_names == ["Aryan"] and not [c for c in dlib.calls if c[0] == "encodings"]


def test_corrupt_cache_triggers_rebuild(dlib, db):
    root, enc = db
    make_person(root, "Aryan", 1)
    enc.write_bytes(b"garbage")
    r = FaceRecognizer(root, enc)
    assert r.known_names == ["Aryan"]
    np.load(enc, allow_pickle=False).close()


def test_empty_database_writes_empty_shapes(dlib, db):
    root, enc = db
    r = FaceRecognizer(root, enc)
    assert r.known_names == []
    with np.load(enc, allow_pickle=False) as data:
        assert data["encodings"].shape == (0, ENC) and data["names"].shape == (0,)


def test_pickle_is_never_imported():
    assert "pickle" not in fr.__dict__


# --------------------------------------------------------------------- analyze
def test_analyze_crops_top_60_percent_and_picks_upsample(dlib, db):
    r = FaceRecognizer(*db)
    res = r.analyze(frame(), (100, 100, 250, 400))  # 150 px wide -> upsample 2
    assert res.found and res.name == "Unknown"  # empty known set, no argmin crash
    shape, ups = dlib.calls[0][1], dlib.calls[0][2]
    assert shape[1] == 150 and shape[0] == int(300 * 0.6) + 1 and ups == 2
    assert res.face_bbox == (110, 110, 160, 160)  # crop offset + css box
    dlib.calls.clear()
    r.analyze(frame(), (0, 0, 300, 400))
    assert dlib.calls[0][2] == 1


def test_analyze_skips_tiny_crops_without_dlib(dlib, db):
    r = FaceRecognizer(*db)
    assert r.analyze(frame(), (0, 0, 30, 100)) == FaceResult(found=False)
    assert dlib.calls == []


def test_analyze_best_match_within_tolerance(dlib, db):
    root, enc = db
    make_person(root, "Far", 1)
    make_person(root, "Near", 1)
    encs = iter([_enc(0.9), _enc(0.15)])  # build order: Far then Near (sorted by path)
    dlib.encoding = None
    dlib.face_encodings = lambda img, known_face_locations=None, **k: [next(encs)] if known_face_locations else []
    r = FaceRecognizer(root, enc, tolerance=0.6)
    dlib.face_encodings = lambda img, known_face_locations=None, **k: [_enc(0.1)]
    res = r.analyze(frame(), (0, 0, 300, 400))
    assert res.name == "Near" and res.distance == pytest.approx(0.05)
    r.tolerance = 0.01
    assert r.analyze(frame(), (0, 0, 300, 400)).name == "Unknown"


def test_analyze_takes_largest_face(dlib, db):
    dlib.locations = [(10, 30, 30, 10), (50, 150, 150, 50)]
    r = FaceRecognizer(*db)
    res = r.analyze(frame(), (0, 0, 300, 400))
    assert res.face_bbox == (50, 50, 150, 150)


def test_landmarks_at_uses_css_order_and_clamps(dlib, db):
    r = FaceRecognizer(*db)
    marks = r.landmarks_at(frame(), (100, 50, 180, 130))
    assert marks is not None
    assert dlib.calls[-1] == ("landmarks", [(50, 180, 130, 100)])  # top, right, bottom, left
    assert r.landmarks_at(frame(), (0, 0, 10, 10)) is None  # below 20 px
    assert r.landmarks_at(frame(), (600, 400, 700, 500)) is not None  # clamped to the frame


def test_missing_library_returns_not_found(monkeypatch, db):
    monkeypatch.setitem(sys.modules, "face_recognition", None)
    r = FaceRecognizer(*db)
    assert r.analyze(frame(), (0, 0, 300, 400)).found is False


# --------------------------------------------------------------------- enroll
def test_enroll_saves_reencoded_jpeg_and_updates_state(dlib, db):
    root, enc = db
    r = FaceRecognizer(root, enc)
    out = r.enroll("Aryan  Negi", png_bytes())
    assert out == {"name": "Aryan Negi", "images": 1}
    files = list((root / "Aryan_Negi").iterdir())
    assert len(files) == 1 and files[0].suffix == ".jpg"
    with Image.open(files[0]) as im:
        assert im.format == "JPEG"
    assert r.known_names == ["Aryan Negi"]
    assert r.list_people() == [{"name": "Aryan Negi", "images": 1}]
    # the second image for the same person reuses the folder (case-insensitive)
    assert r.enroll("aryan negi", png_bytes()) == {"name": "Aryan Negi", "images": 2}


@pytest.mark.parametrize("bad", ["", "1abc", "a/b", "x" * 41, "Ary\nan", ".", ".."])
def test_enroll_rejects_bad_names(dlib, db, bad):
    r = FaceRecognizer(*db)
    with pytest.raises(ValueError):
        r.enroll(bad, png_bytes())


def test_enroll_rejects_bad_images(dlib, db):
    r = FaceRecognizer(*db)
    with pytest.raises(ValueError, match="5 MB"):
        r.enroll("Aryan", b"x" * (5 * 2**20 + 1))
    with pytest.raises(ValueError):
        r.enroll("Aryan", b"not an image")
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="GIF")
    with pytest.raises(ValueError, match="JPEG and PNG"):
        r.enroll("Aryan", buf.getvalue())
    # a decompression bomb: tiny on the wire, huge in pixels
    buf = io.BytesIO()
    Image.new("1", (6000, 6000)).save(buf, format="PNG")
    with pytest.raises(ValueError):
        r.enroll("Aryan", buf.getvalue())
    assert list(r.db_path.glob("**/*.jpg")) == []


def test_enroll_requires_exactly_one_face(dlib, db):
    r = FaceRecognizer(*db)
    dlib.locations = []
    with pytest.raises(ValueError, match="found 0"):
        r.enroll("Aryan", png_bytes())
    dlib.locations = [(1, 2, 3, 0), (5, 6, 7, 4)]
    with pytest.raises(ValueError, match="found 2"):
        r.enroll("Aryan", png_bytes())


def test_enroll_limits_per_person(dlib, db):
    r = FaceRecognizer(*db)
    for _ in range(fr.MAX_IMAGES_PER_PERSON):
        r.enroll("Aryan", png_bytes())
    with pytest.raises(ValueError, match="already has"):
        r.enroll("Aryan", png_bytes())


# --------------------------------------------------------------------- remove
@pytest.mark.parametrize("name", [".", "..", "", "a/..", "../faces", "Nobody"])
def test_remove_never_touches_paths_from_names(dlib, db, name):
    root, enc = db
    make_person(root, "Aryan", 2)
    r = FaceRecognizer(root, enc)
    assert r.remove(name) is False
    assert len(list(root.glob("**/*.jpg"))) == 2 and root.is_dir()


def test_remove_deletes_only_that_person(dlib, db):
    root, enc = db
    make_person(root, "Aryan", 2)
    make_person(root, "Bob", 1)
    (root / "Loose_Guy.jpg").write_bytes(png_bytes(fmt="JPEG"))
    r = FaceRecognizer(root, enc)
    assert r.remove("aryan ") is False  # exact display-name match only
    assert r.remove("Aryan") is True
    assert not (root / "Aryan").exists() and (root / "Bob").is_dir()
    assert r.remove("Loose Guy") is True and not (root / "Loose_Guy.jpg").exists()
    assert r.known_names == ["Bob"]


def test_enroll_trailing_space_round_trips_with_remove(dlib, db):
    r = FaceRecognizer(*db)
    r.enroll("Aryan ", png_bytes())
    assert r.remove("Aryan") is True


# --------------------------------------------------------------------- real dlib
@pytest.mark.slow
def test_dlib_lock_survives_concurrent_analyze(db):
    import importlib

    lib = pytest.importorskip("face_recognition")
    assert sys.modules["face_recognition"] is lib
    import cv2

    asset = importlib.import_module("ultralytics").__file__.replace("__init__.py", "assets/zidane.jpg")
    img = cv2.imread(asset)
    assert img is not None
    r = FaceRecognizer(*db)
    errors = []

    def worker(scale):
        try:
            f = cv2.resize(img, None, fx=scale, fy=scale)
            h, w = f.shape[:2]
            for _ in range(40):
                r.analyze(f, (0, 0, w, h))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in (0.5, 0.75, 1.0)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


@pytest.mark.slow
def test_real_enroll_and_recognise(db):
    import importlib

    pytest.importorskip("face_recognition")
    import cv2

    asset = importlib.import_module("ultralytics").__file__.replace("__init__.py", "assets/zidane.jpg")
    img = cv2.imread(asset)
    face = img[40:360, 800:1160]  # the right-hand person's head (dlib finds it at ~(116,906)-(270,1061))
    ok, buf = cv2.imencode(".jpg", face)
    r = FaceRecognizer(*db)
    assert r.enroll("Zizou", buf.tobytes())["images"] == 1
    res = r.analyze(img, (780, 20, 1200, 720))
    assert res.found and res.name == "Zizou" and res.landmarks is not None
