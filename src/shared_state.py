"""
Shared State
------------
Stores data shared between detection system and Telegram bot.
"""

import threading
from datetime import datetime


class SystemState:
    """Holds the current state of the surveillance system."""
    
    def __init__(self):
        # Lock for thread safety
        self.lock = threading.Lock()
        
        # System status
        self.is_running = True
        self.alerts_paused = False
        
        # Statistics
        self.total_alerts_today = 0
        self.total_people_detected = 0
        self.last_alert_time = None
        self.last_alert_level = None
        
        # Current frame (for snapshot command)
        self.current_frame = None
        
        # Zone info
        self.zone_coordinates = (0, 0, 1000, 800)
        
        # Recent alerts log
        self.recent_alerts = []
        self.max_recent = 5
    
    def update_frame(self, frame):
        """Update current camera frame."""
        with self.lock:
            self.current_frame = frame.copy() if frame is not None else None
    
    def get_frame(self):
        """Get latest camera frame."""
        with self.lock:
            return self.current_frame.copy() if self.current_frame is not None else None
    
    def add_alert(self, level, behavior, people_count):
        """Record a new alert."""
        with self.lock:
            self.total_alerts_today += 1
            self.last_alert_time = datetime.now()
            self.last_alert_level = level
            
            alert_info = {
                "time": datetime.now().strftime("%I:%M:%S %p"),
                "level": level,
                "behavior": behavior,
                "people": people_count
            }
            
            self.recent_alerts.append(alert_info)
            if len(self.recent_alerts) > self.max_recent:
                self.recent_alerts.pop(0)
    
    def pause_alerts(self):
        """Stop sending alerts."""
        with self.lock:
            self.alerts_paused = True
    
    def resume_alerts(self):
        """Resume sending alerts."""
        with self.lock:
            self.alerts_paused = False
    
    def is_paused(self):
        """Check if alerts are paused."""
        with self.lock:
            return self.alerts_paused
    
    def get_stats(self):
        """Get system statistics."""
        with self.lock:
            return {
                "total_alerts": self.total_alerts_today,
                "total_people": self.total_people_detected,
                "last_alert": self.last_alert_time,
                "last_level": self.last_alert_level,
                "is_paused": self.alerts_paused,
                "recent_alerts": list(self.recent_alerts)
            }


# Create one shared instance for the whole project
system_state = SystemState()