import cv2
import threading
import time

class CameraStream:
    def __init__(self, source):
        self.source = source
        self.cap = cv2.VideoCapture(source)
        self.grabbed, self.frame = self.cap.read()
        self.started = False
        self.read_lock = threading.Lock()

    def start(self):
        if self.started:
            return None
        self.started = True
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.start()
        return self

    def update(self):
        while self.started:
            grabbed, frame = self.cap.read()
            with self.read_lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.01) # CPU usage control

    def read(self):
        with self.read_lock:
            frame = self.frame.copy() if self.grabbed else None
        return frame

    def stop(self):
        self.started = False
        self.thread.join()
        self.cap.release()