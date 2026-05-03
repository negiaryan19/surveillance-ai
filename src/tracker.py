"""
Object Tracker - Intelligence Layer
----------------------------------
Assigns unique IDs to people and remembers them across frames.
"""

import math

class BehaviorTracker:
    def __init__(self, max_disappeared=40, max_history=30):
        self.next_id = 1
        self.objects = {}  # Stores {id: (center_x, center_y)}
        self.disappeared = {}  # Tracks how many frames an ID was missing
        self.history = {}  # Stores movement path for behavior analysis
        self.max_disappeared = max_disappeared
        self.max_history = max_history  # Fix 1: Limit memory usage

    def register(self, centroid):
        """Assign a new ID to a new person."""
        self.objects[self.next_id] = centroid
        self.disappeared[self.next_id] = 0
        self.history[self.next_id] = [centroid]
        self.next_id += 1

    def deregister(self, object_id):
        """Remove ID if they are gone for too long."""
        del self.objects[object_id]
        del self.disappeared[object_id]
        del self.history[object_id]

    def update(self, input_centroids):
        """Matches new detections with existing IDs using distance math."""
        if not input_centroids:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)
            return self.objects

        if not self.objects:
            for centroid in input_centroids:
                self.register(centroid)
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())
            
            # Keep track of which existing IDs were matched
            matched_ids = set()

            # Distance calculation logic
            for i, obj_centroid in enumerate(object_centroids):
                if not input_centroids: 
                    break # No more new detections to match

                # Find the closest new detection to the old position
                distances = [math.hypot(obj_centroid[0]-c[0], obj_centroid[1]-c[1]) for c in input_centroids]
                min_dist_idx = distances.index(min(distances))

                if distances[min_dist_idx] < 60:  # Pixel threshold
                    obj_id = object_ids[i]
                    self.objects[obj_id] = input_centroids[min_dist_idx]
                    self.disappeared[obj_id] = 0
                    
                    self.history[obj_id].append(input_centroids[min_dist_idx])
                    # Fix 1: Keep only the most recent history to prevent memory leak
                    if len(self.history[obj_id]) > self.max_history:
                        self.history[obj_id].pop(0)
                        
                    matched_ids.add(obj_id)
                    input_centroids.pop(min_dist_idx)

            # Fix 2: Increment disappearance for IDs that were NOT matched in this frame
            for obj_id in object_ids:
                if obj_id not in matched_ids:
                    self.disappeared[obj_id] += 1
                    if self.disappeared[obj_id] > self.max_disappeared:
                        self.deregister(obj_id)

            # Register any remaining new detections
            for centroid in input_centroids:
                self.register(centroid)

        return self.objects

    def get_behavior(self, obj_id):
        """Analyze if ID is loitering or moving fast."""
        if obj_id not in self.history or len(self.history[obj_id]) < 5:
            return "Analyzing..."
        
        # Simple speed check based on distance moved (using recent history)
        path = self.history[obj_id]
        dist = math.hypot(path[-1][0] - path[0][0], path[-1][1] - path[0][1])
        
        if dist < 15: return "Standing Still"
        return "Moving"