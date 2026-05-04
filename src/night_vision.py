import cv2
import numpy as np

class NightVision:
    def __init__(self, threshold=85):
        self.threshold = threshold # Brightness level jiske niche Night Mode on hoga

    def is_low_light(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        avg_brightness = np.mean(gray)
        return avg_brightness < self.threshold

    def enhance(self, frame):
        # Image ko andhere mein saaf karne ka logic
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced_lab = cv2.merge([l, a, b])
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)