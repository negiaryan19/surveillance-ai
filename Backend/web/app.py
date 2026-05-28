import sys
import time
import os
import threading
from pathlib import Path
from flask import Flask, render_template, Response, jsonify, send_file
from flask_cors import CORS  # 👈 NEW: Added CORS for React connection
import cv2
import numpy as np
import atexit

# --- PATH & IMPORT SETUP ---
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from ultralytics import YOLO
from src.threat_assessor import ThreatAssessor
from src.face_recognizer import FaceRecognizer
from src.liveness_detector import LivenessDetector
from src.database_manager import DatabaseManager
from src.telegram_bot import send_telegram_alert
from src.report_generator import generate_pdf_report
from config.settings import MODEL_PATH, CONFIDENCE_LIMIT

# 🔐 Optional Encryption Fallback
try:
    from src.security_vault import encrypt_file
    ENCRYPTION_ENABLED = True
except ImportError:
    print("⚠️ WARNING: Cryptography module missing. Reports will NOT be encrypted.")
    ENCRYPTION_ENABLED = False

app = Flask(__name__)
CORS(app)  # 👈 NEW: This allows your React Command Center to talk to Flask

SNAPSHOTS_DIR = BASE_DIR / "database/snapshots"
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

# --- ADVANCED THREADED CAMERA CLASS ---
class ThreadedCamera:
    def __init__(self, src=0):
        self.capture = cv2.VideoCapture(src, cv2.CAP_AVFOUNDATION)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        self.ret, self.frame = self.capture.read()
        self.stopped = False
        self.lock = threading.Lock()
        if self.ret:
            self.thread = threading.Thread(target=self.update, args=())
            self.thread.daemon = True
            self.thread.start()

    def update(self):
        while not self.stopped:
            ret, frame = self.capture.read()
            with self.lock:
                self.ret = ret
                self.frame = frame
            time.sleep(0.01)

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.ret else None

    def stop(self):
        self.stopped = True
        if hasattr(self, 'thread'):
            self.thread.join()
        self.capture.release()

# Start Cameras
print("🎥 Initializing Camera Threads...")
cam_alpha = ThreadedCamera(0)  # Master Cam
cam_bravo = ThreadedCamera(1)  # Secondary Cam

def cleanup():
    cam_alpha.stop()
    cam_bravo.stop()
atexit.register(cleanup)

# --- LOAD AI MODELS & TRAFFIC CONTROLLER ---
print("🧠 Loading DUAL-CORE AI & Memory...")
db = DatabaseManager()

# 🚦 THE AI LOCK (Fixes PyTorch Collision)
ai_lock = threading.Lock()

model = YOLO(MODEL_PATH)                  
pose_model = YOLO('yolov8n-pose.pt')      
face_id = FaceRecognizer(str(BASE_DIR / "database/known_faces"), str(BASE_DIR / "database/face_encodings.pkl"))
liveness_detector = LivenessDetector()
threat_engine = ThreatAssessor()

THREAT_CLASSES = {
    0: "Person",
    2: "Car",
    3: "Motorcycle",
    16: "Dog",
    43: "Weapon (Knife)"
}

