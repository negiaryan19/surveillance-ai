"""
Anomaly Detector
----------------
Detects unusual behavior patterns. Uses tracking data + statistical analysis.
"""
import numpy as np
from collections import deque

class AnomalyDetector:
    def __init__(self):
        self.behavior_history = {}  # Per person tracking
        self.window_size = 30

    def analyze(self, person_id, bbox, position):
        # Initialize history for new person
        if person_id not in self.behavior_history:
            self.behavior_history[person_id] = {
                "positions": deque(maxlen=self.window_size),
                "bbox_sizes": deque(maxlen=self.window_size),
                "velocities": deque(maxlen=self.window_size)
            }
            
        history = self.behavior_history[person_id]
        
        # Calculate features
        x, y = position
        x1, y1, x2, y2 = bbox
        bbox_height = y2 - y1
        bbox_width = x2 - x1
        bbox_ratio = bbox_height / max(bbox_width, 1)
        
        # Calculate velocity
        if history["positions"]:
            last_x, last_y = history["positions"][-1]
            velocity = np.sqrt((x - last_x)**2 + (y - last_y)**2)
        else:
            velocity = 0
            
        # Update history
        history["positions"].append((x, y))
        history["bbox_sizes"].append((bbox_width, bbox_height))
        history["velocities"].append(velocity)
        
        # Need enough data to analyze
        if len(history["velocities"]) < 10:
            return False, None, 0
            
        return self._detect_patterns(history, bbox_ratio, velocity)

    def _detect_patterns(self, history, bbox_ratio, velocity):
        velocities = list(history["velocities"])
        
        # 1. CRAWLING - bbox is much wider than tall
        if bbox_ratio < 0.6:
            return True, "CRAWLING DETECTED", "HIGH"
            
        # 2. RUNNING/FLEEING - very high velocity
        avg_velocity = np.mean(velocities[-10:])
        if avg_velocity > 40: # Threshold for running
            return True, "RUNNING FAST", "HIGH"
            
        # 3. ERRATIC MOVEMENT - high velocity variance
        velocity_std = np.std(velocities[-10:])
        if velocity_std > 25:
            return True, "ERRATIC MOVEMENT", "MEDIUM"

        return False, None, 0

    def reset_person(self, person_id):
        if person_id in self.behavior_history:
            del self.behavior_history[person_id]