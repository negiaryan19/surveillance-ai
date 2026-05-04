import numpy as np
import threading
import time
import os

class AudioDetector:
    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.is_running = False
        # Note: Real implementation uses YAMNet, for now we use 
        # Decibel-level peak detection for instant prototype testing.
        self.threshold = 0.5 

    def start(self):
        self.is_running = True
        threading.Thread(target=self._listen, daemon=True).start()
        print("🎤 Audio Surveillance Active (Listening for Gunshots/Screams)...")

    def _listen(self):
        # Mock logic for prototype: Detects sudden loud noises
        while self.is_running:
            # Yahan actual mic input logic aayega
            time.sleep(1) 

    def trigger_mock_event(self, event_type="GUNSHOT"):
        """Testing ke liye: Manual trigger"""
        self.alert_callback(f"🔊 AUDIO ALERT: {event_type} Detected!")