# --- MASTER AI PROCESSING LOOP ---
def generate_ai_frames(camera, cam_name="ALPHA"):
    frame_count = 0
    latest_boxes = []
    last_log_time = 0
    last_center = None

    tracked_objects = {}

    while True:
        ret, raw_frame = camera.read()
        if not ret or raw_frame is None:
            time.sleep(0.5)
            continue
            
        clean_frame = cv2.resize(raw_frame, (640, 480))
        frame_count += 1
        
        # 1. SKELETON LAYER (Protected by AI Lock)
        with ai_lock:
            pose_results = pose_model(clean_frame, verbose=False)
        display_frame = pose_results[0].plot(boxes=False) if len(pose_results) > 0 else clean_frame.copy()
        
        # ZONES LAYER
        cv2.rectangle(display_frame, (0, 0), (320, 480), (0, 255, 0), 2)
        cv2.putText(display_frame, f"FEED: {cam_name} [SAFE]", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.rectangle(display_frame, (320, 0), (640, 480), (0, 165, 255), 2)
        cv2.putText(display_frame, "[WARNING]", (330, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        
        is_live, blinks = liveness_detector.check_liveness(clean_frame)
        cv2.putText(display_frame, f"EAR Blinks: {blinks}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        
        # 2. DETECTION LAYER WITH TRACKING (Protected by AI Lock, Every frame)
        with ai_lock:
            detections = model.track(clean_frame, persist=True, tracker="bytetrack.yaml", verbose=False)
        
        latest_boxes = []
        current_center = None
        largest_area = 0
        
        do_heavy_calc = (frame_count % 5 == 0)
        
        for detection in detections:
            if detection.boxes is None or detection.boxes.id is None:
                continue
                
            for box in detection.boxes:
                class_id = int(box.cls[0])
                conf = float(box.conf[0])
                
                if class_id in THREAT_CLASSES and conf > CONFIDENCE_LIMIT:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    obj_type = THREAT_CLASSES[class_id]
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    zone_level = "SAFE" if cx < 320 else "WARNING"
                    
                    track_id = int(box.id[0]) if box.id is not None else -1
                    if track_id == -1:
                        continue
                        
                    is_crawling = False
                    has_weapon = True if class_id == 43 else False
                    
                    if obj_type == "Person":
                        width, height = (x2 - x1), (y2 - y1)
                        if width > height * 1.2:
                            is_crawling = True
                            
                    if do_heavy_calc or track_id not in tracked_objects:
                        face_status, is_auth, display_name = "UNKNOWN", False, obj_type
                        
                        if class_id == 0:
                            identity = face_id.identify(clean_frame, (x1, y1, x2, y2))
                            if identity not in ["Unknown", None]:
                                display_name = identity
                                face_status = "KNOWN" if is_live else "SPOOF"
                                is_auth = is_live
                                
                        score, cat, reasons = threat_engine.calculate_threat(
                            zone_level=zone_level, object_type=obj_type, 
                            face_status=face_status, is_crawling=is_crawling, has_weapon=has_weapon
                        )
                        
                        box_color = (0, 255, 0) if (is_auth and not is_crawling and not has_weapon) else ((0, 0, 255) if score >= 80 else (0, 165, 255))
                        
                        prefix = "✅ " if is_auth else "⚠️ "
                        if is_crawling: prefix = "🕷️ CRAWL "
                        if has_weapon: prefix = "🔪 LETHAL "
                        
                        label = f"{prefix}ID:{track_id} {display_name} | {score}%"
                        
                        tracked_objects[track_id] = {
                            "color": box_color,
                            "label": label,
                            "score": score,
                            "is_auth": is_auth,
                            "display_name": display_name
                        }
                    else:
                        cached = tracked_objects[track_id]
                        box_color = cached["color"]
                        label = cached["label"]
                        score = cached["score"]
                        is_auth = cached["is_auth"]
                        display_name = cached["display_name"]
                        
                        if not is_auth and not is_crawling and not has_weapon:
                            box_color = (0, 0, 255) if score >= 80 else (0, 165, 255)
                            
                    latest_boxes.append((x1, y1, x2, y2, box_color, label, cx, cy))

                    area = (x2 - x1) * (y2 - y1)
                    if area > largest_area:
                        largest_area = area
                        current_center = (cx, cy)

                    # Telemetry & DB
                    current_time = time.time()
                    if (current_time - last_log_time > 5) and (score >= 70) and not is_auth: 
                        snap_path = str(SNAPSHOTS_DIR / f"alert_{cam_name}_{int(current_time)}.jpg")
                        cv2.imwrite(snap_path, display_frame)
                        db.log_incident(object_type=f"[{cam_name}] {display_name} (ID:{track_id})", threat_score=score, zone_level=zone_level, image_path=snap_path)
                        send_telegram_alert(f"{display_name} ID:{track_id} ({cam_name})", score, snap_path)
                        last_log_time = current_time
                        
            if current_center is not None: last_center = current_center

        # Render Tracking Box
        for (x1, y1, x2, y2, color, label, cx, cy) in latest_boxes:
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.circle(display_frame, (cx, cy), 5, (0, 255, 0), -1)
            if last_center is not None:
                cv2.arrowedLine(display_frame, last_center, (cx, cy), (255, 255, 0), 2, tipLength=0.3)

        ret, buffer = cv2.imencode('.jpg', display_frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

def generate_standby_frames(message, instruction):
    black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(black_frame, message, (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    cv2.putText(black_frame, instruction, (140, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
    ret, buffer = cv2.imencode('.jpg', black_frame)
    while True:
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(1)

@app.route('/video_feed_1')
def video_feed_1():
    if not cam_alpha.ret:
        return Response(
            generate_standby_frames("ALPHA FEED OFFLINE", "ALLOW CAMERA ACCESS"),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    return Response(generate_ai_frames(cam_alpha, "ALPHA"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed_2')
def video_feed_2():
    if not cam_bravo.ret:
        return Response(
            generate_standby_frames("BRAVO FEED OFFLINE", "CONNECT SECOND CAMERA"),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
    
    return Response(generate_ai_frames(cam_bravo, "BRAVO"), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/logs')
def get_logs():
    logs = db.get_recent_logs(limit=15)
    return jsonify([{"timestamp": l[0], "object": l[1], "threat": l[2], "zone": l[3]} for l in logs])

@app.route('/download_secure_report')
def download_secure():
    try:
        report_path = generate_pdf_report()
        if report_path:
            if ENCRYPTION_ENABLED: encrypt_file(report_path)
            return send_file(report_path, as_attachment=True)
        return "Error: Empty Database.", 404
    except Exception as e:
        return f"Report Failed: {e}", 500

if __name__ == '__main__':
    print("🌐 Project Chanakya Web Core ONLINE on Port 5001")
    app.run(host='127.0.0.1', port=5001, debug=True, use_reloader=False)
