"""
Black Box - Auto Video Recorder (Phase 2.4)
-------------------------------------------
Keeps a rolling buffer of frames. On alert, saves 5s before and 5s after the incident.
"""

import cv2
import threading
from datetime import datetime
from collections import deque
from pathlib import Path

class VideoRecorder:
    def __init__(self, output_dir, fps=20, pre_buffer_sec=5, post_buffer_sec=5):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        
        self.pre_buffer = deque(maxlen=fps * pre_buffer_sec)
        self.post_buffer_target = fps * post_buffer_sec
        self.current_post_frames = []
        
        self.recording_active = False
        self.incident_prefix = ""

    def update(self, frame):
        if not self.recording_active:
            self.pre_buffer.append(frame.copy())
        else:
            self.current_post_frames.append(frame.copy())
            if len(self.current_post_frames) >= self.post_buffer_target:
                self._save_video()

    def trigger(self, prefix):
        if not self.recording_active:
            self.recording_active = True
            self.incident_prefix = prefix
            self.current_post_frames = []
            print("🎥 [Black Box] Alert Triggered! Capturing live incident...")

    def _save_video(self):
        frames_to_save = list(self.pre_buffer) + self.current_post_frames
        prefix = self.incident_prefix
        
        self.recording_active = False
        self.current_post_frames = []
        
        threading.Thread(
            target=self._write_to_disk, 
            args=(frames_to_save, prefix), 
            daemon=True
        ).start()

    def _write_to_disk(self, frames, prefix):
        if not frames: return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"{prefix}_{ts}.mp4"
        
        h, w = frames[0].shape[:2]
        out = cv2.VideoWriter(str(filepath), cv2.VideoWriter_fourcc(*'mp4v'), self.fps, (w, h))
        
        for f in frames:
            out.write(f)
        out.release()
        print(f"\n✅ [Black Box] Evidence Secured: {filepath.name}\n")