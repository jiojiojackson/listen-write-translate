import sys
import soundcard as sc
import numpy as np
import wave
from io import BytesIO
import os
from groq import Groq
from dotenv import load_dotenv
import queue
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QTextEdit, QLabel, QSplitter, QPushButton,
                            QGridLayout, QFrame, QSlider)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QResizeEvent
import pythoncom  # Add this import at the top with other imports


class AudioWorker(QThread):
    audio_ready = pyqtSignal(BytesIO)
    error = pyqtSignal(str)
    sound_level = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.running = False
        self.threshold = 0.01  # Default threshold
        self.buffer = []  # Store audio segments
        self.silence_duration = 0
        self.SILENCE_THRESHOLD = 1.0  # 1 second of silence indicates sentence end
    
    def calculate_rms(self, audio_data):
        return np.sqrt(np.mean(np.square(audio_data)))
        
    def run(self):
        pythoncom.CoInitialize()  # Initialize COM for this thread
        try:
            loopback = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
            while self.running:
                with loopback.recorder(samplerate=48000) as mic:
                    data = mic.record(numframes=48000)  # Record smaller chunks (1 second)
                    if not self.running:
                        break
                        
                    rms = self.calculate_rms(data)
                    self.sound_level.emit(rms)
                    
                    if rms > self.threshold:
                        self.buffer.append(data)
                        self.silence_duration = 0
                    else:
                        self.silence_duration += 1
                        
                        # If we have buffered data and detected sentence end
                        if len(self.buffer) > 0 and self.silence_duration >= self.SILENCE_THRESHOLD:
                            # Combine buffered audio segments
                            complete_audio = np.concatenate(self.buffer)
                            wav_buffer = BytesIO()
                            with wave.open(wav_buffer, 'wb') as wav:
                                wav.setnchannels(2)
                                wav.setsampwidth(2)
                                wav.setframerate(48000)
                                wav.writeframes((complete_audio * 32767).astype(np.int16).tobytes())
                            wav_buffer.seek(0)
                            
                            if self.running:
                                self.audio_ready.emit(wav_buffer)
                            
                            # Clear buffer after sending
                            self.buffer = []
                            self.silence_duration = 0
                    
        except Exception as e:
            self.error.emit(f"Recording Error: {str(e)}")
        finally:
            pythoncom.CoUninitialize()  # Cleanup COM
            
    def start_recording(self):
        self.buffer = []
        self.silence_duration = 0
        self.running = True
        self.start()
            
    def stop(self):
        self.running = False
        self.buffer = []
        self.wait()

class TranscriptionWorker(QThread):
    text_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, groq_client):
        super().__init__()
        self.client = groq_client
        self.queue = queue.Queue()
        self.running = True

    def process_audio(self, audio_buffer):
        print("Queuing audio for transcription")
        self.queue.put(audio_buffer)

    def run(self):
        print("TranscriptionWorker started")
        while self.running:
            try:
                if not self.queue.empty():
                    audio_buffer = self.queue.get()
                    print("Processing audio data")
                    transcription = self.client.audio.transcriptions.create(
                        file=("audio.wav", audio_buffer.read()),
                        model="whisper-large-v3-turbo",
                        response_format="verbose_json"
                    )
                    if transcription.text.strip():
                        print(f"Emitting transcription: {transcription.text}")
                        self.text_ready.emit(transcription.text)
                else:
                    self.msleep(100)
            except Exception as e:
                print(f"TranscriptionWorker error: {e}")
                self.error.emit(f"Transcription Error: {str(e)}")

    def stop(self):
        print("Stopping transcription worker...")
        self.running = False
        self.wait()

    def start_processing(self):
        print("Starting transcription processing...")
        self.running = True
        self.start()

