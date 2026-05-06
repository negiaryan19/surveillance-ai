import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Pointing to the database folder in your project
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "database"
DB_PATH = DB_DIR / "chanakya.db"

class DatabaseManager:
    def __init__(self):
        # Ensure the database directory exists
        os.makedirs(DB_DIR, exist_ok=True)
        self.init_db()

    def get_connection(self):
        """Creates a fresh connection to the database."""
        return sqlite3.connect(DB_PATH)

    def init_db(self):
        """Creates the tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    object_type TEXT,
                    threat_score INTEGER,
                    zone_level TEXT,
                    image_path TEXT
                )
            ''')
            conn.commit()
            print("🗄️ System Memory (SQLite) Initialized: chanakya.db")

    def log_incident(self, object_type, threat_score, zone_level="SAFE", image_path="None"):
        """Saves a new threat detection to the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO incidents (object_type, threat_score, zone_level, image_path)
                VALUES (?, ?, ?, ?)
            ''', (object_type, threat_score, zone_level, image_path))
            conn.commit()
            print(f"💾 Logged: {object_type} | Threat: {threat_score}%")

    def get_recent_logs(self, limit=10):
        """Fetches the latest incidents for the web dashboard."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT timestamp, object_type, threat_score, zone_level 
                FROM incidents 
                ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
            return cursor.fetchall()

# Small test block to create the DB when you run this file directly
if __name__ == "__main__":
    db = DatabaseManager()
    print("✅ Database is ready for Phase 4!")