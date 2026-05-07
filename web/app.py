# import sys
# import time
# from pathlib import Path
# from flask import Flask, render_template, Response, jsonify
# import cv2
# import atexit

# # Set up paths
# BASE_DIR = Path(__file__).resolve().parent.parent
# sys.path.append(str(BASE_DIR))

# # Import your AI Brains & Database
# from ultralytics import YOLO
# from src.threat_assessor import ThreatAssessor
# from src.face_recognizer import FaceRecognizer
# from src.liveness_detector import LivenessDetector
# from src.database_manager import DatabaseManager
# from config.settings import MODEL_PATH, CONFIDENCE_LIMIT

# app = Flask(__name__)

# # Initialize Camera
# camera = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

# def release_camera():
#     if camera.isOpened():
#         camera.release()
#         print("📷 Camera safely released.")
# atexit.register(release_camera)

# # 🧠 INITIALIZE AI ENGINE & MEMORY
# print("🧠 Loading AI Core & Memory...")
# db = DatabaseManager()
# model = YOLO(MODEL_PATH)
# face_id = FaceRecognizer(str(BASE_DIR / "database/known_faces"), str(BASE_DIR / "database/face_encodings.pkl"))
# liveness_detector = LivenessDetector()
# threat_engine = ThreatAssessor()

# THREAT_CLASSES = {
#     0: {"name": "Person", "color": (0, 255, 255)},
#     2: {"name": "Car", "color": (0, 0, 255)},
#     3: {"name": "Motorcycle", "color": (0, 0, 255)},
#     16: {"name": "Dog", "color": (0, 255, 0)}
# }

# def generate_frames():
#     """Captures frames, runs AI, and logs to database with a cooldown."""
#     frame_count = 0
#     latest_boxes = []
#     last_log_time = 0  # 🕒 Cooldown tracker

#     while True:
#         success, raw_frame = camera.read()
#         if not success:
#             break
            
#         frame = cv2.resize(raw_frame, (640, 480))
#         frame_count += 1
        
#         # Check Liveness
#         is_live, blinks = liveness_detector.check_liveness(frame)
#         cv2.putText(frame, f"Blinks: {blinks}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        
#         # Run AI Heavy Ops every 5 frames
#         if frame_count % 5 == 0:
#             latest_boxes = []
#             detections = model(frame, verbose=False)
            
#             for detection in detections:
#                 for box in detection.boxes:
#                     class_id = int(box.cls[0])
#                     conf = float(box.conf[0])
                    
#                     if class_id in THREAT_CLASSES and conf > CONFIDENCE_LIMIT:
#                         x1, y1, x2, y2 = map(int, box.xyxy[0])
#                         obj_type = THREAT_CLASSES[class_id]["name"]
#                         box_color = THREAT_CLASSES[class_id]["color"]
                        
#                         face_status = "UNKNOWN"
#                         is_auth = False
                        
#                         if class_id == 0:
#                             identity = face_id.identify(frame, (x1, y1, x2, y2))
#                             if identity != "Unknown" and identity is not None:
#                                 face_status = "KNOWN" if is_live else "SPOOF"
#                                 is_auth = is_live
#                                 box_color = (0, 255, 0) if is_auth else (0, 165, 255)
                                
#                         score, cat, reasons = threat_engine.calculate_threat(
#                             zone_level="SAFE", object_type=obj_type, face_status=face_status, is_anomaly=False
#                         )
                        
#                         label = f"{'✅ AUTH' if is_auth else f'⚠️ {cat}'} | Threat: {score}%"
#                         latest_boxes.append((x1, y1, x2, y2, box_color, label))

#                         # 💾 DATABASE LOGGING WITH 5-SECOND COOLDOWN
#                         current_time = time.time()
#                         if (current_time - last_log_time > 5) and (score > 10): 
#                             db.log_incident(object_type=obj_type, threat_score=score, zone_level="SAFE")
#                             last_log_time = current_time

#         # Draw boxes
#         for (x1, y1, x2, y2, color, label) in latest_boxes:
#             cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
#             cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

#         ret, buffer = cv2.imencode('.jpg', frame)
#         frame_bytes = buffer.tobytes()
#         yield (b'--frame\r\n'
#                b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# @app.route('/')
# def index():
#     return render_template('index.html')

# @app.route('/video_feed')
# def video_feed():
#     return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# # 📡 NEW API ROUTE: To send database logs to the web dashboard
# @app.route('/api/logs')
# def get_logs():
#     logs = db.get_recent_logs(limit=15)
#     log_list = [{"timestamp": l[0], "object": l[1], "threat": l[2], "zone": l[3]} for l in logs]
#     return jsonify(log_list)

# if __name__ == '__main__':
#     print("🌐 Project Chanakya Web Core ONLINE on Port 5001")
#     app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)



import sys
import time
import os
from pathlib import Path
from flask import Flask, render_template, Response, jsonify
import cv2
import atexit

# Set up paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# Import your AI Brains, Database, and Telegram Bot
from ultralytics import YOLO
from src.threat_assessor import ThreatAssessor
from src.face_recognizer import FaceRecognizer
from src.liveness_detector import LivenessDetector
from src.database_manager import DatabaseManager
from src.telegram_bot import send_telegram_alert  # 📱 TELEGRAM BOT IS HERE
from config.settings import MODEL_PATH, CONFIDENCE_LIMIT

