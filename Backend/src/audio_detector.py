"""
Project Chanakya - Audio Intelligence (YAMNet)
----------------------------------------------
Listens to the microphone in the background.
Detects Gunshots, Screams, Sirens, and Breaking Glass.
"""

import pyaudio
import numpy as np
import tensorflow_hub as hub
import csv
import threading
import time

class AudioDetector:
    def __init__(self, alert_callback=None):
        self.alert_callback = alert_callback
        print("🔊 Initializing YAMNet Audio Defense Model...")
        
        # Load the YAMNet model from TensorFlow Hub
        self.model = hub.load('https://tfhub.dev/google/yamnet/1')
        
        # Load the class map (translates numbers to words like 'Gunshot')
        class_map_path = self.model.class_map_path().numpy().decode('utf-8')
        self.class_names = []
        with open(class_map_path) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                self.class_names.append(row['display_name'])
                
        # DRDO Target Sounds (High Priority Threats)
        self.THREAT_SOUNDS = ["Gunshot, gunfire", "Screaming", "Siren", "Glass", "Explosion"]
        
        # Setup Microphone Stream
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=16000,
                                  input=True,
                                  frames_per_buffer=16000) # 1-second audio chunks
        self.is_running = False

    def start(self):
        """Starts the audio listening in a separate background thread."""
        self.is_running = True
        threading.Thread(target=self._listen, daemon=True).start()
        print("✅ Audio Detection ONLINE. Listening for threats...")

    def _listen(self):
        while self.is_running:
            try:
                # 1. Read 1 second of audio
                data = self.stream.read(16000, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                
                # 2. Normalize audio for the AI model
                waveform = audio_data / 32768.0 
                
                # 3. Predict the sound
                scores, embeddings, spectrogram = self.model(waveform)
                scores_np = scores.numpy()
                infered_class = self.class_names[scores_np.mean(axis=0).argmax()]
                
                # 4. Check if it's a military threat
                for threat in self.THREAT_SOUNDS:
                    if threat.lower() in infered_class.lower():
                        print(f"\n🚨 [AUDIO THREAT DETECTED]: {infered_class.upper()}")
                        
                        # Trigger the Telegram Alert callback if provided
                        if self.alert_callback:
                            self.alert_callback(f"🔊 Audio Threat: {infered_class.upper()}")
                        
                        time.sleep(5) # 5-second cooldown to avoid spamming
                        break
                        
            except Exception as e:
                pass

    def stop(self):
        """Safely shuts down the microphone."""
        self.is_running = False
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()