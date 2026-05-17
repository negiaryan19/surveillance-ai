import face_recognition
import cv2
import os
import glob
import pickle

class FaceRecognizer:
    def __init__(self, db_path, encoding_path):
        self.db_path = db_path
        self.encoding_path = encoding_path
        self.known_encodings = []
        self.known_names = []
        self.load_known_faces()

    def load_known_faces(self):
        """Database se photos load karke unke encodings banata hai."""
        
        # 1. Check if encoding file already exists
        if os.path.exists(self.encoding_path):
            with open(self.encoding_path, 'rb') as f:
                data = pickle.load(f)
                self.known_encodings = data["encodings"]
                self.known_names = data["names"]
            print(f"✅ Loaded {len(self.known_names)} authorized faces from cache.")
        else:
            print("🔨 Building face database... (First time setup)")
            
            # 2. Iterate through image folder
            for image_path in glob.glob(os.path.join(self.db_path, "*")):
                # DEBUG: Check if file is being found
                print(f"DEBUG: Found file {image_path}")
                
                if image_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                    name = os.path.basename(image_path).split('.')[0]
                    
                    try:
                        image = face_recognition.load_image_file(image_path)
                        encodings = face_recognition.face_encodings(image)
                        
                        if len(encodings) > 0:
                            self.known_encodings.append(encodings[0])
                            self.known_names.append(name)
                        else:
                            print(f"⚠️ Warning: No face found in {image_path}")
                    except Exception as e:
                        print(f"❌ Error processing {image_path}: {e}")
            
            # 3. Save encodings for next time
            if self.known_encodings:
                with open(self.encoding_path, 'wb') as f:
                    pickle.dump({"encodings": self.known_encodings, "names": self.known_names}, f)
                print(f"✅ Database built successfully. Loaded {len(self.known_names)} faces.")
            else:
                print("❌ ERROR: No faces were loaded. Check your database folder!")

    def identify(self, frame, bbox):
        """Camera frame mein face ko identify karta hai."""
        x1, y1, x2, y2 = bbox
        
        # Safe crop logic
        h, w, _ = frame.shape
        y1, y2 = max(0, y1), min(h, y2)
        x1, x2 = max(0, x1), min(w, x2)
        
        face_img = frame[y1:y2, x1:x2]
        if face_img.size == 0:
            return "Unknown"
            
        rgb_face = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb_face)
        
        if len(encodings) > 0:
            # UPDATED: Tolerance 0.6 for better recognition accuracy
            matches = face_recognition.compare_faces(self.known_encodings, encodings[0], tolerance=0.6)
            
            if True in matches:
                first_match_index = matches.index(True)
                return self.known_names[first_match_index]
        
        return "Unknown"