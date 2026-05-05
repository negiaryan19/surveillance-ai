import sys
from pathlib import Path
from flask import Flask, render_template, Response
import cv2
import atexit

# Set up paths so Flask can find your AI Engine in the 'src' folder
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# Import your AI Brains
from ultralytics import YOLO
from src.threat_assessor import ThreatAssessor
from src.face_recognizer import FaceRecognizer
from src.liveness_detector import LivenessDetector
from config.settings import MODEL_PATH, CONFIDENCE_LIMIT

app = Flask(__name__)

# Initialize Camera
camera = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

def release_camera():
    if camera.isOpened():
        camera.release()
        print("📷 Camera safely released.")
atexit.register(release_camera)

# 🧠 INITIALIZE AI ENGINE
print("🧠 Loading Project Chanakya AI Core into Web Server...")
model = YOLO(MODEL_PATH)
face_id = FaceRecognizer(str(BASE_DIR / "database/known_faces"), str(BASE_DIR / "database/face_encodings.pkl"))
liveness_detector = LivenessDetector()
threat_engine = ThreatAssessor()

THREAT_CLASSES = {
    0: {"name": "Person", "color": (0, 255, 255)},
    2: {"name": "Car", "color": (0, 0, 255)},
    3: {"name": "Motorcycle", "color": (0, 0, 255)},
    16: {"name": "Dog", "color": (0, 255, 0)}
}

def generate_frames():
    """Smart Loop: Checks blink every frame, but runs heavy AI every 5 frames."""
    frame_count = 0
    latest_boxes = [] # Memory to store boxes so they don't flicker

    while True:
        success, raw_frame = camera.read()
        if not success:
            break
            
        frame = cv2.resize(raw_frame, (640, 480))
        frame_count += 1
        
        # ⚡ 1. FAST OPERATION: Check Liveness on EVERY single frame (Catches the blink!)
        is_live, blinks = liveness_detector.check_liveness(frame)
        cv2.putText(frame, f"Blinks: {blinks}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        
        # 🧠 2. HEAVY OPERATION: Run YOLO & Face ID only every 5 frames (Saves FPS!)
        if frame_count % 5 == 0:
            latest_boxes = [] # Clear memory for new detection
            detections = model(frame, verbose=False)
            
            for detection in detections:
                for box in detection.boxes:
                    class_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    
                    if class_id in THREAT_CLASSES and conf > CONFIDENCE_LIMIT:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        obj_type = THREAT_CLASSES[class_id]["name"]
                        box_color = THREAT_CLASSES[class_id]["color"]
                        
                        face_status = "UNKNOWN"
                        is_auth = False
                        
                        # Face ID
                        if class_id == 0:
                            identity = face_id.identify(frame, (x1, y1, x2, y2))
                            if identity != "Unknown" and identity is not None:
                                face_status = "KNOWN" if is_live else "SPOOF"
                                is_auth = is_live
                                box_color = (0, 255, 0) if is_auth else (0, 165, 255)
                                
                        # Threat Score
                        score, cat, reasons = threat_engine.calculate_threat(
                            zone_level="SAFE", object_type=obj_type, face_status=face_status, is_anomaly=False
                        )
                        
                        label = f"{'✅ AUTH' if is_auth else f'⚠️ {cat}'} | Threat: {score}%"
                        # Store the result in memory
                        latest_boxes.append((x1, y1, x2, y2, box_color, label))

        # 🎨 3. DRAW: Paint the stored boxes on the current fast frame
        for (x1, y1, x2, y2, color, label) in latest_boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # 🌐 4. Send to Browser
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("🌐 Project Chanakya Web Core ONLINE on Port 5001")
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)