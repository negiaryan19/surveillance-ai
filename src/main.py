"""
AI Surveillance System - Main Entry Point
------------------------------------------
Runs detection + Telegram bot together.
"""

import sys
import os
import cv2
import time
import threading
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

# Add parent directory for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.smart_alert import (
    BehaviorTracker,
    calculate_threat_level,
    create_report,
    send_alert_to_telegram
)
from src.shared_state import system_state
from src.telegram_bot import run_telegram_bot
from config.settings import (
    MODEL_PATH, ZONE, LOITER_TIME, ALERT_COOLDOWN,
    SNAPSHOTS_DIR, LOG_FILE, ALERT_SOUND,
    PERSON_CLASS_ID, CONFIDENCE_LIMIT,
    CAMERA_INDEX, USE_AVFOUNDATION
)

# ========================================
# Setup
# ========================================
print("🚀 Starting AI Surveillance System...")
print("=" * 50)

# Load AI model
print("🧠 Loading YOLOv8 model...")
model = YOLO(MODEL_PATH)
print("✅ Model loaded!")

# Open camera
print("📷 Opening camera...")
if USE_AVFOUNDATION:
    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_AVFOUNDATION)
else:
    camera = cv2.VideoCapture(CAMERA_INDEX)

if not camera.isOpened():
    print("❌ Camera not working.")
    exit()

print("✅ Camera ready!")

# Initialize tracker
tracker = BehaviorTracker()
loiter_start_time = None
alert_already_sent = False
last_alert_time = 0

# Update zone in shared state
system_state.zone_coordinates = ZONE

# ========================================
# Start Telegram Bot in Background
# ========================================
print("\n🤖 Starting Telegram Bot in background...")
bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()
time.sleep(2)  # Give bot time to start
print("=" * 50)
print("✅ All systems ready! Press 'Q' to exit.\n")

# ========================================
# Main Detection Loop
# ========================================
while True:
    success, frame = camera.read()
    if not success:
        print("⚠️ Camera frame missing.")
        break

    # Update shared state with current frame (for /snapshot command)
    system_state.update_frame(frame)

    # Draw the restricted zone
    zone_x1, zone_y1, zone_x2, zone_y2 = ZONE
    cv2.rectangle(frame, (zone_x1, zone_y1), (zone_x2, zone_y2), (0, 0, 255), 2)
    cv2.putText(
        frame, "Restricted Zone",
        (zone_x1 + 10, zone_y1 + 30),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2
    )

    is_someone_in_zone = False
    total_people = 0

    # Run AI detection
    detections = model(frame, verbose=False)

    for detection in detections:
        for box in detection.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])

            if class_id != PERSON_CLASS_ID:
                continue
            if confidence < CONFIDENCE_LIMIT:
                continue

            total_people += 1

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2

            inside_zone = (
                zone_x1 <= center_x <= zone_x2 and
                zone_y1 <= center_y <= zone_y2
            )

            if inside_zone:
                is_someone_in_zone = True
                tracker.add_position(center_x, center_y)
                box_color = (0, 0, 255)
                box_label = f"INTRUDER {confidence:.2f}"
            else:
                box_color = (0, 255, 0)
                box_label = f"Person {confidence:.2f}"

            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
            cv2.putText(
                frame, box_label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, box_color, 2
            )
            cv2.circle(frame, (center_x, center_y), 6, (255, 0, 0), -1)

    # Show people count
    cv2.putText(
        frame, f"People Detected: {total_people}",
        (10, 70),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
    )

    # Show pause indicator
    if system_state.is_paused():
        cv2.putText(
            frame, "⏸ ALERTS PAUSED",
            (10, 200),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2
        )

    # Alert logic
    if is_someone_in_zone:
        if loiter_start_time is None:
            loiter_start_time = time.time()

        time_in_zone = time.time() - loiter_start_time

        cv2.putText(
            frame, f"Zone Time: {int(time_in_zone)}s",
            (10, 110),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2
        )
        cv2.putText(
            frame, "STATUS: THREAT MONITORING",
            (10, 150),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2
        )

        current_time = time.time()
        time_since_last_alert = current_time - last_alert_time

        should_send_alert = (
            time_in_zone >= LOITER_TIME and
            not alert_already_sent and
            time_since_last_alert >= ALERT_COOLDOWN
        )

        if should_send_alert:
            alert_already_sent = True
            last_alert_time = current_time

            print("\n" + "=" * 50)
            print("🚨 INTRUDER ALERT TRIGGERED 🚨")
            print("=" * 50)

            # Analyze behavior
            behavior = tracker.get_behavior()

            # Calculate threat level
            threat_level = calculate_threat_level(
                total_people, time_in_zone, behavior
            )

            # Create report
            report_message = create_report(
                total_people, time_in_zone, behavior, threat_level
            )

            print(report_message)

            # Save snapshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_path = str(SNAPSHOTS_DIR / f"intruder_{timestamp}.jpg")
            cv2.imwrite(snapshot_path, frame)

            # Record in shared state
            system_state.add_alert(threat_level, behavior, total_people)

            # Send alert (only if not paused)
            if system_state.is_paused():
                print("⏸️ Alerts paused - skipping Telegram notification")
            else:
                send_alert_to_telegram(report_message, snapshot_path)

                # Voice/Audio alerts
                if threat_level == "CRITICAL":
                    os.system('say "Critical threat detected" &')
                elif threat_level == "HIGH":
                    os.system('say "High alert. Intruder detected" &')
                else:
                    os.system('say "Intruder detected" &')

                if os.path.exists(ALERT_SOUND):
                    os.system(f'afplay "{ALERT_SOUND}" &')

            # Log it
            with open(LOG_FILE, "a") as log:
                log.write(
                    f"[{threat_level}] {datetime.now()} | "
                    f"Behavior: {behavior} | "
                    f"People: {total_people} | "
                    f"Image: {snapshot_path}\n"
                )

    else:
        loiter_start_time = None
        alert_already_sent = False
        tracker.reset()

        cv2.putText(
            frame, "STATUS: SECURE",
            (10, 110),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
        )

    cv2.imshow("AI Surveillance System", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Cleanup
camera.release()
cv2.destroyAllWindows()
print("\n✅ System stopped safely.")