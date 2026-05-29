import math

import cv2
import face_recognition


class EmotionDetector:
    """Reusable facial-landmark emotion signal detector.

    This is intentionally lightweight: it uses existing face_recognition
    landmarks, so the project gains an emotion module without adding another
    heavyweight model dependency.
    """

    def detect(self, frame, bbox=None):
        face_image = self._crop_face(frame, bbox)
        if face_image is None or face_image.size == 0:
            return self._result("Unknown", 0, {})

        try:
            rgb_face = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
            landmarks_list = face_recognition.face_landmarks(rgb_face)
        except Exception:
            return self._result("Unknown", 0, {})

        if not landmarks_list:
            return self._result("Unknown", 0, {})

        signals = self._extract_signals(landmarks_list[0])
        emotion, confidence = self._classify(signals)
        return self._result(emotion, confidence, signals)

    def _crop_face(self, frame, bbox):
        if bbox is None:
            return frame

        x1, y1, x2, y2 = bbox
        height, width = frame.shape[:2]
        pad_x = max(8, int((x2 - x1) * 0.18))
        pad_y = max(8, int((y2 - y1) * 0.18))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(width, x2 + pad_x)
        y2 = min(height, y2 + pad_y)
        return frame[y1:y2, x1:x2]

    def _extract_signals(self, landmarks):
        left_eye = landmarks.get("left_eye", [])
        right_eye = landmarks.get("right_eye", [])
        top_lip = landmarks.get("top_lip", [])
        bottom_lip = landmarks.get("bottom_lip", [])
        chin = landmarks.get("chin", [])
        left_brow = landmarks.get("left_eyebrow", [])
        right_brow = landmarks.get("right_eyebrow", [])

        eye_ratio = self._avg([self._eye_aspect_ratio(left_eye), self._eye_aspect_ratio(right_eye)])
        mouth_open = self._mouth_open_ratio(top_lip, bottom_lip)
        mouth_width = self._mouth_width_ratio(top_lip, bottom_lip, chin)
        brow_gap = self._brow_gap_ratio(left_eye + right_eye, left_brow + right_brow, chin)

        return {
            "eye_ratio": round(eye_ratio, 3),
            "mouth_open": round(mouth_open, 3),
            "mouth_width": round(mouth_width, 3),
            "brow_gap": round(brow_gap, 3),
        }

    def _classify(self, signals):
        eye_ratio = signals.get("eye_ratio", 0)
        mouth_open = signals.get("mouth_open", 0)
        mouth_width = signals.get("mouth_width", 0)
        brow_gap = signals.get("brow_gap", 0)

        if eye_ratio and eye_ratio < 0.18:
            return "Tired", 78
        if mouth_open > 0.34 and eye_ratio > 0.24:
            return "Surprised", 82
        if mouth_width > 0.44 and mouth_open > 0.11:
            return "Happy", 74
        if 0 < brow_gap < 0.15 and mouth_open < 0.16:
            return "Focused", 70
        return "Neutral", 66

    def _eye_aspect_ratio(self, eye):
        if len(eye) < 6:
            return 0
        vertical_1 = self._distance(eye[1], eye[5])
        vertical_2 = self._distance(eye[2], eye[4])
        horizontal = self._distance(eye[0], eye[3])
        if horizontal == 0:
            return 0
        return (vertical_1 + vertical_2) / (2.0 * horizontal)

    def _mouth_open_ratio(self, top_lip, bottom_lip):
        if len(top_lip) < 12 or len(bottom_lip) < 12:
            return 0
        upper_center = self._center(top_lip[8:11])
        lower_center = self._center(bottom_lip[8:11])
        mouth_width = self._distance(top_lip[0], top_lip[6])
        if mouth_width == 0:
            return 0
        return self._distance(upper_center, lower_center) / mouth_width

    def _mouth_width_ratio(self, top_lip, bottom_lip, chin):
        if len(top_lip) < 7 or len(chin) < 17:
            return 0
        face_width = self._distance(chin[0], chin[16])
        mouth_width = self._distance(top_lip[0], top_lip[6])
        if face_width == 0:
            return 0
        return mouth_width / face_width

    def _brow_gap_ratio(self, eyes, brows, chin):
        if not eyes or not brows or len(chin) < 9:
            return 0
        face_height = max(1, self._distance(chin[8], self._center(brows)))
        return abs(self._center(brows)[1] - self._center(eyes)[1]) / face_height

    def _avg(self, values):
        numbers = [value for value in values if value > 0]
        return sum(numbers) / len(numbers) if numbers else 0

    def _center(self, points):
        if not points:
            return (0, 0)
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def _distance(self, point_a, point_b):
        return math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1])

    def _result(self, emotion, confidence, signals):
        return {
            "emotion": emotion,
            "confidence": confidence,
            "signals": signals,
        }
