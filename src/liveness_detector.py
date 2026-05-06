import cv2
import math
import face_recognition

class LivenessDetector:
    def __init__(self):
        # ⚡ Using face_recognition (already installed and working on your Mac!)
        self.EAR_THRESH = 0.22  # Sensitivity Threshold
        self.CONSEC_FRAMES = 1  
        
        self.blink_counter = 0
        self.total_blinks = 0
        self.is_live = False

    def euclidean_distance(self, p1, p2):
        """Calculates distance between two (x, y) points."""
        return math.dist(p1, p2)

    def get_ear(self, eye):
        """Calculates Eye Aspect Ratio (EAR) using 6 eye landmarks."""
        # Vertical distances
        v1 = self.euclidean_distance(eye[1], eye[5])
        v2 = self.euclidean_distance(eye[2], eye[4])
        # Horizontal distance
        h = self.euclidean_distance(eye[0], eye[3])
        
        if h == 0:
            return 0
        return (v1 + v2) / (2.0 * h)

    def check_liveness(self, frame):
        """Analyzes frame for blinks and returns (is_live, total_blinks)."""
        # Convert BGR to RGB for face_recognition
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Find all facial features in the image
        face_landmarks_list = face_recognition.face_landmarks(rgb_frame)

        for face_landmarks in face_landmarks_list:
            # Extract eyes coordinates
            left_eye = face_landmarks.get('left_eye')
            right_eye = face_landmarks.get('right_eye')

            if left_eye and right_eye:
                left_ear = self.get_ear(left_eye)
                right_ear = self.get_ear(right_eye)
                
                # Average EAR of both eyes
                ear = (left_ear + right_ear) / 2.0
                
                # 🐛 DEBUGGER: Live EAR values printed to terminal
                print(f"👀 Live EAR: {ear:.3f} | Need to drop below: {self.EAR_THRESH}")

                # Check if eyes are closed
                if ear < self.EAR_THRESH:
                    self.blink_counter += 1
                else:
                    # Eyes opened after being closed
                    if self.blink_counter >= self.CONSEC_FRAMES:
                        self.total_blinks += 1
                        self.is_live = True
                        print(f"✅ BLINK CAUGHT! Total Blinks: {self.total_blinks}")
                    self.blink_counter = 0
                    
        return self.is_live, self.total_blinks