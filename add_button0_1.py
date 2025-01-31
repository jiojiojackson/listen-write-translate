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
                            QGridLayout, QFrame)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QResizeEvent

class AudioWorker(QThread):
    audio_ready = pyqtSignal(BytesIO)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False  # Changed to False initially
        
    def run(self):
        try:
            loopback = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
            while self.running:  # Check running state at loop start
                with loopback.recorder(samplerate=48000) as mic:
                    data = mic.record(numframes=48000 * 5)
                    if not self.running:  # Check if stopped during recording
                        break
                    wav_buffer = BytesIO()
                    with wave.open(wav_buffer, 'wb') as wav:
                        wav.setnchannels(2)
                        wav.setsampwidth(2)
                        wav.setframerate(48000)
                        wav.writeframes((data * 32767).astype(np.int16).tobytes())
                    wav_buffer.seek(0)
                    if self.running:
                        self.audio_ready.emit(wav_buffer)
        except Exception as e:
            self.error.emit(f"Recording Error: {str(e)}")
            
    def start_recording(self):
        self.running = True
        self.start()
        
    def stop(self):
        self.running = False
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
        self.queue.put(audio_buffer)

    def run(self):
        while self.running:
            if not self.queue.empty():
                try:
                    audio_buffer = self.queue.get()
                    transcription = self.client.audio.transcriptions.create(
                        file=("audio.wav", audio_buffer.read()),
                        model="whisper-large-v3-turbo",
                        response_format="verbose_json"
                    )
                    if transcription.text.strip():
                        self.text_ready.emit(transcription.text)
                except Exception as e:
                    self.error.emit(f"Transcription Error: {str(e)}")
            self.msleep(100)

    def stop(self):
        self.running = False
        self.wait()

    def start_processing(self):
        self.running = True
        self.start()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.running = False
        self.init_ui()

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
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        self.start_stop_btn.clicked.connect(self.toggle_recording)
        control_layout.addWidget(self.start_stop_btn)
        
        # Text panels with titles
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

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.update_layout()

    def update_layout(self):
        # Remove widgets from grid (except control panel)
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget() != self.grid_layout.itemAt(0).widget():
                self.grid_layout.removeItem(item)

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

    def toggle_status(self):
        if self.status_text.isVisible():
            self.status_text.hide()
            self.minimize_btn.setText("+")
            self.status_container.setMaximumHeight(30)
        else:
            self.status_text.show()
            self.minimize_btn.setText("_")
            self.status_container.setMaximumHeight(150)

    def toggle_recording(self):
        self.running = not self.running
        if self.running:
            self.start_stop_btn.setText("Stop")
            self.start_stop_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ff6b6b;
                    font-size: 14px;
                    padding: 5px 15px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #ff5252;
                }
            """)
        else:
            self.start_stop_btn.setText("Start")
            self.start_stop_btn.setStyleSheet("""
                QPushButton {
                    font-size: 14px;
                    padding: 5px 15px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)

    def append_status(self, text):
        self.status_text.append(text)
        if not self.status_text.isVisible():
            self.toggle_status()

    def closeEvent(self, event):
        self.running = False
        super().closeEvent(event)

class RealtimeTranscriber:
    def __init__(self):
        self.app = QApplication(sys.argv)
        load_dotenv()
        
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.deeplx_api = os.getenv("deeplx_api_key")
        
        self.window = MainWindow()
        self.audio_worker = AudioWorker()
        self.transcription_worker = TranscriptionWorker(self.client)
        
        self.setup_connections()

    def setup_connections(self):
        self.audio_worker.audio_ready.connect(self.transcription_worker.process_audio)
        self.audio_worker.error.connect(self.window.append_status)
        self.transcription_worker.text_ready.connect(
            lambda text: self.window.transcript_panel.append(text))
        self.transcription_worker.text_ready.connect(self.translate_text)
        self.transcription_worker.error.connect(self.window.append_status)
        self.window.start_stop_btn.clicked.connect(self.toggle_recording)

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

    def toggle_recording(self):
        if self.window.running:
            # Starting
            self.audio_worker.start_recording()
            self.transcription_worker.start_processing()
            self.window.append_status("Service started...")
        else:
            # Stopping
            if self.audio_worker.isRunning():
                self.audio_worker.stop()
            if self.transcription_worker.isRunning():
                self.transcription_worker.stop()
            self.window.append_status("Service stopped...")

    def start(self):
        self.window.show()
        return self.app.exec()

    def closeEvent(self, event):
        # Ensure cleanup on window close
        if self.audio_worker.isRunning():
            self.audio_worker.stop()
        if self.transcription_worker.isRunning():
            self.transcription_worker.stop()
        event.accept()

if __name__ == "__main__":
    transcriber = RealtimeTranscriber()
    sys.exit(transcriber.start())