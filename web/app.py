import sys
import time
import os
from pathlib import Path
from flask import Flask, render_template, Response, jsonify, send_file
import cv2
import atexit

# Set up paths
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# Import your AI Brains, Database, Telegram, and Report Generator
from ultralytics import YOLO
from src.threat_assessor import ThreatAssessor
from src.face_recognizer import FaceRecognizer
from src.liveness_detector import LivenessDetector
from src.database_manager import DatabaseManager
from src.telegram_bot import send_telegram_alert
from src.report_generator import generate_pdf_report
from config.settings import MODEL_PATH, CONFIDENCE_LIMIT

app = Flask(__name__)
camera = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

SNAPSHOTS_DIR = BASE_DIR / "database/snapshots"
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

def release_camera():
    if camera.isOpened():
        camera.release()
atexit.register(release_camera)

print("🧠 Loading DUAL-CORE AI & Memory...")
db = DatabaseManager()
# Standard Model (Persons, Cars, Dogs, Weapons)
model = YOLO(MODEL_PATH)
# 🔴 PHASE 5: Pose Estimation Model (Behavior/Skeleton)
pose_model = YOLO('yolov8n-pose.pt') 

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
    last_center = None

    while True:
        success, raw_frame = camera.read()
        if not success: break
            
        # 1. Core Frames Setup
        clean_frame = cv2.resize(raw_frame, (640, 480))
        frame_count += 1
        
        # 2. SKELETON TRACKING (Plotting on display frame)
        pose_results = pose_model(clean_frame, verbose=False)
        if len(pose_results) > 0:
            # Draw skeletons without bounding boxes
            display_frame = pose_results[0].plot(boxes=False)
        else:
            display_frame = clean_frame.copy()
        
        # 3. DRAW ZONES
        cv2.rectangle(display_frame, (0, 0), (320, 480), (0, 255, 0), 2)
        cv2.putText(display_frame, "Safe Zone [SAFE]", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        cv2.rectangle(display_frame, (320, 0), (640, 480), (0, 165, 255), 2)
        cv2.putText(display_frame, "Warning Zone [WARNING]", (330, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        
        # Fast Liveness Check on CLEAN frame
        is_live, blinks = liveness_detector.check_liveness(clean_frame)
        cv2.putText(display_frame, f"Blinks: {blinks}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        # Heavy AI Ops every 5 frames
        if frame_count % 5 == 0:
            latest_boxes = []
            detections = model(clean_frame, verbose=False)
            
            current_center = None
            largest_area = 0
            
            for detection in detections:
                for box in detection.boxes:
                    class_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    
                    if class_id in THREAT_CLASSES and conf > CONFIDENCE_LIMIT:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        obj_type = THREAT_CLASSES[class_id]
                        
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        zone_level = "SAFE" if cx < 320 else "WARNING"
                        
                        # 🔴 PHASE 5: Crawling Logic (Width > Height * 1.2)
                        is_crawling = False
                        if obj_type == "Person":
                            width = x2 - x1
                            height = y2 - y1
                            if width > height * 1.2:
                                is_crawling = True
                        
                        face_status = "UNKNOWN"
                        is_auth = False
                        display_name = obj_type
                        
                        if class_id == 0:
                            identity = face_id.identify(clean_frame, (x1, y1, x2, y2))
                            if identity != "Unknown" and identity is not None:
                                display_name = identity
                                face_status = "KNOWN" if is_live else "SPOOF"
                                is_auth = is_live
                                
                        # Integrating the new parameters
                        score, cat, reasons = threat_engine.calculate_threat(
                            zone_level=zone_level, 
                            object_type=obj_type, 
                            face_status=face_status, 
                            is_anomaly=False,
                            is_crawling=is_crawling,  # Activated!
                            has_weapon=False
                        )
                        
                        box_color = (0, 255, 255)
                        if is_auth and not is_crawling: box_color = (0, 255, 0)
                        elif score > 50: box_color = (0, 0, 255)
                        
                        label_prefix = "✅ " if is_auth else "⚠️ "
                        if is_crawling: label_prefix = "🕷️ CRAWL "
                        
                        label = f"{label_prefix}{display_name} | Threat: {score}%"
                        latest_boxes.append((x1, y1, x2, y2, box_color, label, cx, cy))

                        area = (x2 - x1) * (y2 - y1)
                        if area > largest_area:
                            largest_area = area
                            current_center = (cx, cy)

                        # TELEGRAM + DATABASE ALERT LOGIC
                        current_time = time.time()
                        if (current_time - last_log_time > 5) and (score > 50) and not is_auth: 
                            
                            snap_filename = f"threat_{int(current_time)}.jpg"
                            snap_path = str(SNAPSHOTS_DIR / snap_filename)
                            # Save the frame WITH the skeleton drawn on it
                            cv2.imwrite(snap_path, display_frame)
                            
                            db.log_incident(object_type=display_name, threat_score=score, zone_level=zone_level, image_path=snap_path)
                            send_telegram_alert(display_name, score, snap_path)
                            last_log_time = current_time
                            
            if current_center is not None:
                last_center = current_center

        # DRAW BOXES & TRACKING ARROW ON DISPLAY FRAME
        for (x1, y1, x2, y2, color, label, cx, cy) in latest_boxes:
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.circle(display_frame, (cx, cy), 5, (0, 255, 0), -1)
            
            if last_center is not None:
                cv2.arrowedLine(display_frame, last_center, (cx, cy), (255, 255, 0), 2, tipLength=0.3)

        ret, buffer = cv2.imencode('.jpg', display_frame)
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

@app.route('/download_report')
def download():
    try:
        report_path = generate_pdf_report()
        if report_path:
            return send_file(report_path, as_attachment=True)
        else:
            return "Error: Database is empty or not found.", 404
    except Exception as e:
        return f"Report Generation Failed: {e}", 500

if __name__ == '__main__':
    print("🌐 Project Chanakya Web Core ONLINE on Port 5001")
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)