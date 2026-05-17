import os
import requests
import threading
from dotenv import load_dotenv

# Load the hidden environment variables
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def _send_alert_background(object_type, threat_score, image_path, message):
    """Ye function background (invisible thread) mein chalega taaki video freeze na ho"""
    try:
        # 1. Send the text alert (5 sec timeout)
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=5)
        
        # 2. Send the image (10 sec timeout)
        if image_path and os.path.exists(image_path):
            photo_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            with open(image_path, 'rb') as photo:
                files = {'photo': photo}
                data = {'chat_id': CHAT_ID, 'caption': message}
                response = requests.post(photo_url, data=data, files=files, timeout=10)
                
            if response.status_code == 200:
                print("✅ 📱 Secure Telegram Alert & Photo Sent in Background!")
            else:
                print(f"⚠️ Telegram Error: {response.text}")
                
    except Exception as e:
        print(f"❌ Background Telegram Error: {e}")

def send_telegram_alert(object_type, threat_score, image_path=None):
    """
    Main function jo AI call karega. Ye turant thread start karke wapas video par chala jayega.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ ERROR: Telegram credentials not found! Check your .env file.")
        return

    message = f"🚨 PROJECT CHANAKYA ALERT 🚨\n\n"
    message += f"👁️ Intruder/Threat Detected: {object_type}\n"
    message += f"⚠️ Threat Score: {threat_score}%\n"
    message += f"📍 Status: Action Required immediately."

    # 🚀 FIRE AND FORGET: Start the upload in a parallel background thread
    alert_thread = threading.Thread(
        target=_send_alert_background, 
        args=(object_type, threat_score, image_path, message),
        daemon=True
    )
    alert_thread.start()

if __name__ == "__main__":
    print("Testing Secure Threaded Telegram Module...")
    send_telegram_alert("TEST SUBJECT", 99)