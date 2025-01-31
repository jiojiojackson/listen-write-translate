import soundcard as sc
import numpy as np
import wave
import time

try:
    # Get default system audio loopback (what you hear)
    loopback = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
    
    # Set recording parameters
    SAMPLE_RATE = 48000
    CHANNELS = 2
    DURATION = 5  # seconds

    print("Recording system audio for 5 seconds...")
    
    # Record audio using context manager
    with loopback.recorder(samplerate=SAMPLE_RATE) as mic:
        data = mic.record(numframes=SAMPLE_RATE * DURATION)
        
    # Save as WAV file
    with wave.open('output.wav', 'wb') as f:
        f.setnchannels(CHANNELS)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes((data * 32767).astype(np.int16).tobytes())

    print("Recording saved as output.wav")
    
except Exception as e:
    print(f"Error: {str(e)}")