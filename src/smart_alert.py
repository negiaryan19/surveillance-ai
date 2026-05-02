"""
Smart Alert System
------------------
Analyzes intruder behavior and sends smart alerts to Telegram.
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()


# ========================================
# Telegram details (loaded from .env)
# ========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("⚠️  Warning: BOT_TOKEN or CHAT_ID missing in .env file!")


# ========================================
# Behavior Tracker
# ========================================
class BehaviorTracker:
    """Tracks person movement to figure out behavior."""

    def __init__(self):
        self.positions = []
        self.max_positions = 30

    def add_position(self, x, y):
        """Save current position."""
        self.positions.append((x, y))
        if len(self.positions) > self.max_positions:
            self.positions.pop(0)

    def get_behavior(self):
        """Decide if person is standing, walking, or running."""
        
        if len(self.positions) < 5:
            return "Analyzing..."

        total_distance = 0
        for i in range(1, len(self.positions)):
            old_x, old_y = self.positions[i - 1]
            new_x, new_y = self.positions[i]
            distance = ((new_x - old_x) ** 2 + (new_y - old_y) ** 2) ** 0.5
            total_distance += distance

        avg_movement = total_distance / len(self.positions)

        if avg_movement < 5:
            return "Standing Still (Loitering)"
        elif avg_movement < 20:
            return "Walking Slowly"
        else:
            return "Running Fast"

    def reset(self):
        """Clear all positions."""
        self.positions = []


# ========================================
# Calculate Threat Level
# ========================================
def calculate_threat_level(person_count, time_in_zone, behavior):
    """Score the threat and return level."""

    score = 0

    if time_in_zone > 15:
        score += 3
    elif time_in_zone > 8:
        score += 2
    elif time_in_zone > 3:
        score += 1

    if person_count > 3:
        score += 3
    elif person_count > 1:
        score += 2

    if "Running" in behavior:
        score += 3
    elif "Standing Still" in behavior:
        score += 2

    if score >= 7:
        return "CRITICAL"
    elif score >= 5:
        return "HIGH"
    elif score >= 3:
        return "MEDIUM"
    else:
        return "LOW"


# ========================================
# Create Report Message
# ========================================
def create_report(person_count, time_in_zone, behavior, threat_level):
    """Build clean report message."""

    now = datetime.now().strftime("%d %b %Y, %I:%M:%S %p")

    emoji_map = {
        "LOW": "🟢", "MEDIUM": "🟡",
        "HIGH": "🟠", "CRITICAL": "🔴"
    }
    emoji = emoji_map.get(threat_level, "⚪")

    action_map = {
        "LOW": "Just keep watching.",
        "MEDIUM": "Send patrol to check.",
        "HIGH": "Send security team immediately.",
        "CRITICAL": "Emergency response needed right now!"
    }
    action = action_map.get(threat_level, "Monitor the situation.")

    report = f"""
🚨 *INTRUDER ALERT* 🚨

📍 *Location:* Restricted Zone
🕐 *Time:* {now}

━━━━━━━━━━━━━━━
{emoji} *Threat Level:* {threat_level}
👤 *People Detected:* {person_count}
⏱️ *Time in Zone:* {int(time_in_zone)} seconds
🎯 *Behavior:* {behavior}
━━━━━━━━━━━━━━━

✅ *Suggested Action:*
{action}

_— AI Surveillance System_
"""
    return report


# ========================================
# Send to Telegram
# ========================================
def send_alert_to_telegram(message, image_path):
    """Send report + snapshot to Telegram."""

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    try:
        with open(image_path, "rb") as image_file:
            files = {"photo": image_file}
            data = {
                "chat_id": CHAT_ID,
                "caption": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, files=files, data=data, timeout=10)

        if response.status_code == 200:
            print("✅ Alert sent to Telegram!")
            return True
        else:
            print(f"❌ Telegram error: {response.text}")
            return False

    except Exception as error:
        print(f"❌ Could not send alert: {error}")
        return False