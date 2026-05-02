"""
Telegram Command Bot
--------------------
Receives commands from Telegram and controls the surveillance system.
"""

import os
import sys
import cv2
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# Add parent directory so we can import config
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.shared_state import system_state
from config.settings import SNAPSHOTS_DIR

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


# ========================================
# Command: /start - Welcome message
# ========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message when user starts the bot."""
    
    welcome_message = """
🛡️ *AI SURVEILLANCE COMMAND CENTER* 🛡️

Welcome! Your defence system is online.

📋 *Available Commands:*

/status \\- Check system status
/snapshot \\- Get instant camera photo
/stats \\- View today's statistics
/zone \\- Check restricted zone info
/pause \\- Pause alert notifications
/resume \\- Resume alert notifications
/log \\- View last 5 alerts
/help \\- Show this menu

🟢 *System Status:* ONLINE
🤖 *Bot:* Active and Ready

_Stay vigilant, soldier!_ 🎖️
"""
    
    await update.message.reply_text(welcome_message, parse_mode="Markdown")


# ========================================
# Command: /status - Current status
# ========================================
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current system status."""
    
    stats = system_state.get_stats()
    
    if stats["is_paused"]:
        status_text = "⏸️ PAUSED"
        status_emoji = "🟡"
    else:
        status_text = "🟢 ACTIVE & MONITORING"
        status_emoji = "🟢"
    
    if stats["last_alert"]:
        last_alert = stats["last_alert"].strftime("%I:%M:%S %p")
        last_level = stats["last_level"]
    else:
        last_alert = "No alerts yet"
        last_level = "N/A"
    
    message = f"""
📊 *SYSTEM STATUS REPORT*

{status_emoji} *Status:* {status_text}
🕐 *Time:* {datetime.now().strftime("%I:%M:%S %p")}

━━━━━━━━━━━━━━━
🚨 *Alerts Today:* {stats["total_alerts"]}
🕒 *Last Alert:* {last_alert}
⚠️ *Last Level:* {last_level}
━━━━━━━━━━━━━━━

✅ All systems operational.
"""
    
    await update.message.reply_text(message, parse_mode="Markdown")


# ========================================
# Command: /snapshot - Get instant photo
# ========================================
async def snapshot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send instant camera snapshot."""
    
    await update.message.reply_text("📸 Capturing snapshot...")
    
    frame = system_state.get_frame()
    
    if frame is None:
        await update.message.reply_text("❌ Camera not available right now.")
        return
    
    # Save snapshot
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = str(SNAPSHOTS_DIR / f"manual_{timestamp}.jpg")
    cv2.imwrite(snapshot_path, frame)
    
    try:
        with open(snapshot_path, "rb") as photo:
            caption = f"📸 *Live Snapshot*\n🕐 {datetime.now().strftime('%I:%M:%S %p')}"
            await update.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending photo: {e}")


# ========================================
# Command: /stats - Show statistics
# ========================================
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's statistics."""
    
    stats = system_state.get_stats()
    
    message = f"""
📈 *TODAY'S STATISTICS*

🚨 *Total Alerts:* {stats["total_alerts"]}
👥 *People Detected:* {stats["total_people"]}

━━━━━━━━━━━━━━━
*Recent Activity:*
"""
    
    if stats["recent_alerts"]:
        for i, alert in enumerate(stats["recent_alerts"][-5:], 1):
            level_emoji = {
                "LOW": "🟢", "MEDIUM": "🟡",
                "HIGH": "🟠", "CRITICAL": "🔴"
            }.get(alert["level"], "⚪")
            
            message += f"\n{i}. {level_emoji} {alert['time']} - {alert['level']}"
            message += f"\n   👤 {alert['people']} person(s) | {alert['behavior']}"
    else:
        message += "\n_No alerts recorded yet._"
    
    message += "\n\n━━━━━━━━━━━━━━━"
    
    await update.message.reply_text(message, parse_mode="Markdown")


# ========================================
# Command: /zone - Zone information
# ========================================
async def zone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show restricted zone information."""
    
    zone = system_state.zone_coordinates
    
    message = f"""
🗺️ *RESTRICTED ZONE INFO*

📍 *Coordinates:*
   • Top-Left: ({zone[0]}, {zone[1]})
   • Bottom-Right: ({zone[2]}, {zone[3]})

📐 *Zone Size:*
   • Width: {zone[2] - zone[0]} pixels
   • Height: {zone[3] - zone[1]} pixels

🎯 *Detection:* Active
⚠️ *Alert Trigger:* 2 seconds loitering
"""
    
    await update.message.reply_text(message, parse_mode="Markdown")


# ========================================
# Command: /pause - Pause alerts
# ========================================
async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause alert notifications."""
    
    system_state.pause_alerts()
    
    message = """
⏸️ *ALERTS PAUSED*

🔕 You will not receive notifications until resumed.

📌 *Note:* Detection is still running, but alerts are silenced.

Use /resume to enable alerts again.
"""
    
    await update.message.reply_text(message, parse_mode="Markdown")


# ========================================
# Command: /resume - Resume alerts
# ========================================
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume alert notifications."""
    
    system_state.resume_alerts()
    
    message = """
▶️ *ALERTS RESUMED*

🔔 You will now receive all intrusion alerts.

🟢 *Status:* Active monitoring
🛡️ *Protection:* Full
"""
    
    await update.message.reply_text(message, parse_mode="Markdown")


# ========================================
# Command: /log - Recent alerts
# ========================================
async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent alert history."""
    
    stats = system_state.get_stats()
    
    if not stats["recent_alerts"]:
        await update.message.reply_text(
            "📋 *No alerts recorded yet.*\n\nSystem is monitoring...",
            parse_mode="Markdown"
        )
        return
    
    message = "📋 *RECENT ALERT LOG*\n\n"
    
    for i, alert in enumerate(stats["recent_alerts"], 1):
        level_emoji = {
            "LOW": "🟢", "MEDIUM": "🟡",
            "HIGH": "🟠", "CRITICAL": "🔴"
        }.get(alert["level"], "⚪")
        
        message += f"*{i}.* {level_emoji} *{alert['level']}*\n"
        message += f"   🕐 {alert['time']}\n"
        message += f"   👤 {alert['people']} person(s)\n"
        message += f"   🎯 {alert['behavior']}\n\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")


# ========================================
# Command: /help - Show all commands
# ========================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help menu."""
    
    help_text = """
🆘 *HELP - COMMAND GUIDE*

*📊 Information:*
/status - Current system status
/stats - Today's statistics
/log - Recent alert history
/zone - Restricted zone info

*🎮 Control:*
/snapshot - Get live camera photo
/pause - Stop alert notifications
/resume - Resume notifications

*ℹ️ Other:*
/start - Welcome message
/help - This menu

━━━━━━━━━━━━━━━
🤖 _AI Surveillance Bot v1.0_
"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ========================================
# Start the bot
# ========================================
def run_telegram_bot():
    """Start the Telegram bot."""
    
    print("🤖 Starting Telegram Command Bot...")
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not found in .env file!")
        return
    
    # Create the bot application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register all commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("snapshot", snapshot_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("zone", zone_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("log", log_command))
    app.add_handler(CommandHandler("help", help_command))
    
    print("✅ Telegram Bot is running!")
    print("📱 Send /start to your bot in Telegram\n")
    
    # Start the bot
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


if __name__ == "__main__":
    run_telegram_bot()