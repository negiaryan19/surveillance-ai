"""
Smart Alert System
------------------
This file analyzes intruder behavior and sends smart alerts to Telegram.
Author: [Your Name]
"""

import requests
from datetime import datetime


# ========================================
# Put your Telegram details here
# ========================================
BOT_TOKEN = ""
CHAT_ID = "PASTE_YOUR_CHAT_ID_HERE"


# ========================================
# Class to track and analyze person behavior
# ========================================
class BehaviorTracker:
    """
    This class remembers where the person was in the last few frames
    and figures out if they are standing still, walking, or running.
    """

    def __init__(self):
        # Store the last 30 positions of the person
        self.positions = []
        self.max_positions = 30

    def add_position(self, x, y):
        """Save the current position of the person."""
        self.positions.append((x, y))

        # Keep only the latest 30 positions
        if len(self.positions) > self.max_positions:
            self.positions.pop(0)

    def get_behavior(self):
        """
        Look at the positions and decide:
        - Is the person standing still? (suspicious)
        - Walking normally?
        - Running fast? (very suspicious)
        """

        # Need at least 5 positions to decide
        if len(self.positions) < 5:
            return "Analyzing..."

        # Calculate how much the person moved in total
        total_distance = 0
        for i in range(1, len(self.positions)):
            old_x, old_y = self.positions[i - 1]
            new_x, new_y = self.positions[i]

            # Distance formula
            distance = ((new_x - old_x) ** 2 + (new_y - old_y) ** 2) ** 0.5
            total_distance += distance

        # Average movement per frame
        avg_movement = total_distance / len(self.positions)

        # Decide behavior based on movement
        if avg_movement < 5:
            return "Standing Still (Loitering)"
        elif avg_movement < 20:
            return "Walking Slowly"
        else:
            return "Running Fast"

    def reset(self):
        """Clear all positions when person leaves."""
        self.positions = []


# ========================================
# Function to decide how dangerous the threat is
# ========================================
def calculate_threat_level(person_count, time_in_zone, behavior):
    """
    Give the threat a score based on:
    - How many people are there
    - How long they have been in the zone
    - What they are doing

    Returns: threat level (LOW / MEDIUM / HIGH / CRITICAL)
    """

    score = 0

    # Longer time = more dangerous
    if time_in_zone > 15:
        score += 3
    elif time_in_zone > 8:
        score += 2
    elif time_in_zone > 3:
        score += 1

    # More people = more dangerous
    if person_count > 3:
        score += 3
    elif person_count > 1:
        score += 2

    # Running or standing still = suspicious
    if "Running" in behavior:
        score += 3
    elif "Standing Still" in behavior:
        score += 2

    # Final decision based on total score
    if score >= 7:
        return "CRITICAL"
    elif score >= 5:
        return "HIGH"
    elif score >= 3:
        return "MEDIUM"
    else:
        return "LOW"


# ========================================
# Function to make a nice report message
# ========================================
def create_report(person_count, time_in_zone, behavior, threat_level):
    """
    Build a clean and professional looking report
    that will be sent to Telegram.
    """

    # Get current date and time
    now = datetime.now().strftime("%d %b %Y, %I:%M:%S %p")

    # Choose emoji based on threat level
    emoji_map = {
        "LOW": "🟢",
        "MEDIUM": "🟡",
        "HIGH": "🟠",
        "CRITICAL": "🔴"
    }
    emoji = emoji_map.get(threat_level, "⚪")

    # Suggest action based on threat level
    action_map = {
        "LOW": "Just keep watching.",
        "MEDIUM": "Send patrol to check.",
        "HIGH": "Send security team immediately.",
        "CRITICAL": "Emergency response needed right now!"
    }
    action = action_map.get(threat_level, "Monitor the situation.")

    # Build the final message
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

_— Sent by AI Surveillance System_
"""
    return report


# ========================================
# Function to send the alert to Telegram
# ========================================
def send_alert_to_telegram(message, image_path):
    """
    Send the report along with snapshot image to Telegram.
    """

    # Telegram API URL for sending photo
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    try:
        # Open the snapshot image
        with open(image_path, "rb") as image_file:

            # Prepare the data to send
            files = {"photo": image_file}
            data = {
                "chat_id": CHAT_ID,
                "caption": message,
                "parse_mode": "Markdown"
            }

            # Send to Telegram
            response = requests.post(url, files=files, data=data, timeout=10)

        # Check if it was sent successfully
        if response.status_code == 200:
            print("✅ Alert sent to Telegram successfully!")
            return True
        else:
            print(f"❌ Telegram failed. Error: {response.text}")
            return False

    except Exception as error:
        print(f"❌ Could not send alert: {error}")
        return False