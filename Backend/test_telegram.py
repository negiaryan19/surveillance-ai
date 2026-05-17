import os
from dotenv import load_dotenv
import requests

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print(f"Checking Token: {token[:10]}...")
print(f"Checking Chat ID: {chat_id}")

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {"chat_id": chat_id, "text": "🚨 Chanakya Test: Kya tum mujhe sun sakte ho?"}

try:
    r = requests.post(url, data=payload)
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")