class MainWindow(QMainWindow):
    def __init__(self, audio_worker=None, transcription_worker=None):
        super().__init__()
        self.running = False
        self.audio_worker = audio_worker
        self.transcription_worker = transcription_worker
        
        # Initialize worker status
        self.audio_worker_active = False
        self.transcription_worker_active = False
        
        self.init_ui()
        # Move threshold update to after UI initialization
        if self.audio_worker:
            self.update_threshold()
    def keyPressEvent(self, event):
        # Check if the pressed key is space
        if event.key() == Qt.Key.Key_Space:
            # Trigger the same action as clicking the start/stop button
            self.toggle_recording()

    def init_ui(self):
        self.setWindowTitle("Real-time Transcription & Translation")
        self.setGeometry(100, 100, 1200, 800)
        
        # Main widget and layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.grid_layout = QGridLayout(self.main_widget)
        
        # Control panel
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        
        # Start/Stop button
        self.start_stop_btn = QPushButton("Start")
        self.start_stop_btn.setMinimumHeight(40)
        self.start_stop_btn.setStyleSheet("""
            QPushButton { 
                font-size: 14px; 
                padding: 5px 15px;
                border-radius: 5px;
                background-color: #4CAF50;
                color: white;
            }
        """)
        self.start_stop_btn.clicked.connect(self.toggle_recording)
        control_layout.addWidget(self.start_stop_btn)
        
        # Add tooltip to show spacebar shortcut
        self.start_stop_btn.setToolTip("Click or press Space to Start/Stop")

        # Sound level indicator
        self.sound_indicator = QLabel("Sound Level: Silent")
        self.sound_indicator.setStyleSheet("color: gray;")
        control_layout.addWidget(self.sound_indicator)
        
        # Threshold control
        threshold_container = QWidget()
        threshold_layout = QHBoxLayout(threshold_container)
        threshold_layout.addWidget(QLabel("Threshold:"))
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setRange(0, 100)
        self.threshold_slider.setValue(10)
        self.threshold_slider.valueChanged.connect(self.update_threshold)
        threshold_layout.addWidget(self.threshold_slider)
        control_layout.addWidget(threshold_container)
        
        # Set up text panels
        transcript_container = QWidget()
        transcript_layout = QVBoxLayout(transcript_container)
        transcript_label = QLabel("Transcription")
        transcript_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.transcript_panel = QTextEdit()
        self.transcript_panel.setReadOnly(True)
        self.transcript_panel.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Sunken)
        transcript_layout.addWidget(transcript_label)
        transcript_layout.addWidget(self.transcript_panel)
        
        translation_container = QWidget()
        translation_layout = QVBoxLayout(translation_container)
        translation_label = QLabel("Translation")
        translation_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.translation_panel = QTextEdit()
        self.translation_panel.setReadOnly(True)
        self.translation_panel.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Sunken)
        translation_layout.addWidget(translation_label)
        translation_layout.addWidget(self.translation_panel)
        
        # Status panel
        self.status_container = QWidget()
        status_layout = QVBoxLayout(self.status_container)
        
        status_header = QWidget()
        header_layout = QHBoxLayout(status_header)
        
        self.status_label = QLabel("Status")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.minimize_btn = QPushButton("_")
        self.minimize_btn.setMaximumWidth(30)
        self.minimize_btn.clicked.connect(self.toggle_status)
        
        header_layout.addWidget(self.status_label)
        header_layout.addWidget(self.minimize_btn)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        
        status_layout.addWidget(status_header)
        status_layout.addWidget(self.status_text)
        
        # Initial layout setup
        self.grid_layout.addWidget(control_panel, 0, 0, 1, 2)
        self.transcript_container = transcript_container
        self.translation_container = translation_container
        self.update_layout()

    def toggle_status(self):
        """Toggle the visibility of the status text panel"""
        if hasattr(self, 'status_text') and hasattr(self, 'minimize_btn'):
            if self.status_text.isVisible():
                self.status_text.hide()
                self.minimize_btn.setText("+")
                self.status_container.setMaximumHeight(30)
            else:
                self.status_text.show()
                self.minimize_btn.setText("_")
                self.status_container.setMaximumHeight(150)
            print("Status panel visibility toggled")

    def update_layout(self):
        """Update the layout based on window size"""
        try:
            # Remove widgets from grid (except control panel)
            for i in reversed(range(self.grid_layout.count())):
                item = self.grid_layout.itemAt(i)
                if item and item.widget() != self.grid_layout.itemAt(0).widget():
                    self.grid_layout.removeItem(item)

            # Check window width for layout decision
            if self.width() < 800:  # Vertical layout
                self.grid_layout.addWidget(self.transcript_container, 1, 0, 1, 2)
                self.grid_layout.addWidget(self.translation_container, 2, 0, 1, 2)
                self.grid_layout.addWidget(self.status_container, 3, 0, 1, 2)
            else:  # Horizontal layout
                splitter = QSplitter(Qt.Orientation.Horizontal)
                splitter.addWidget(self.transcript_container)
                splitter.addWidget(self.translation_container)
                self.grid_layout.addWidget(splitter, 1, 0, 1, 2)
                self.grid_layout.addWidget(self.status_container, 2, 0, 1, 2)

            print("Layout updated successfully")
        except Exception as e:
            print(f"Layout update error: {e}")

    def resizeEvent(self, event):
        """Handle window resize events"""
        super().resizeEvent(event)
        self.update_layout()

    def update_threshold(self):
        if hasattr(self, 'threshold_slider') and self.audio_worker:
            value = self.threshold_slider.value() / 1000.0
            self.audio_worker.threshold = value
            print(f"Threshold updated to: {value}")
            self.append_status(f"Threshold updated to: {value}")

    def toggle_recording(self):
        print("Toggle recording called")
        try:
            if not self.running:
                print("Starting recording...")
                if self.audio_worker and not self.audio_worker_active:
                    self.audio_worker.start_recording()
                    self.audio_worker_active = True

                if self.transcription_worker and not self.transcription_worker_active:
                    self.transcription_worker.start_processing()
                    self.transcription_worker_active = True

                self.running = True
                self.start_stop_btn.setText("Stop")
                self.start_stop_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #ff6b6b;
                        font-size: 14px;
                        padding: 5px 15px;
                        border-radius: 5px;
                        color: white;
                    }
                """)
                self.append_status("Service started...")
            else:
                print("Stopping recording...")
                if self.audio_worker and self.audio_worker_active:
                    self.audio_worker.stop()
                    self.audio_worker_active = False

                if self.transcription_worker and self.transcription_worker_active:
                    self.transcription_worker.stop()
                    self.transcription_worker_active = False

                self.running = False
                self.start_stop_btn.setText("Start")
                self.start_stop_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        font-size: 14px;
                        padding: 5px 15px;
                        border-radius: 5px;
                        color: white;
                    }
                """)
                self.append_status("Service stopped...")
        except Exception as e:
            print(f"Toggle recording error: {e}")
            self.append_status(f"Error: {str(e)}")

    def append_status(self, text):
        if hasattr(self, 'status_text'):
            self.status_text.append(text)

    def update_sound_level(self, level):
        if hasattr(self, 'sound_indicator'):
            if self.audio_worker and level > self.audio_worker.threshold:
                self.sound_indicator.setText("Sound Level: Active")
                self.sound_indicator.setStyleSheet("color: green;")
            else:
                self.sound_indicator.setText("Sound Level: Silent")
                self.sound_indicator.setStyleSheet("color: gray;")

    def closeEvent(self, event):
        self.running = False
        if hasattr(self, 'audio_worker') and self.audio_worker:
            self.audio_worker.stop()
        if hasattr(self, 'transcription_worker') and self.transcription_worker:
            self.transcription_worker.stop()
        event.accept()