app = Flask(__name__)
camera = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

# Create folder for saving threat snapshots
SNAPSHOTS_DIR = BASE_DIR / "database/snapshots"
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

def release_camera():
    if camera.isOpened():
        camera.release()
atexit.register(release_camera)

print("🧠 Loading AI Core & Memory...")
db = DatabaseManager()
model = YOLO(MODEL_PATH)
face_id = FaceRecognizer(str(BASE_DIR / "database/known_faces"), str(BASE_DIR / "database/face_encodings.pkl"))
liveness_detector = LivenessDetector()
threat_engine = ThreatAssessor()

THREAT_CLASSES = {
    0: "Person",
    2: "Car",
    3: "Motorcycle",
    16: "Dog"
}

def generate_frames():
    frame_count = 0
    latest_boxes = []
    last_log_time = 0
    last_center = None  # Arrow draw karne ke liye pichli position

    while True:
        success, raw_frame = camera.read()
        if not success: break
            
        frame = cv2.resize(raw_frame, (640, 480))
        frame_count += 1
        
        # ==========================================
        # 🗺️ 1. DRAW ZONES (SAFE vs WARNING)
        # ==========================================
        # Left half (0 to 320) -> SAFE ZONE
        cv2.rectangle(frame, (0, 0), (320, 480), (0, 255, 0), 2)
        cv2.putText(frame, "Safe Zone [SAFE]", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Right half (320 to 640) -> WARNING ZONE
        cv2.rectangle(frame, (320, 0), (640, 480), (0, 165, 255), 2)
        cv2.putText(frame, "Warning Zone [WARNING]", (330, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        
        # Fast Liveness Check
        is_live, blinks = liveness_detector.check_liveness(frame)
        cv2.putText(frame, f"Blinks: {blinks}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        # Heavy AI Ops every 5 frames
        if frame_count % 5 == 0:
            latest_boxes = []
            detections = model(frame, verbose=False)
            
            current_center = None
            largest_area = 0
            
            for detection in detections:
                for box in detection.boxes:
                    class_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    
                    if class_id in THREAT_CLASSES and conf > CONFIDENCE_LIMIT:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        obj_type = THREAT_CLASSES[class_id]
                        
                        # Find object center (Centroid)
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        
                        # Decide Zone (Left or Right side)
                        zone_level = "SAFE" if cx < 320 else "WARNING"
                        
                        face_status = "UNKNOWN"
                        is_auth = False
                        
                        if class_id == 0:
                            identity = face_id.identify(frame, (x1, y1, x2, y2))
                            if identity != "Unknown" and identity is not None:
                                face_status = "KNOWN" if is_live else "SPOOF"
                                is_auth = is_live
                                
                        score, cat, reasons = threat_engine.calculate_threat(
                            zone_level=zone_level, object_type=obj_type, face_status=face_status, is_anomaly=False
                        )
                        
                        # Color coding based on Threat
                        box_color = (0, 255, 255) # Yellow default
                        if is_auth: box_color = (0, 255, 0) # Green for Auth
                        elif score > 50: box_color = (0, 0, 255) # Red for Threat
                        
                        label = f"{'✅ AUTH' if is_auth else f'⚠️ {cat}'} | Threat: {score}%"
                        latest_boxes.append((x1, y1, x2, y2, box_color, label, cx, cy))

                        # Tracker logic for arrow
                        area = (x2 - x1) * (y2 - y1)
                        if area > largest_area:
                            largest_area = area
                            current_center = (cx, cy)

                        # ==========================================
                        # 🚨 2. TELEGRAM + DATABASE ALERT LOGIC
                        # ==========================================
                        current_time = time.time()
                        if (current_time - last_log_time > 5) and (score > 50) and not is_auth: 
                            
                            snap_filename = f"threat_{int(current_time)}.jpg"
                            snap_path = str(SNAPSHOTS_DIR / snap_filename)
                            cv2.imwrite(snap_path, frame)
                            
                            db.log_incident(object_type=obj_type, threat_score=score, zone_level=zone_level, image_path=snap_path)
                            
                            print(f"\n🚀 System Triggered! Sending Alert to Telegram...")
                            send_telegram_alert(obj_type, score, snap_path)
                            
                            last_log_time = current_time
                            
            if current_center is not None:
                last_center = current_center

        # ==========================================
        # 🎯 3. DRAW BOXES & TRACKING ARROW
        # ==========================================
        for (x1, y1, x2, y2, color, label, cx, cy) in latest_boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            # Draw Centroid Dot (Green)
            cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)
            
            # Draw Cyan Tracking Arrow based on previous frame
            if last_center is not None:
                cv2.arrowedLine(frame, last_center, (cx, cy), (255, 255, 0), 2, tipLength=0.3)

        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/logs')
def get_logs():
    logs = db.get_recent_logs(limit=15)
    log_list = [{"timestamp": l[0], "object": l[1], "threat": l[2], "zone": l[3]} for l in logs]
    return jsonify(log_list)

if __name__ == '__main__':
    print("🌐 Project Chanakya Web Core ONLINE on Port 5001")
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)