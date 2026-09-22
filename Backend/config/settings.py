"""Project Chanakya configuration: constants plus environment overrides.

The ONLY import-time side effect is ``load_dotenv(BASE_DIR / ".env")``. In
particular no directory is created here -- importing this module from a test,
a tool or a CI job must never touch the filesystem. Call :func:`ensure_dirs`
from the process entry point instead.

Misconfiguration (a malformed ``CHANAKYA_CAMERAS`` or ``CHANAKYA_PORT``) raises
``ValueError`` at import: for a surveillance system, silently falling back to
the default webcams when the operator asked for an RTSP camera is worse than
refusing to start. Error messages never contain a camera source, because
sources routinely embed credentials (``rtsp://user:password@host/...``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_CAMERA_ID_RE = re.compile(r"[a-z0-9_-]{1,32}")
_DIGITS_RE = re.compile(r"[0-9]+")
# "default" names the fallback zone set (src.zones); a camera with that id
# would make the two indistinguishable in the zones file and the zones API.
_RESERVED_CAMERA_IDS = frozenset({"default"})


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable; unset or blank keeps ``default``."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in _TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable; unset or blank keeps ``default``."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _env_list(name: str, default: list[str]) -> list[str]:
    """Parse a comma-separated environment variable, dropping blank items."""
    value = os.getenv(name)
    if value is None:
        return list(default)
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or list(default)


def _env_data_dir(default: Path) -> Path:
    """``CHANAKYA_DATA_DIR`` as an absolute path, so stored paths stay absolute."""
    value = os.getenv("CHANAKYA_DATA_DIR")
    if value is None or not value.strip():
        return default
    return Path(value.strip()).expanduser().resolve()


def parse_cameras(spec: str) -> list[dict]:
    """Parse ``"alpha=0,gate=rtsp://user:pw@host/s?x=1,demo=/path/clip.mp4"``.

    Items are separated by ``,`` (a literal comma inside a URL must be written
    ``%2C``). Each item is split on its FIRST ``=`` only, because RTSP/HTTP
    URLs contain ``=`` in their query strings. A digit-only source becomes an
    ``int`` (a local camera index); anything else is kept verbatim.

    Raises ``ValueError`` for malformed input. The message names a camera id
    only once that id has been validated, and otherwise refers to the entry by
    position: an item written without ``id=`` would put the URL -- password
    included -- where the id is expected, so an unvalidated id is never echoed.
    """
    cameras: list[dict] = []
    seen: set[str] = set()
    for position, raw_item in enumerate(spec.split(","), start=1):
        item = raw_item.strip()
        if not item:
            continue  # tolerate "a=0," and "a=0,,b=1"
        cam_id, separator, source = item.partition("=")
        cam_id, source = cam_id.strip(), source.strip()
        if not _CAMERA_ID_RE.fullmatch(cam_id):
            raise ValueError(
                f"camera entry #{position}: expected '<id>=<source>' with an id "
                "of 1-32 characters from a-z, 0-9, '_' and '-'"
            )
        if cam_id in _RESERVED_CAMERA_IDS:
            raise ValueError(f"camera id '{cam_id}' is reserved")
        if not separator or not source:
            raise ValueError(f"camera '{cam_id}' has no source")
        if cam_id in seen:
            raise ValueError(f"duplicate camera id '{cam_id}'")
        seen.add(cam_id)
        cameras.append(
            {
                "id": cam_id,
                "name": cam_id.upper(),
                "source": int(source) if _DIGITS_RE.fullmatch(source) else source,
            }
        )
    if not cameras:
        raise ValueError("camera specification defines no cameras")
    return cameras


def _env_cameras(default: list[dict]) -> list[dict]:
    """``CHANAKYA_CAMERAS`` parsed, or a copy of ``default`` when unset/blank."""
    spec = os.getenv("CHANAKYA_CAMERAS")
    if spec is None or not spec.strip():
        return [dict(camera) for camera in default]
    try:
        return parse_cameras(spec)
    except ValueError as exc:
        raise ValueError(f"CHANAKYA_CAMERAS: {exc}") from None


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
DATA_DIR = _env_data_dir(BASE_DIR / "database")
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
VIDEOS_DIR = DATA_DIR / "videos"
REPORTS_DIR = DATA_DIR / "reports"
KNOWN_FACES_DIR = DATA_DIR / "known_faces"
ENCODINGS_FILE = DATA_DIR / "face_encodings.npz"
DB_PATH = DATA_DIR / "chanakya.db"
ZONES_FILE = DATA_DIR / "zones.json"
KEY_FILE = DATA_DIR / "secret.key"
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
MODEL_PATH = str(BASE_DIR / "models" / "yolov8n.pt")
POSE_MODEL_PATH = str(BASE_DIR / "yolov8n-pose.pt")

# --------------------------------------------------------------------------
# Video pipeline
# --------------------------------------------------------------------------
FRAME_WIDTH, FRAME_HEIGHT = 640, 480
JPEG_QUALITY = 80
CAMERAS: list[dict] = _env_cameras(
    [
        {"id": "alpha", "name": "ALPHA", "source": 0},
        {"id": "bravo", "name": "BRAVO", "source": 1},
    ]
)

# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------
THREAT_CLASSES = {0: "Person", 2: "Car", 3: "Motorcycle", 16: "Dog", 43: "Weapon (Knife)"}
CONFIDENCE_LIMIT = 0.65
CLASS_CONFIDENCE = {43: 0.35}  # knives are small and low-confidence on a nano model
HEAVY_EVERY_N_FRAMES = 5
POSE_EVERY_N_FRAMES = 2

# --------------------------------------------------------------------------
# Identity and liveness
# --------------------------------------------------------------------------
FACE_TOLERANCE = 0.6
EAR_THRESHOLD = 0.22
LIVENESS_TTL = 30.0
LIVENESS_GRACE = 15.0
LIVENESS_MAX_VERIFY = 45.0

# --------------------------------------------------------------------------
# Behaviour (speeds are body-heights per second)
# --------------------------------------------------------------------------
LOITER_SECONDS = 10.0
TRACK_MAX_AGE = 5.0
PRONE_MIN_SECONDS = 1.5
RUN_SPEED_BH = 2.0
ERRATIC_SPEED_BH = 1.2

# --------------------------------------------------------------------------
# Alerting
# --------------------------------------------------------------------------
ALERT_MIN_SCORE = 70
ALERT_MIN_TRACK_AGE = 2.0
ALERT_TRACK_COOLDOWN = 60.0
ALERT_ESCALATION_DELTA = 15
ALERT_CAMERA_MIN_INTERVAL = 3.0
ALERT_NOTIFY_MIN_INTERVAL = 30.0
WEAPON_MIN_HITS = 4
WEAPON_ALERT_INTERVAL = 10.0

RETENTION_DAYS = 30  # 0 disables retention

# --------------------------------------------------------------------------
# API server
# --------------------------------------------------------------------------
API_TOKEN = os.getenv("CHANAKYA_API_TOKEN") or None
CORS_ORIGINS = _env_list("CHANAKYA_CORS_ORIGINS", ["http://127.0.0.1:5173", "http://localhost:5173"])
HOST = os.getenv("CHANAKYA_HOST") or "127.0.0.1"
PORT = _env_int("CHANAKYA_PORT", 5001)
DEBUG = _env_bool("CHANAKYA_DEBUG", False)

LOCAL_TZ = "Asia/Kolkata"
VERSION = "2.0.0"


def ensure_dirs() -> None:
    """Create every data directory (``mkdir -p``).

    Called by ``engine.start()`` / ``main()``, never at import. The directory
    names are read at call time so a process that re-points ``DATA_DIR`` and
    friends before starting gets the directories it asked for.
    """
    for directory in (DATA_DIR, SNAPSHOTS_DIR, VIDEOS_DIR, REPORTS_DIR, KNOWN_FACES_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)


def _resolve_from_base(path) -> Path:
    """Resolve ``path`` (symlinks included), anchoring relative paths at BASE_DIR.

    The CWD is deliberately ignored: the server can be launched from anywhere,
    and a stored path must not change meaning with the launch directory.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return candidate.resolve()


def safe_child(path, root) -> Path | None:
    """Return the resolved ``path`` iff it is an existing file strictly inside ``root``.

    This is the ONE path-containment check of the project (incident
    serialisation, the snapshot/clip routes and retention all use it).
    Both sides are fully resolved first, so ``..`` segments and symlinks that
    point outside ``root`` are rejected, and containment is decided on path
    components -- never ``str.startswith``, which would accept the sibling
    directory ``snapshots_evil/`` for the root ``snapshots/``.
    """
    if not path or not root:
        return None
    try:
        resolved_path = _resolve_from_base(path)
        resolved_root = _resolve_from_base(root)
        if resolved_path != resolved_root and resolved_path.is_relative_to(resolved_root) and resolved_path.is_file():
            return resolved_path
    except (OSError, RuntimeError, TypeError, ValueError):
        # Unresolvable input (embedded NUL, symlink loop, wrong type) is simply
        # "not a safe child"; callers turn None into a 404.
        return None
    return None
