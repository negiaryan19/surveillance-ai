"""Known-face database, recognition, enrollment and per-frame landmark lookup.

Design notes that are not obvious from the code:

* ``DLIB_LOCK`` serialises EVERY call into dlib. dlib's HOG detector is not
  re-entrant and releases the GIL, so two camera threads calling it on
  different-sized crops crash the whole process with SIGTRAP (reproduced
  during review). The lock is held per call, never across a rebuild or file
  I/O, so a camera thread waits at most ~15 ms.
* Known encodings are held as ONE immutable ``(encodings, names)`` pair that
  ``reload()`` replaces by reference, so a rebuild never blocks analysis and
  ``analyze`` never sees a half-updated list.
* Upload bytes are untrusted: a 400 KiB PNG can decode to 400+ MiB. They are
  sniffed and size-checked with Pillow before any pixel is decoded, and the
  stored file is a re-encoded JPEG (which also strips EXIF/GPS).
* ``remove()`` never builds a filesystem path from the caller's name; it
  rescans the folder and unlinks the files whose *display* name matches, so
  ``"."``, ``".."`` and friends can never reach the filesystem.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import os
import re
import threading
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("chanakya.face_recognizer")

DLIB_LOCK = threading.RLock()

ENCODING_DIM = 128
VALID_EXTENSIONS = (".png", ".jpg", ".jpeg")
NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9 -]{0,39}")
MAX_UPLOAD_BYTES = 5 * 2**20
MAX_UPLOAD_PIXELS = 25_000_000
ENROLL_MAX_SIDE = 1024
MAX_IMAGES_PER_PERSON = 10
MAX_IMAGES_TOTAL = 200
MIN_CROP_WIDTH = 40
UPSAMPLE_BELOW_WIDTH = 200
MIN_LANDMARK_BOX = 20


def canonical_name(raw: str) -> str:
    """Collapse runs of spaces/underscores and trim: ``"Aryan__Negi "`` → ``"Aryan Negi"``."""
    return re.sub(r"[ _]+", " ", str(raw or "")).strip()


@dataclass
class FaceResult:
    found: bool
    name: str = "Unknown"
    distance: float | None = None
    landmarks: dict | None = None
    face_bbox: tuple | None = None


class FaceRecognizer:
    def __init__(self, db_path=None, encoding_path=None, tolerance: float | None = None) -> None:
        from config import settings

        self.db_path = Path(db_path if db_path is not None else settings.KNOWN_FACES_DIR)
        self.encoding_path = Path(encoding_path if encoding_path is not None else settings.ENCODINGS_FILE)
        self.tolerance = float(settings.FACE_TOLERANCE if tolerance is None else tolerance)
        self._known: tuple[np.ndarray, tuple[str, ...]] = (np.zeros((0, ENCODING_DIM)), ())
        self._signature: dict | None = None
        self._state_lock = threading.Lock()
        self._warned_missing_lib = False
        self.reload()

    # ------------------------------------------------------------------ library
    def _lib(self):
        """Return the face_recognition module, or None (with one warning) if absent."""
        try:
            import face_recognition  # noqa: WPS433 - heavy, imported lazily on purpose

            return face_recognition
        except Exception:  # noqa: BLE001 - ImportError or a broken dlib build
            if not self._warned_missing_lib:
                log.warning("face_recognition is not available; identities will stay Unknown")
                self._warned_missing_lib = True
            return None

    # ------------------------------------------------------------------ scanning
    def _scan(self) -> list[tuple[str, Path]]:
        """(display name, image path) for every image, loose or in a person folder."""
        if not self.db_path.is_dir():
            return []
        found: list[tuple[str, Path]] = []
        for root, dirs, files in os.walk(self.db_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            root_path = Path(root)
            for file_name in files:
                if file_name.startswith(".") or not file_name.lower().endswith(VALID_EXTENSIONS):
                    continue
                if root_path == self.db_path:
                    name = canonical_name(Path(file_name).stem)
                else:
                    name = canonical_name(root_path.name)
                if name:
                    found.append((name, root_path / file_name))
        return sorted(found, key=lambda item: str(item[1]))

    def _signature_of(self, images: list[tuple[str, Path]]) -> dict:
        if not images:
            return {"count": 0, "latest_mtime": 0, "digest": ""}
        digest = hashlib.sha1(usedforsecurity=False)
        latest = 0.0
        for _, path in images:
            rel = str(path.relative_to(self.db_path))
            digest.update(rel.encode("utf-8", "replace"))
            with contextlib.suppress(OSError):  # a file removed mid-scan just changes the signature
                latest = max(latest, path.stat().st_mtime)
        return {"count": len(images), "latest_mtime": latest, "digest": digest.hexdigest()}

    # ------------------------------------------------------------------ cache
    def _load_cache(self, signature: dict) -> tuple[np.ndarray, tuple[str, ...]] | None:
        if not self.encoding_path.is_file():
            return None
        try:
            with np.load(self.encoding_path, allow_pickle=False) as data:
                if json.loads(str(data["signature"])) != signature:
                    return None
                encodings = np.asarray(data["encodings"], dtype=np.float64)
                names = tuple(str(n) for n in data["names"])
            if encodings.ndim != 2 or encodings.shape[1] != ENCODING_DIM or encodings.shape[0] != len(names):
                raise ValueError("cache shape mismatch")
            return encodings, names
        except Exception as exc:  # noqa: BLE001 - any corruption means rebuild
            log.warning("face cache unusable (%s); rebuilding", type(exc).__name__)
            return None

    def _write_cache(self, encodings: np.ndarray, names: tuple[str, ...], signature: dict) -> None:
        self.encoding_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.encoding_path.with_name(self.encoding_path.name + ".tmp")
        try:
            # np.savez appends ".npz" to a bare path; an open handle avoids that.
            with open(tmp, "wb") as fh:
                np.savez(
                    fh,
                    encodings=np.asarray(encodings, dtype=np.float64).reshape(-1, ENCODING_DIM),
                    names=np.array(list(names), dtype=str),
                    signature=np.array(json.dumps(signature)),
                )
            os.replace(tmp, self.encoding_path)
        except OSError:
            log.exception("could not write face cache")
            tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------ reload
    def reload(self) -> int:
        """Rescan the folder; rebuild encodings only when the folder changed."""
        images = self._scan()
        signature = self._signature_of(images)
        with self._state_lock:
            if self._signature == signature:
                return len(self._known[1])
        cached = self._load_cache(signature)
        if cached is None:
            cached = self._build(images)
            self._write_cache(cached[0], cached[1], signature)
            log.info("face database built: %d encodings", len(cached[1]))
        else:
            log.info("face database loaded from cache: %d encodings", len(cached[1]))
        with self._state_lock:
            self._known = cached
            self._signature = signature
        return len(cached[1])

    def _build(self, images: list[tuple[str, Path]]) -> tuple[np.ndarray, tuple[str, ...]]:
        lib = self._lib()
        encodings: list[np.ndarray] = []
        names: list[str] = []
        if lib is None:
            return np.zeros((0, ENCODING_DIM)), ()
        for name, path in images:
            try:
                rgb = _load_rgb(path)
                if rgb is None:
                    continue
                with DLIB_LOCK:
                    locations = lib.face_locations(rgb, number_of_times_to_upsample=1)
                    if not locations:
                        log.warning("no face found in %s", path.name)
                        continue
                    location = _largest(locations)
                    enc = lib.face_encodings(rgb, known_face_locations=[location])
                if enc:
                    encodings.append(np.asarray(enc[0], dtype=np.float64))
                    names.append(name)
            except Exception:  # noqa: BLE001 - one bad file must not stop the rebuild
                log.exception("could not encode %s", path.name)
        arr = np.vstack(encodings) if encodings else np.zeros((0, ENCODING_DIM))
        return arr, tuple(names)

    # ------------------------------------------------------------------ queries
    @property
    def known_names(self) -> list[str]:
        return list(self._known[1])

    def list_people(self) -> list[dict]:
        counts: dict[str, int] = {}
        for name, _ in self._scan():
            counts[name] = counts.get(name, 0) + 1
        return [{"name": n, "images": counts[n]} for n in sorted(counts, key=str.lower)]

    def analyze(self, frame_bgr, person_bbox) -> FaceResult:
        """Find, identify and landmark the face inside a person box (one HOG pass)."""
        lib = self._lib()
        if lib is None or frame_bgr is None:
            return FaceResult(found=False)
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in person_bbox)
        x1, x2 = max(0, x1), min(w, x2)
        y1 = max(0, y1)
        y2 = min(h, y1 + int((max(y2, y1) - y1) * 0.6) + 1)  # faces are in the top 60 %
        if x2 - x1 < MIN_CROP_WIDTH or y2 - y1 < MIN_CROP_WIDTH:
            return FaceResult(found=False)
        crop = np.ascontiguousarray(frame_bgr[y1:y2, x1:x2, ::-1])  # BGR -> RGB
        upsample = 2 if crop.shape[1] < UPSAMPLE_BELOW_WIDTH else 1  # small faces need it
        with DLIB_LOCK:
            locations = lib.face_locations(crop, number_of_times_to_upsample=upsample)
            if not locations:
                return FaceResult(found=False)
            top, right, bottom, left = _largest(locations)
            enc = lib.face_encodings(crop, known_face_locations=[(top, right, bottom, left)])
            marks = lib.face_landmarks(crop, face_locations=[(top, right, bottom, left)])
        face_bbox = (x1 + left, y1 + top, x1 + right, y1 + bottom)
        landmarks = _offset_landmarks(marks[0], x1, y1) if marks else None
        name, distance = "Unknown", None
        if enc:
            name, distance = self._match(np.asarray(enc[0], dtype=np.float64), lib)
        return FaceResult(found=True, name=name, distance=distance, landmarks=landmarks, face_bbox=face_bbox)

    def _match(self, encoding: np.ndarray, lib) -> tuple[str, float | None]:
        encodings, names = self._known  # one read; reload() swaps atomically
        if len(names) == 0:
            return "Unknown", None
        distances = lib.face_distance(encodings, encoding)
        idx = int(np.argmin(distances))
        best = float(distances[idx])
        if best <= self.tolerance:
            return names[idx], best
        return "Unknown", best

    def landmarks_at(self, frame_bgr, face_bbox) -> dict | None:
        """Landmarks for a face whose location is already known (~0.5 ms, no HOG)."""
        lib = self._lib()
        if lib is None or frame_bgr is None or face_bbox is None:
            return None
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in face_bbox)
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        if x2 - x1 < MIN_LANDMARK_BOX or y2 - y1 < MIN_LANDMARK_BOX:
            return None
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        with DLIB_LOCK:
            # dlib css order is (top, right, bottom, left); the wrong order
            # silently returns garbage landmarks right at the blink threshold.
            marks = lib.face_landmarks(rgb, face_locations=[(y1, x2, y2, x1)])
        return marks[0] if marks else None

    def identify(self, frame, bbox) -> str:
        return self.analyze(frame, bbox).name

    # ------------------------------------------------------------------ enrollment
    def enroll(self, name: str, image_bytes: bytes) -> dict:
        display = canonical_name(name)
        if not NAME_RE.fullmatch(display):
            raise ValueError("name must start with a letter and use only letters, digits, spaces or hyphens (max 40)")
        display = self._existing_spelling(display)
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError("image larger than 5 MB")

        rgb = _decode_upload(image_bytes)
        lib = self._lib()
        if lib is None:
            raise ValueError("face recognition is not available on this server")
        with DLIB_LOCK:
            locations = lib.face_locations(rgb, number_of_times_to_upsample=1)
        if len(locations) != 1:
            raise ValueError(f"expected exactly one face, found {len(locations)}")
        with DLIB_LOCK:
            enc = lib.face_encodings(rgb, known_face_locations=[locations[0]])
        if not enc:
            raise ValueError("could not encode the face")

        people = {p["name"]: p["images"] for p in self.list_people()}
        if people.get(display, 0) >= MAX_IMAGES_PER_PERSON:
            raise ValueError(f"{display} already has {MAX_IMAGES_PER_PERSON} images")
        if sum(people.values()) >= MAX_IMAGES_TOTAL:
            raise ValueError("face database is full")

        folder = self.db_path / display.replace(" ", "_")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{uuid.uuid4().hex}.jpg"
        _save_jpeg(rgb, target)

        # Append the encoding we already have instead of re-encoding everything.
        with self._state_lock:
            encodings, names = self._known
            new = (np.vstack([encodings, np.asarray(enc[0], dtype=np.float64)[None, :]]), names + (display,))
            signature = self._signature_of(self._scan())
            self._known = new
            self._signature = signature
        self._write_cache(new[0], new[1], signature)
        return {"name": display, "images": people.get(display, 0) + 1}

    def _existing_spelling(self, display: str) -> str:
        for person in self.list_people():
            if person["name"].lower() == display.lower():
                return person["name"]
        return display

    def remove(self, name: str) -> bool:
        """Delete every image of one person, matching by display name only."""
        target = canonical_name(name)
        if not target:
            return False
        victims = [path for shown, path in self._scan() if shown == target]
        if not victims:
            return False
        folders: set[Path] = set()
        for path in victims:
            try:
                path.unlink()
            except OSError:
                log.exception("could not delete %s", path.name)
            if path.parent != self.db_path:
                folders.add(path.parent)
        for folder in folders:
            try:
                if folder.parent == self.db_path and folder != self.db_path and not any(folder.iterdir()):
                    folder.rmdir()
            except OSError:
                pass
        self.reload()
        return True


# ---------------------------------------------------------------------- helpers
def _largest(locations):
    return max(locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))


def _offset_landmarks(marks: dict, dx: int, dy: int) -> dict:
    return {key: [(int(x) + dx, int(y) + dy) for x, y in pts] for key, pts in marks.items()}


def _load_rgb(path: Path):
    """Decode a stored image via Pillow (bounded), returning an RGB uint8 array."""
    from PIL import Image, ImageOps

    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        image.thumbnail((ENROLL_MAX_SIDE, ENROLL_MAX_SIDE))
        return np.ascontiguousarray(np.asarray(image))


def _decode_upload(image_bytes: bytes):
    """Sniff, bound and decode untrusted bytes; never hand them to cv2.imdecode."""
    from PIL import Image, ImageOps

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(image_bytes))
            if im.format not in ("JPEG", "PNG"):
                raise ValueError("only JPEG and PNG images are accepted")
            if im.width * im.height > MAX_UPLOAD_PIXELS:
                raise ValueError("image dimensions too large")
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((ENROLL_MAX_SIDE, ENROLL_MAX_SIDE))
            return np.ascontiguousarray(np.asarray(im))
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types on bad input
        raise ValueError("unsupported or too large image") from exc


def _save_jpeg(rgb: np.ndarray, target: Path) -> None:
    from PIL import Image

    Image.fromarray(rgb).save(target, format="JPEG", quality=90)
