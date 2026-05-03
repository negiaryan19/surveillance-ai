"""
Project Settings
----------------
All configuration values are stored here.
"""

import os
from pathlib import Path

# ========================================
# Project Root Paths
# ========================================
BASE_DIR = Path(__file__).resolve().parent.parent

# Folder paths
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
LOGS_DIR = DATA_DIR / "logs"
SOUNDS_DIR = BASE_DIR / "sounds"

# File paths
MODEL_PATH = str(MODELS_DIR / "yolov8n.pt")
LOG_FILE = str(LOGS_DIR / "alerts.log")
ALERT_SOUND = str(SOUNDS_DIR / "alert.mp3")

# Make sure folders exist
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ========================================
# Detection Settings
# ========================================
ZONE = (0, 0, 1000, 800)         # (x1, y1, x2, y2)
LOITER_TIME = 2                   # seconds
ALERT_COOLDOWN = 10               # seconds between alerts
PERSON_CLASS_ID = 0               # YOLO class for person
CONFIDENCE_LIMIT = 0.65           # Minimum confidence


# ========================================
# Camera Settings
# ========================================
CAMERA_INDEX = 0
USE_AVFOUNDATION = True           # True for Mac, False for others