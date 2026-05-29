import face_recognition
import cv2
import os
import pickle

class FaceRecognizer:
    def __init__(self, db_path, encoding_path):
        self.db_path = db_path
        self.encoding_path = encoding_path
        self.known_encodings = []
        self.known_names = []
        self.load_known_faces()

    def load_known_faces(self):
        """Loads known faces from loose files or person-wise folders."""
        image_files = self._scan_known_face_images()
        signature = self._database_signature(image_files)
        
        if os.path.exists(self.encoding_path):
            with open(self.encoding_path, 'rb') as f:
                data = pickle.load(f)
            if data.get("signature") == signature:
                self.known_encodings = data["encodings"]
                self.known_names = data["names"]
                print(f"✅ Loaded {len(self.known_names)} authorized faces from cache.")
                return

            print("🔁 Known face database changed. Rebuilding encodings...")
        else:
            print("🔨 Building face database... (First time setup)")
            
        for name, image_path in image_files:
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
            
        if self.known_encodings:
            with open(self.encoding_path, 'wb') as f:
                pickle.dump(
                    {"encodings": self.known_encodings, "names": self.known_names, "signature": signature},
                    f
                )
            print(f"✅ Database built successfully. Loaded {len(self.known_names)} faces.")
        else:
            print("❌ ERROR: No faces were loaded. Check your database folder!")

    def _scan_known_face_images(self):
        if not os.path.isdir(self.db_path):
            os.makedirs(self.db_path, exist_ok=True)
            return []

        image_files = []
        valid_extensions = ('.png', '.jpg', '.jpeg')

        for root, dirs, files in os.walk(self.db_path):
            dirs[:] = [folder for folder in dirs if not folder.startswith(".")]
            for file_name in files:
                if file_name.startswith(".") or not file_name.lower().endswith(valid_extensions):
                    continue

                image_path = os.path.join(root, file_name)
                relative_root = os.path.relpath(root, self.db_path)
                if relative_root == ".":
                    name = os.path.splitext(file_name)[0]
                else:
                    name = os.path.basename(root)

                image_files.append((name.replace("_", " ").strip(), image_path))

        return sorted(image_files, key=lambda item: item[1])

    def _database_signature(self, image_files):
        if not image_files:
            return {"count": 0, "latest_mtime": 0}

        latest_mtime = max(os.path.getmtime(image_path) for _, image_path in image_files)
        return {"count": len(image_files), "latest_mtime": latest_mtime}

    def identify(self, frame, bbox):
        """Camera frame mein face ko identify karta hai."""
        if not self.known_encodings:
            return "Unknown"

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
