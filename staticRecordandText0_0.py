import soundcard as sc
import numpy as np
import wave
from io import BytesIO
import os
from groq import Groq
from dotenv import load_dotenv
import threading
import queue
import time

class RealtimeTranscriber:
    def __init__(self):
        load_dotenv()
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.audio_queue = queue.Queue()
        self.SAMPLE_RATE = 48000
        self.CHANNELS = 2
        self.CHUNK_DURATION = 5
        self.running = True

    def record_chunk(self):
        while self.running:
            try:
                loopback = sc.get_microphone(
                    id=str(sc.default_speaker().name), 
                    include_loopback=True
                )
                
                print("\nRecording chunk...")
                with loopback.recorder(samplerate=self.SAMPLE_RATE) as mic:
                    data = mic.record(numframes=self.SAMPLE_RATE * self.CHUNK_DURATION)
                
                # Store in memory buffer
                wav_buffer = BytesIO()
                with wave.open(wav_buffer, 'wb') as wav:
                    wav.setnchannels(self.CHANNELS)
                    wav.setsampwidth(2)
                    wav.setframerate(self.SAMPLE_RATE)
                    wav.writeframes((data * 32767).astype(np.int16).tobytes())
                
                wav_buffer.seek(0)
                self.audio_queue.put(wav_buffer)

            except Exception as e:
                print(f"Recording Error: {str(e)}")
                self.running = False

    def process_chunks(self):
        while self.running:
            if not self.audio_queue.empty():
                try:
                    audio_buffer = self.audio_queue.get()
                    transcription = self.client.audio.transcriptions.create(
                        file=("audio.wav", audio_buffer.read()),
                        model="whisper-large-v3-turbo",
                        response_format="verbose_json"
                    )
                    if transcription.text.strip():
                        print(f"\nTranscription: {transcription.text}")
                
                except Exception as e:
                    print(f"Transcription Error: {str(e)}")
            time.sleep(0.1)

    def start(self):
        print("Starting realtime transcription (Ctrl+C to stop)...")
        record_thread = threading.Thread(target=self.record_chunk)
        process_thread = threading.Thread(target=self.process_chunks)
        
        record_thread.start()
        process_thread.start()
        
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.running = False
            record_thread.join()
            process_thread.join()
            print("\nTranscription stopped")

if __name__ == "__main__":
    transcriber = RealtimeTranscriber()
    transcriber.start()