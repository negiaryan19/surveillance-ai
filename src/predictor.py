"""
Movement Predictor - Phase 2.2
------------------------------
Predicts the future position of intruders to provide early warnings.
"""
import numpy as np
from collections import defaultdict

class MovementPredictor:
    def __init__(self):
        self.history = defaultdict(list)
        self.max_history = 10

    def update(self, person_id, x, y):
        self.history[person_id].append((x, y))
        if len(self.history[person_id]) > self.max_history:
            self.history[person_id].pop(0)

    def predict_next_position(self, person_id, frames_ahead=15):
        positions = self.history.get(person_id, [])
        if len(positions) < 3:
            return None

        # Calculate average velocity (dx, dy)
        velocities_x = []
        velocities_y = []
        for i in range(1, len(positions)):
            velocities_x.append(positions[i][0] - positions[i-1][0])
            velocities_y.append(positions[i][1] - positions[i-1][1])

        avg_vx = np.mean(velocities_x)
        avg_vy = np.mean(velocities_y)

        last_x, last_y = positions[-1]
        pred_x = int(last_x + avg_vx * frames_ahead)
        pred_y = int(last_y + avg_vy * frames_ahead)
        return (pred_x, pred_y)

    def get_direction(self, person_id):
        positions = self.history.get(person_id, [])
        if len(positions) < 5:
            return "Analyzing..."
        
        start_x, start_y = positions[0]
        end_x, end_y = positions[-1]
        dx, dy = end_x - start_x, end_y - start_y

        if abs(dx) < 10 and abs(dy) < 10: return "Stationary"
        
        # FIX: Removed emojis to stop OpenCV from showing ??????
        if abs(dx) > abs(dy):
            return "East ->" if dx > 0 else "West <-"
        else:
            return "South v" if dy > 0 else "North ^"