class RealtimeTranscriber:
    def __init__(self):
        try:
            self.app = QApplication(sys.argv)
            load_dotenv()

            self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            self.deeplx_api = os.getenv("deeplx_api_key")
            
            print("Initializing workers...")
            self.audio_worker = AudioWorker()  # Correct initialization
            self.transcription_worker = TranscriptionWorker(self.client)
            
            print("Creating main window...")
            self.window = MainWindow(
                audio_worker=self.audio_worker,
                transcription_worker=self.transcription_worker
            )
            
            print("Setting up connections...")
            self.setup_connections()
            print("Initialization complete")
            
        except Exception as e:
            print(f"Initialization error: {e}")
            raise

    def setup_connections(self):
        try:
            self.audio_worker.audio_ready.connect(self.transcription_worker.process_audio)
            self.audio_worker.error.connect(self.window.append_status)
            self.audio_worker.sound_level.connect(self.window.update_sound_level)
            self.transcription_worker.text_ready.connect(self.window.transcript_panel.append)
            self.transcription_worker.text_ready.connect(self.translate_text)
            self.transcription_worker.error.connect(self.window.append_status)
            print("All signals connected successfully")
        except Exception as e:
            print(f"Error setting up connections: {e}")
            raise

    def translate_text(self, text):
        try:
            url = f"https://api.deeplx.org/{self.deeplx_api}/translate"
            data = {"text": text, "target_lang": "ZH"}
            
            response = requests.post(
                url, 
                json=data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                translation = response.json()['data']
                self.window.translation_panel.append(translation)
            else:
                self.window.append_status(f"Translation Error: {response.status_code}")
                
        except Exception as e:
            self.window.append_status(f"Translation Error: {str(e)}")

    def start(self):
        self.window.show()
        return self.app.exec()

if __name__ == "__main__":
    try:
        transcriber = RealtimeTranscriber()
        sys.exit(transcriber.start())
    except Exception as e:
        print(f"Application error: {e}")
        sys.exit(1)