# """
# AI Surveillance System - Command Center (Phase 3.2)
# ---------------------------------------------------
# Updates: Frame Skip (5x), Threaded Alerts, Multi-Class Detection, Face Recognition
# """

# import sys
# import os
# import cv2
# import time
# import numpy as np
# import threading
# from datetime import datetime
# from pathlib import Path
# from ultralytics import YOLO

# # Project Setup
# BASE_DIR = Path(__file__).resolve().parent.parent
# sys.path.append(str(BASE_DIR))

# from src.smart_alert import calculate_threat_level, create_report, send_alert_to_telegram
# from src.shared_state import system_state
# from src.telegram_bot import run_telegram_bot
# from src.tracker import BehaviorTracker
# from src.predictor import MovementPredictor
# from src.zones import ZoneManager
# from src.video_recorder import VideoRecorder 
# # Naya Import Phase 3 ke liye
# from src.face_recognizer import FaceRecognizer

# from config.settings import (
#     MODEL_PATH, LOITER_TIME, ALERT_COOLDOWN,
#     SNAPSHOTS_DIR, LOG_FILE, ALERT_SOUND,
#     PERSON_CLASS_ID, CONFIDENCE_LIMIT,
#     CAMERA_INDEX, USE_AVFOUNDATION
# )

# # ========================================
# # Directory Setup
# # ========================================
# REAL_SNAPSHOTS_DIR = BASE_DIR / "database" / "snapshots"
# REAL_VIDEOS_DIR = BASE_DIR / "database" / "videos"
# KNOWN_FACES_DIR = BASE_DIR / "database" / "known_faces"
# ENCODINGS_FILE = BASE_DIR / "database" / "face_encodings.pkl"

# REAL_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
# REAL_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
# KNOWN_FACES_DIR.mkdir(parents=True, exist_ok=True)

# # ========================================
# # Initialization
# # ========================================
# print("🚀 Initializing Autonomous Defense System (Phase 3)...")
# model = YOLO(MODEL_PATH)

# if USE_AVFOUNDATION:
#     camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)
# else:
#     camera = cv2.VideoCapture(CAMERA_INDEX)

# # Performance Target
# target_width, target_height = 640, 480

# tracker = BehaviorTracker(max_disappeared=40)
# predictor = MovementPredictor()
# zone_manager = ZoneManager()
# recorder = VideoRecorder(output_dir=REAL_VIDEOS_DIR)

# # Initialize Face Recognizer
# face_id = FaceRecognizer(str(KNOWN_FACES_DIR), str(ENCODINGS_FILE))

# # Define Threat Classes (YOLO COCO Classes)
# THREAT_CLASSES = {
#     0: {"name": "Person", "color": (0, 255, 255)}, # Cyan
#     1: {"name": "Bicycle", "color": (255, 255, 0)},
#     2: {"name": "Car", "color": (0, 0, 255)},      # Red
#     3: {"name": "Motorcycle", "color": (0, 0, 255)},
#     16: {"name": "Dog", "color": (0, 255, 0)}      # Green
# }

# heatmap_accumulation = np.zeros((target_height, target_width), dtype=np.float32)

# last_alert_time = 0
# loiter_timers = {} 
# frame_count = 0

# # Start Bot
# bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
# bot_thread.start()

# # Threaded Audio & Telegram Alert (No Lag!)
# def async_alert(report, path, zone_level):
#     send_alert_to_telegram(report, path)
#     os.system(f'say -v Samantha "Alert. Intruder detected in {zone_level} zone" &')
#     print(f"✅ Background Alert & Sound Sent for: {zone_level}")

# print("✅ System Optimized. Multi-Class & Face ID Active.")
# print("=" * 50)

# try:
#     while True:
#         success, raw_frame = camera.read()
#         if not success: break

#         frame_count += 1
        
#         # 1. IMMEDIATE RESIZE
#         frame = cv2.resize(raw_frame, (target_width, target_height))

#         # 2. FRAME SKIPPING (CRITICAL FIX)
#         if frame_count % 5 == 0:
#             recorder.update(frame)
#             system_state.update_frame(frame)
            
#             # AI Inference
#             detections = model(frame, verbose=False)
#             current_centroids = []
            
#             for detection in detections:
#                 for box in detection.boxes:
#                     class_id = int(box.cls[0])
#                     confidence = float(box.conf[0])
                    
