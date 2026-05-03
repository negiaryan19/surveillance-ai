"""
AI Surveillance System - Command Center (Phase 2.4)
---------------------------------------------------
Features: YOLOv8 + Tracking + Multi-Zone + Telegram + BLACK BOX VIDEO 🎥 + FIXED PATHS
"""

import sys
import os
import cv2
import time
import threading
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

# Project Setup
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.smart_alert import calculate_threat_level, create_report, send_alert_to_telegram
from src.shared_state import system_state
from src.telegram_bot import run_telegram_bot
from src.tracker import BehaviorTracker
from src.predictor import MovementPredictor
from src.zones import ZoneManager
from src.video_recorder import VideoRecorder 
from config.settings import (
    MODEL_PATH, LOITER_TIME, ALERT_COOLDOWN,
    SNAPSHOTS_DIR, LOG_FILE, ALERT_SOUND,
    PERSON_CLASS_ID, CONFIDENCE_LIMIT,
    CAMERA_INDEX, USE_AVFOUNDATION
)

# ========================================
# Strict Directory Creation
# ========================================
# Ye force karega ki folders bane hi bane!
REAL_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "database" / "snapshots"
REAL_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

REAL_VIDEOS_DIR = Path(__file__).resolve().parent.parent / "database" / "videos"
REAL_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# ========================================
# Initialization
# ========================================
print("🚀 Initializing Mega-Integrated Surveillance System...")
model = YOLO(MODEL_PATH)

if USE_AVFOUNDATION:
    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)
else:
    camera = cv2.VideoCapture(CAMERA_INDEX)

if not camera.isOpened():
    print("❌ Camera Error!")
    exit()

tracker = BehaviorTracker(max_disappeared=40)
predictor = MovementPredictor()
zone_manager = ZoneManager()

# Black Box Video Recorder - Pointing to the strict video folder
recorder = VideoRecorder(output_dir=REAL_VIDEOS_DIR)

last_alert_time = 0
loiter_timers = {} 

bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()

print("✅ All modules (Tracking, Prediction, Zones, Telegram, Black Box) are ONLINE.")
print("=" * 50)

# ========================================
# Main Loop
# ========================================
while True:
    success, frame = camera.read()
    if not success: break

    recorder.update(frame)

    system_state.update_frame(frame)
    zone_manager.draw_all_zones(frame, cv2)

    current_centroids = []
    
    # 1. AI Detection
    detections = model(frame, verbose=False)
    for detection in detections:
        for box in detection.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])

            if class_id == PERSON_CLASS_ID and confidence > CONFIDENCE_LIMIT:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 0), 1)
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                current_centroids.append((cx, cy))

    # 2. Tracking
    tracked_objects = tracker.update(current_centroids)
    
    is_someone_in_zone = False
    total_people = len(tracked_objects)
    
    highest_zone_time = 0
    primary_threat_id = None
    primary_behavior = "Analyzing..."
    primary_zone_level = "UNKNOWN"

    # 3. Process Objects & Zones
    for (obj_id, centroid) in tracked_objects.items():
        cx, cy = centroid
        predictor.update(obj_id, cx, cy)
        
        current_zone = zone_manager.get_zone_for_point(cx, cy)
        behavior = tracker.get_behavior(obj_id)

        if current_zone and current_zone.level != "SAFE":
            is_someone_in_zone = True
            color = (0, 0, 255) if current_zone.level == "CRITICAL" else (0, 165, 255)

            if obj_id not in loiter_timers:
                loiter_timers[obj_id] = time.time()
            
            time_in_zone = time.time() - loiter_timers[obj_id]
            
            if time_in_zone > highest_zone_time:
                highest_zone_time = time_in_zone
                primary_threat_id = obj_id
                primary_behavior = behavior
                primary_zone_level = current_zone.level 
                
            label = f"ID:{obj_id} | {current_zone.level} | {int(time_in_zone)}s"
        else:
            color = (0, 255, 0)
            label = f"ID:{obj_id} | SAFE"
            if obj_id in loiter_timers:
                del loiter_timers[obj_id]

        pred_pos = predictor.predict_next_position(obj_id)
        if pred_pos:
            cv2.arrowedLine(frame, (cx, cy), pred_pos, (255, 255, 0), 2, tipLength=0.3)
            
        cv2.circle(frame, (cx, cy), 6, color, -1)
        cv2.putText(frame, label, (cx - 10, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    # 4. Status UI
    status_text = "THREAT MONITORING" if is_someone_in_zone else "SECURE"
    status_color = (0, 0, 255) if is_someone_in_zone else (0, 255, 0)
    cv2.putText(frame, f"STATUS: {status_text}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
    cv2.putText(frame, f"People: {total_people}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # 5. Alert & Black Box Trigger Logic
    if is_someone_in_zone and highest_zone_time >= LOITER_TIME:
        current_time = time.time()
        if current_time - last_alert_time >= ALERT_COOLDOWN:
            last_alert_time = current_time

            print(f"🚨 ALERT TRIGGERED: ID {primary_threat_id} in {primary_zone_level} zone!")
            
            recorder.trigger(prefix=f"incident_ID{primary_threat_id}")
            
            threat_lvl = calculate_threat_level(total_people, highest_zone_time, primary_behavior)
            report = create_report(total_people, highest_zone_time, primary_behavior, threat_lvl)
            
            # Using the strict directory path
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            snap_path = str(REAL_SNAPSHOTS_DIR / f"alert_ID{primary_threat_id}_{ts}.jpg")
            
            # Print location so we know exactly where it goes!
            print(f"📸 DHYAN DO -> Photo saved at: {snap_path}")
            
            cv2.imwrite(snap_path, frame)

            if not system_state.is_paused():
                send_alert_to_telegram(report, snap_path)
                os.system(f'say "Alert. Intruder in {primary_zone_level} zone" &')

            with open(LOG_FILE, "a") as log:
                log.write(f"{datetime.now()} | ID: {primary_threat_id} | Zone: {primary_zone_level}\n")

    cv2.imshow("AI Surveillance - Core Command", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()
print("\n✅ System Offline.")