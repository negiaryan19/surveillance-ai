import cv2
import math
import face_recognition

class LivenessDetector:
    def __init__(self):
        # EAR (Eye Aspect Ratio) Threshold
        self.EAR_THRESHOLD = 0.21  
        self.blink_count = 0
        self.eye_closed = False

    def _calculate_distance(self, p1, p2):
        return math.dist(p1, p2)

    def calculate_ear(self, eye_points):
        # face_recognition gives points as (x, y) tuples
        # Vertical distances
        v1 = self._calculate_distance(eye_points[1], eye_points[5])
        v2 = self._calculate_distance(eye_points[2], eye_points[4])
        # Horizontal distance
        h = self._calculate_distance(eye_points[0], eye_points[3])
        # EAR Formula
        ear = (v1 + v2) / (2.0 * h) if h != 0 else 0
        return ear

    def check_liveness(self, frame):
        """Returns (is_live, current_blink_count)"""
        # Convert to RGB array for face_recognition
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Get face landmarks using the already working face_recognition library
        face_landmarks_list = face_recognition.face_landmarks(rgb_frame)
        
        is_live = False
        
        if face_landmarks_list:
            for face_landmarks in face_landmarks_list:
                # Check if eyes are detected
                if 'left_eye' in face_landmarks and 'right_eye' in face_landmarks:
                    left_eye = face_landmarks['left_eye']
                    right_eye = face_landmarks['right_eye']
                    
                    # Calculate EAR for both eyes
                    ear_left = self.calculate_ear(left_eye)
                    ear_right = self.calculate_ear(right_eye)
                    
                    # Average EAR
                    ear = (ear_left + ear_right) / 2.0
                    
                    # Blink Detection Logic
                    if ear < self.EAR_THRESHOLD:
                        self.eye_closed = True
                    else:
                        if self.eye_closed:  # Eye was closed, now open -> Blink!
                            self.blink_count += 1
                            self.eye_closed = False
                    
                    # Agar 1 bhi blink hui, toh banda ZINDA (Live) hai!
                    if self.blink_count >= 1:
                        is_live = True
                        
        return is_live, self.blink_count

    def reset(self):
        """Blinks ko wapas zero karne ke liye"""
        self.blink_count = 0
        self.eye_closed = False