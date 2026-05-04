"""
AI Surveillance System - Command Center (Phase 3.5)
---------------------------------------------------
Updates: Multi-Class, Face ID, Anomaly Detection + 🌙 NIGHT MODE + 🛡️ ANTI-SPOOFING (Liveness)
"""

import sys
import os
import cv2
import time
import numpy as np
import threading
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from src.smart_alert import send_alert_to_telegram
from src.shared_state import system_state
from src.telegram_bot import run_telegram_bot
from src.tracker import BehaviorTracker
from src.predictor import MovementPredictor
from src.zones import ZoneManager
from src.video_recorder import VideoRecorder 
from src.face_recognizer import FaceRecognizer
from src.anomaly_detector import AnomalyDetector
from src.night_vision import NightVision
# NAYA IMPORT: Liveness Detector
from src.liveness_detector import LivenessDetector

from config.settings import (
    MODEL_PATH, LOITER_TIME, ALERT_COOLDOWN,
    PERSON_CLASS_ID, CONFIDENCE_LIMIT, CAMERA_INDEX, USE_AVFOUNDATION
)

REAL_SNAPSHOTS_DIR = BASE_DIR / "database" / "snapshots"
REAL_VIDEOS_DIR = BASE_DIR / "database" / "videos"
KNOWN_FACES_DIR = BASE_DIR / "database" / "known_faces"
ENCODINGS_FILE = BASE_DIR / "database" / "face_encodings.pkl"

print("🚀 Initializing Phase 3.5: Autonomous Defense, Night Vision & Anti-Spoofing...")
model = YOLO(MODEL_PATH)
camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION if USE_AVFOUNDATION else None)

target_width, target_height = 640, 480

tracker = BehaviorTracker(max_disappeared=40)
predictor = MovementPredictor()
zone_manager = ZoneManager()
recorder = VideoRecorder(output_dir=REAL_VIDEOS_DIR)
face_id = FaceRecognizer(str(KNOWN_FACES_DIR), str(ENCODINGS_FILE))
anomaly_detector = AnomalyDetector()

# Initialize Night Vision & Liveness
nv = NightVision(threshold=85)
liveness_detector = LivenessDetector()

THREAT_CLASSES = {
    0: {"name": "Person", "color": (0, 255, 255)},
    1: {"name": "Bicycle", "color": (255, 255, 0)},
    2: {"name": "Car", "color": (0, 0, 255)},
    3: {"name": "Motorcycle", "color": (0, 0, 255)},
    16: {"name": "Dog", "color": (0, 255, 0)}
}

heatmap_accumulation = np.zeros((target_height, target_width), dtype=np.float32)
last_alert_time = 0
loiter_timers = {} 
frame_count = 0

threading.Thread(target=run_telegram_bot, daemon=True).start()

def async_alert(report, path, zone_level):
    send_alert_to_telegram(report, path)
    os.system(f'say -v Samantha "Alert. {report} in {zone_level}" &')

print("✅ System ONLINE | Anomaly, Night Vision & Liveness Active")

