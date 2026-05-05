"""
AI Surveillance System - Command Center (Phase 3 Final)
----------------------------------------------------------------------
Updates: Multi-Class, Face ID, Anomaly, Night Mode, Anti-Spoofing, 
THREAT SCORING (Chanakya)
(Note: Audio AI paused due to Apple Silicon TF compatibility)
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
from src.liveness_detector import LivenessDetector
from src.threat_assessor import ThreatAssessor

# 🔴 AUDIO IMPORT COMMENTED OUT
# from src.audio_detector import AudioDetector

from config.settings import (
    MODEL_PATH, LOITER_TIME, ALERT_COOLDOWN,
    PERSON_CLASS_ID, CONFIDENCE_LIMIT, CAMERA_INDEX, USE_AVFOUNDATION
)

REAL_SNAPSHOTS_DIR = BASE_DIR / "database" / "snapshots"
REAL_VIDEOS_DIR = BASE_DIR / "database" / "videos"
KNOWN_FACES_DIR = BASE_DIR / "database" / "known_faces"
ENCODINGS_FILE = BASE_DIR / "database" / "face_encodings.pkl"

print("🚀 Initializing Phase 3 Final: Autonomous Defense + Threat AI...")
model = YOLO(MODEL_PATH)
camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION if USE_AVFOUNDATION else None)

target_width, target_height = 640, 480

tracker = BehaviorTracker(max_disappeared=40)
predictor = MovementPredictor()
zone_manager = ZoneManager()
recorder = VideoRecorder(output_dir=REAL_VIDEOS_DIR)
face_id = FaceRecognizer(str(KNOWN_FACES_DIR), str(ENCODINGS_FILE))
anomaly_detector = AnomalyDetector()
nv = NightVision(threshold=85)
liveness_detector = LivenessDetector()
threat_engine = ThreatAssessor()

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

# 🔴 AUDIO FUNCTIONS COMMENTED OUT
# def handle_audio_alert(threat_name):
#     print(f"📡 Sending Audio Alert to Telegram: {threat_name}")
#     frame = system_state.get_latest_frame()
#     if frame is not None:
#         snap_path = str(REAL_SNAPSHOTS_DIR / f"audio_alert_{int(time.time())}.jpg")
#         cv2.imwrite(snap_path, frame)
#         threading.Thread(target=async_alert, args=(threat_name, snap_path, "Audio Range")).start()
#
# audio_sensor = AudioDetector(alert_callback=handle_audio_alert)
# audio_sensor.start()

print("✅ System ONLINE | Threat Matrix Active")

try:
    while True:
        success, raw_frame = camera.read()
        if not success: break
        frame_count += 1
        
        frame = cv2.resize(raw_frame, (target_width, target_height))

        is_night_active = False
        if nv.is_low_light(frame):
            frame = nv.enhance(frame)
            is_night_active = True

        is_live, blinks = liveness_detector.check_liveness(frame)
        cv2.putText(frame, f"Blinks: {blinks}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        if frame_count % 5 == 0:
            recorder.update(frame)
            system_state.update_frame(frame)
            
            detections = model(frame, verbose=False)
            current_centroids = []
            bbox_dict = {} 
            object_meta = {} 
            
            for detection in detections:
                for box in detection.boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    
                    if class_id in THREAT_CLASSES and confidence > CONFIDENCE_LIMIT:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        obj_type = THREAT_CLASSES[class_id]["name"]
                        box_color = THREAT_CLASSES[class_id]["color"]
                        
                        face_status = "N/A"
                        is_authorized = False

                        if class_id == 0:
                            identity = face_id.identify(frame, (x1, y1, x2, y2))
                            if identity != "Unknown" and identity is not None:
                                if is_live:
                                    face_status = "KNOWN"
                                    box_color = (0, 255, 0)
                                    is_authorized = True
                                else:
                                    face_status = "SPOOF"
                                    box_color = (0, 165, 255) 
                            else:
                                face_status = "UNKNOWN"
                                box_color = (0, 0, 255)

                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        current_centroids.append((cx, cy))
                        bbox_dict[(cx, cy)] = (x1, y1, x2, y2)
                        object_meta[(cx, cy)] = {"type": obj_type, "face": face_status, "auth": is_authorized, "color": box_color}

            tracked_objects = tracker.update(current_centroids)
            is_someone_in_zone = False
            highest_zone_time = 0
            primary_threat_id = None
            primary_zone_level = "UNKNOWN"

            for (obj_id, centroid) in tracked_objects.items():
                cx, cy = centroid
                
                if centroid in bbox_dict:
                    meta = object_meta[centroid]
                    x1, y1, x2, y2 = bbox_dict[centroid]
                    
                    is_anomaly, anomaly_type, severity = anomaly_detector.analyze(obj_id, (x1, y1, x2, y2), centroid)
                    current_zone = zone_manager.get_zone_for_point(cx, cy)
                    zone_level = current_zone.level if current_zone else "SAFE"
                    
                    score, category, reasons = threat_engine.calculate_threat(
                        zone_level=zone_level,
                        object_type=meta["type"],
                        face_status=meta["face"],
                        is_anomaly=is_anomaly
                    )
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), meta["color"], 2)
                    
                    if meta["type"] == "Person":
                        if meta["auth"]:
                            label = f"✅ AUTH | Threat: {score}%"
                        else:
                            label = f"⚠️ {category} | Threat: {score}%"
                    else:
                        label = f"{meta['type']} | Threat: {score}%"
                        
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, meta["color"], 2)

                    if zone_level != "SAFE":
                        is_someone_in_zone = True
                        if obj_id not in loiter_timers: loiter_timers[obj_id] = time.time()
                        time_in_zone = time.time() - loiter_timers[obj_id]
                        if time_in_zone > highest_zone_time and not meta["auth"]:
                            highest_zone_time = time_in_zone
                            primary_threat_id = obj_id
                            primary_zone_level = zone_level

            if is_someone_in_zone and highest_zone_time >= LOITER_TIME:
                if time.time() - last_alert_time >= ALERT_COOLDOWN:
                    last_alert_time = time.time()
                    recorder.trigger(prefix=f"incident_ID{primary_threat_id}")
                    snap_path = str(REAL_SNAPSHOTS_DIR / f"alert_ID{primary_threat_id}.jpg")
                    cv2.imwrite(snap_path, frame)
                    if not system_state.is_paused():
                        threading.Thread(target=async_alert, args=("Intruder Detected", snap_path, primary_zone_level)).start()

        zone_manager.draw_all_zones(frame, cv2)
        if is_night_active:
            cv2.putText(frame, "🌙 NIGHT MODE: ACTIVE", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        cv2.putText(frame, f"STATUS: ACTIVE | FPS: 15+", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("AI Surveillance - Core Command", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"): break

except Exception as e:
    print(f"⚠️ Error: {e}")
finally:
    # 🔴 AUDIO CLEANUP COMMENTED OUT
    # audio_sensor.stop() 
    camera.release()
    cv2.destroyAllWindows()
    print("✅ System Offline.")