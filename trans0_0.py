import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_token = os.getenv("deeplx_api_key")

url = f"https://api.deeplx.org/{api_token}/translate"

data = {
    "text": "Hello, world!",
    "target_lang": "ZH-HANS"  # Change to your target language
}

response = requests.post(url, json=data, headers={"Content-Type": "application/json"})

if response.status_code == 200:
    translated_data = response.json()
    print(translated_data['data'])
else:
    print(f"Error: {response.status_code}, {response.text}")