try:
    while True:
        success, raw_frame = camera.read()
        if not success: break
        frame_count += 1
        
        # 1. Resize Frame
        frame = cv2.resize(raw_frame, (target_width, target_height))

        # 🌙 Phase 3.4: Auto Night Mode Detection & Enhancement
        is_night_active = False
        if nv.is_low_light(frame):
            frame = nv.enhance(frame)
            is_night_active = True

        # 🛡️ ANTI-SPOOFING: Liveness Check (Run on every frame)
        is_live, blinks = liveness_detector.check_liveness(frame)
        cv2.putText(frame, f"Blinks: {blinks}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        if frame_count % 5 == 0:
            recorder.update(frame)
            system_state.update_frame(frame)
            
            detections = model(frame, verbose=False)
            current_centroids = []
            bbox_dict = {} 
            
            for detection in detections:
                for box in detection.boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    
                    if class_id in THREAT_CLASSES and confidence > CONFIDENCE_LIMIT:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        threat_info = THREAT_CLASSES[class_id]
                        label = f"{threat_info['name']} {confidence:.2f}"
                        box_color = threat_info["color"]
                        is_authorized = False

                        # 🧠 MILITARY-GRADE LOGIC: Face ID + Liveness Check
                        if class_id == 0:
                            identity = face_id.identify(frame, (x1, y1, x2, y2))
                            if identity != "Unknown" and identity is not None:
                                if is_live:
                                    # Real Person + Authorized
                                    label = f"✅ AUTH: {identity}"
                                    box_color = (0, 255, 0)
                                    is_authorized = True
                                else:
                                    # Shakal match hui par Blink nahi kiya (Phone Spoofing)
                                    label = f"⚠️ SPOOF: {identity}"
                                    box_color = (0, 165, 255) 
                                    is_authorized = False # Block the intruder!
                            else:
                                # Shakal hi match nahi hui
                                label = "🚨 INTRUDER"
                                box_color = (0, 0, 255)

                        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                        cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

                        if not is_authorized:
                            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                            current_centroids.append((cx, cy))
                            bbox_dict[(cx, cy)] = (x1, y1, x2, y2)

            tracked_objects = tracker.update(current_centroids)
            is_someone_in_zone = False
            highest_zone_time = 0
            primary_threat_id = None
            primary_zone_level = "UNKNOWN"
            anomaly_alert_triggered = False

            for (obj_id, centroid) in tracked_objects.items():
                cx, cy = centroid
                
                if centroid in bbox_dict:
                    is_anomaly, anomaly_type, severity = anomaly_detector.analyze(obj_id, bbox_dict[centroid], centroid)
                    if is_anomaly:
                        cv2.putText(frame, f"🚨 {anomaly_type}!", (cx - 50, cy + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                        if severity == "HIGH" and (time.time() - last_alert_time >= 30):
                            last_alert_time = time.time()
                            snap_path = str(REAL_SNAPSHOTS_DIR / f"anomaly_{anomaly_type.replace(' ', '_')}_{obj_id}.jpg")
                            cv2.imwrite(snap_path, frame)
                            threading.Thread(target=async_alert, args=(anomaly_type, snap_path, "Sector")).start()
                            anomaly_alert_triggered = True

                if not anomaly_alert_triggered:
                    predictor.update(obj_id, cx, cy)
                    if 0 <= cy < target_height and 0 <= cx < target_width:
                        cv2.circle(heatmap_accumulation, (cx, cy), 15, (1), -1)
                    
                    current_zone = zone_manager.get_zone_for_point(cx, cy)
                    if current_zone and current_zone.level != "SAFE":
                        is_someone_in_zone = True
                        if obj_id not in loiter_timers: loiter_timers[obj_id] = time.time()
                        time_in_zone = time.time() - loiter_timers[obj_id]
                        if time_in_zone > highest_zone_time:
                            highest_zone_time = time_in_zone
                            primary_threat_id = obj_id
                            primary_zone_level = current_zone.level
                        
                        color = (0, 0, 255) if current_zone.level == "CRITICAL" else (0, 165, 255)
                        cv2.circle(frame, (cx, cy), 5, color, -1)
                    else:
                        if obj_id in loiter_timers: del loiter_timers[obj_id]
                        cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)

            if is_someone_in_zone and highest_zone_time >= LOITER_TIME and not anomaly_alert_triggered:
                if time.time() - last_alert_time >= ALERT_COOLDOWN:
                    last_alert_time = time.time()
                    recorder.trigger(prefix=f"incident_ID{primary_threat_id}")
                    snap_path = str(REAL_SNAPSHOTS_DIR / f"alert_ID{primary_threat_id}.jpg")
                    cv2.imwrite(snap_path, frame)
                    if not system_state.is_paused():
                        threading.Thread(target=async_alert, args=("Intruder Detected", snap_path, primary_zone_level)).start()

        # UI Overlay
        zone_manager.draw_all_zones(frame, cv2)
        if is_night_active:
            cv2.putText(frame, "🌙 NIGHT MODE: ACTIVE", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        cv2.putText(frame, f"STATUS: ACTIVE | FPS: 15+", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("AI Surveillance - Core Command", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"): break

except Exception as e:
    print(f"⚠️ Error: {e}")
finally:
    camera.release()
    cv2.destroyAllWindows()
    print("✅ System Offline.")