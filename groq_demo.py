import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()  # Load environment variables

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
filename = os.path.dirname(__file__) + "/output.wav"

with open(filename, "rb") as file:
    transcription = client.audio.transcriptions.create(
      file=(filename, file.read()),
      model="whisper-large-v3-turbo",
      response_format="verbose_json",
    )
    print(transcription.text)
      