#                     # Phase 3.1: Check if it's a threat class
#                     if class_id in THREAT_CLASSES and confidence > CONFIDENCE_LIMIT:
#                         x1, y1, x2, y2 = map(int, box.xyxy[0])
#                         threat_info = THREAT_CLASSES[class_id]
                        
#                         label = f"{threat_info['name']} {confidence:.2f}"
#                         box_color = threat_info["color"]
#                         is_authorized = False

#                         # Phase 3.2: Face Recognition for Humans
#                         if class_id == 0:
#                             identity = face_id.identify(frame, (x1, y1, x2, y2))
#                             if identity != "Unknown" and identity is not None:
#                                 label = f"✅ AUTHORIZED: {identity}"
#                                 box_color = (0, 255, 0) # Green for Safe
#                                 is_authorized = True
#                             else:
#                                 label = "⚠️ UNKNOWN INTRUDER"
#                                 box_color = (0, 0, 255) # Red for Danger

#                         cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
#                         cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

#                         # Track only if NOT authorized (Ignores known faces)
#                         if not is_authorized:
#                             current_centroids.append(((x1 + x2) // 2, (y1 + y2) // 2))

#             # Tracking & Heavy Calculations
#             tracked_objects = tracker.update(current_centroids)
#             is_someone_in_zone = False
#             highest_zone_time = 0
#             primary_threat_id = None
#             primary_zone_level = "UNKNOWN"

#             for (obj_id, centroid) in tracked_objects.items():
#                 cx, cy = centroid
#                 predictor.update(obj_id, cx, cy)
                
#                 # Heatmap Update
#                 if 0 <= cy < target_height and 0 <= cx < target_width:
#                     cv2.circle(heatmap_accumulation, (cx, cy), 15, (1), -1)
                
#                 current_zone = zone_manager.get_zone_for_point(cx, cy)
#                 if current_zone and current_zone.level != "SAFE":
#                     is_someone_in_zone = True
#                     if obj_id not in loiter_timers: loiter_timers[obj_id] = time.time()
#                     time_in_zone = time.time() - loiter_timers[obj_id]
                    
#                     if time_in_zone > highest_zone_time:
#                         highest_zone_time = time_in_zone
#                         primary_threat_id = obj_id
#                         primary_zone_level = current_zone.level
                    
#                     color = (0, 0, 255) if current_zone.level == "CRITICAL" else (0, 165, 255)
#                     cv2.circle(frame, (cx, cy), 5, color, -1)
#                 else:
#                     if obj_id in loiter_timers: del loiter_timers[obj_id]
#                     cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)

#             # Alert Logic with Cooldown check
#             if is_someone_in_zone and highest_zone_time >= LOITER_TIME:
#                 if time.time() - last_alert_time >= ALERT_COOLDOWN:
#                     last_alert_time = time.time()
#                     print(f"🚨 Sending Alert for ID {primary_threat_id}...")
#                     recorder.trigger(prefix=f"incident_ID{primary_threat_id}")
                    
#                     ts = datetime.now().strftime("%Y%m%d_%H%M%S")
#                     snap_path = str(REAL_SNAPSHOTS_DIR / f"alert_ID{primary_threat_id}_{ts}.jpg")
#                     cv2.imwrite(snap_path, frame)
                    
#                     if not system_state.is_paused():
#                         # Use Threaded Alert function
#                         threading.Thread(target=async_alert, args=("Intruder Detected!", snap_path, primary_zone_level)).start()

#         # Draw UI
#         zone_manager.draw_all_zones(frame, cv2)
#         cv2.putText(frame, f"STATUS: ACTIVE | FPS: 15+", (10, 30), 
#                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
#         cv2.imshow("AI Surveillance - Core Command", frame)

#         if cv2.waitKey(1) & 0xFF == ord("q"):
#             break

# except Exception as e:
#     print(f"⚠️ Error: {e}")

# finally:
#     # Heatmap Generation
#     if np.max(heatmap_accumulation) > 0:
#         heatmap_norm = cv2.normalize(heatmap_accumulation, None, 0, 255, cv2.NORM_MINMAX)
#         heatmap_blur = cv2.GaussianBlur(np.uint8(heatmap_norm), (31, 31), 0)
#         heatmap_color = cv2.applyColorMap(heatmap_blur, cv2.COLORMAP_JET)
#         cv2.imwrite(str(BASE_DIR / "database" / "final_heatmap.jpg"), heatmap_color)

