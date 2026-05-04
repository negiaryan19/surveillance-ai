# import face_recognition
# import os
# import pickle
# from pathlib import Path

# class FaceRecognizer:
#     def __init__(self, known_faces_dir, encodings_file):
#         self.known_faces_dir = Path(known_faces_dir)
#         self.encodings_file = Path(encodings_file)
#         self.known_encodings = []
#         self.known_names = []
#         self._load_or_build_database()

#     def _load_or_build_database(self):
#         if self.encodings_file.exists():
#             with open(self.encodings_file, "rb") as f:
#                 data = pickle.load(f)
#                 self.known_encodings = data["encodings"]
#                 self.known_names = data["names"]
#             print(f"✅ Loaded {len(self.known_names)} authorized faces.")
#         else:
#             self._build_database()

#     def _build_database(self):
#         print("🔨 Building face database...")
#         self.known_faces_dir.mkdir(parents=True, exist_ok=True)
#         for img_path in self.known_faces_dir.glob("*.jpg"):
#             name = img_path.stem
#             image = face_recognition.load_image_file(str(img_path))
#             encodings = face_recognition.face_encodings(image)
#             if encodings:
#                 self.known_encodings.append(encodings[0])
#                 self.known_names.append(name)
        
#         with open(self.encodings_file, "wb") as f:
#             pickle.dump({"encodings": self.known_encodings, "names": self.known_names}, f)

#     def identify(self, frame, bbox):
#         x1, y1, x2, y2 = bbox
#         face_img = frame[y1:y2, x1:x2]
#         if face_img.size == 0: return None
        
#         rgb_face = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
#         encodings = face_recognition.face_encodings(rgb_face)
        
#         if encodings:
#             matches = face_recognition.compare_faces(self.known_encodings, encodings[0], tolerance=0.5)
#             if True in matches:
#                 return self.known_names[matches.index(True)]
#         return "Unknown"


import face_recognition
import os
import pickle
import cv2
from pathlib import Path

class FaceRecognizer:
    def __init__(self, known_faces_dir, encodings_file):
        self.known_faces_dir = Path(known_faces_dir)
        self.encodings_file = Path(encodings_file)
        self.known_encodings = []
        self.known_names = []
        self._load_or_build_database()

    def _load_or_build_database(self):
        if self.encodings_file.exists():
            with open(self.encodings_file, "rb") as f:
                data = pickle.load(f)
                self.known_encodings = data["encodings"]
                self.known_names = data["names"]
            print(f"✅ Loaded {len(self.known_names)} authorized faces.")
        else:
            self._build_database()

    def _build_database(self):
        print("🔨 Building face database...")
        self.known_faces_dir.mkdir(parents=True, exist_ok=True)
        for img_path in self.known_faces_dir.glob("*.jpg"):
            name = img_path.stem
            image = face_recognition.load_image_file(str(img_path))
            encodings = face_recognition.face_encodings(image)
            if encodings:
                self.known_encodings.append(encodings[0])
                self.known_names.append(name)
        
        with open(self.encodings_file, "wb") as f:
            pickle.dump({"encodings": self.known_encodings, "names": self.known_names}, f)

    def identify(self, frame, bbox):
        x1, y1, x2, y2 = bbox
        face_img = frame[y1:y2, x1:x2]
        if face_img.size == 0: return None
        
        # Convert BGR (OpenCV) to RGB (face_recognition needs RGB)
        rgb_face = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb_face)
        
        if encodings:
            matches = face_recognition.compare_faces(self.known_encodings, encodings[0], tolerance=0.5)
            if True in matches:
                return self.known_names[matches.index(True)]
        return "Unknown"