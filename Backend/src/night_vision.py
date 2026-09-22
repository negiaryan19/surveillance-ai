"""Low-light detection and CLAHE enhancement (one instance per camera)."""

import cv2
import numpy as np


class NightVision:
    def __init__(self, threshold=70):
        # Mean grey level below which CLAHE enhancement kicks in. 85 flagged ordinary
        # indoor scenes with dark clothing as "night"; 70 keeps it for genuinely dim frames.
        self.threshold = threshold

    def is_low_light(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        avg_brightness = np.mean(gray)
        return avg_brightness < self.threshold

    def enhance(self, frame):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        lightness, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_lab = cv2.merge([clahe.apply(lightness), a, b])
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