#     camera.release()
#     cv2.destroyAllWindows()
#     print("✅ System Offline.")
"""
AI Surveillance System - Command Center (Phase 3.3)
---------------------------------------------------
Updates: Multi-Class, Face Recognition AND Anomaly Detection 🚨
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
# NAYA IMPORT: Anomaly Detector
from src.anomaly_detector import AnomalyDetector

from config.settings import (
    MODEL_PATH, LOITER_TIME, ALERT_COOLDOWN,
    PERSON_CLASS_ID, CONFIDENCE_LIMIT, CAMERA_INDEX, USE_AVFOUNDATION
)

REAL_SNAPSHOTS_DIR = BASE_DIR / "database" / "snapshots"
REAL_VIDEOS_DIR = BASE_DIR / "database" / "videos"
KNOWN_FACES_DIR = BASE_DIR / "database" / "known_faces"
ENCODINGS_FILE = BASE_DIR / "database" / "face_encodings.pkl"

print("🚀 Initializing Phase 3.3: Anomaly & Behavior Detection...")
model = YOLO(MODEL_PATH)
camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION if USE_AVFOUNDATION else None)

target_width, target_height = 640, 480

tracker = BehaviorTracker(max_disappeared=40)
predictor = MovementPredictor()
zone_manager = ZoneManager()
recorder = VideoRecorder(output_dir=REAL_VIDEOS_DIR)
face_id = FaceRecognizer(str(KNOWN_FACES_DIR), str(ENCODINGS_FILE))

# Initialize Anomaly Detector
anomaly_detector = AnomalyDetector()

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

print("✅ System ONLINE | Anomaly Engine Active")

try:
    while True:
        success, raw_frame = camera.read()
        if not success: break
        frame_count += 1
        frame = cv2.resize(raw_frame, (target_width, target_height))

        if frame_count % 5 == 0:
            recorder.update(frame)
            system_state.update_frame(frame)
            
            detections = model(frame, verbose=False)
            current_centroids = []
            bbox_dict = {} # Track boxes for anomaly logic
            
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

                        if class_id == 0:
                            identity = face_id.identify(frame, (x1, y1, x2, y2))
                            if identity != "Unknown" and identity is not None:
                                label = f"✅ AUTH: {identity}"
                                box_color = (0, 255, 0)
                                is_authorized = True
                            else:
                                label = "⚠️ INTRUDER"
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
                
                # Anomaly Detection Check
                if centroid in bbox_dict:
                    is_anomaly, anomaly_type, severity = anomaly_detector.analyze(obj_id, bbox_dict[centroid], centroid)
                    if is_anomaly:
                        cv2.putText(frame, f"🚨 {anomaly_type}!", (cx - 50, cy + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                        
                        # Immediate Alert for High Severity Anomalies
                        if severity == "HIGH" and (time.time() - last_alert_time >= 30):
                            last_alert_time = time.time()
                            snap_path = str(REAL_SNAPSHOTS_DIR / f"anomaly_{anomaly_type.replace(' ', '_')}_{obj_id}.jpg")
                            cv2.imwrite(snap_path, frame)
                            threading.Thread(target=async_alert, args=(anomaly_type, snap_path, "Sector")).start()
                            anomaly_alert_triggered = True

                # Standard Zone Tracking
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

            # Zone Alert Logic (Runs only if Anomaly Alert didn't fire)
            if is_someone_in_zone and highest_zone_time >= LOITER_TIME and not anomaly_alert_triggered:
                if time.time() - last_alert_time >= ALERT_COOLDOWN:
                    last_alert_time = time.time()
                    recorder.trigger(prefix=f"incident_ID{primary_threat_id}")
                    snap_path = str(REAL_SNAPSHOTS_DIR / f"alert_ID{primary_threat_id}.jpg")
                    cv2.imwrite(snap_path, frame)
                    if not system_state.is_paused():
                        threading.Thread(target=async_alert, args=("Intruder Detected", snap_path, primary_zone_level)).start()

        zone_manager.draw_all_zones(frame, cv2)
        cv2.putText(frame, f"STATUS: ANOMALY ENGINE ON | FPS: 15+", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("AI Surveillance - Core Command", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"): break

except Exception as e:
    print(f"⚠️ Error: {e}")
finally:
    camera.release()
    cv2.destroyAllWindows()
    print("✅ System Offline.")