import sqlite3
from fpdf import FPDF
from datetime import datetime
import os
from pathlib import Path

# Path Logic: Project ke root folder tak pahunchna
BASE_DIR = Path(__file__).resolve().parent.parent

class ChanakyaReport(FPDF):
    def header(self):
        # Logo ya Header Text
        self.set_font('Arial', 'B', 15)
        self.set_text_color(255, 0, 0) # Red color for branding
        self.cell(0, 10, 'PROJECT CHANAKYA: INTELLIGENCE BRIEFING', 0, 1, 'C')
        self.ln(5)
        self.set_font('Arial', 'I', 10)
        self.set_text_color(0, 0, 0)
        self.cell(0, 10, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', 0, 1, 'R')
        self.line(10, 32, 200, 32) # Header line
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf_report():
    # 🔍 DB Path Discovery: Pehle root check karo, phir database/ folder
    possible_paths = [
        BASE_DIR / "chanakya.db",
        BASE_DIR / "database" / "chanakya.db"
    ]
    
    db_path = None
    for p in possible_paths:
        if p.exists():
            db_path = p
            break
            
    if not db_path:
        print("⚠️ ERROR: Database file (chanakya.db) not found!")
        return None

    # 1. Connect and Fetch
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, object_type, threat_score, zone_level FROM logs ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    # 2. PDF Setup
    pdf = ChanakyaReport()
    pdf.add_page()
    pdf.set_font("Arial", size=11)

    # 3. Briefing Summary
    total = len(rows)
    high_priority = len([r for r in rows if r[2] > 70])
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "MISSION SUMMARY", 1, 1, 'L', fill=True)
    pdf.set_font("Arial", size=11)
    pdf.cell(0, 10, f"- Total Incidents Recorded: {total}", 0, 1)
    pdf.cell(0, 10, f"- High Priority Intrusion Alerts: {high_priority}", 0, 1)
    pdf.ln(10)

    # 4. Data Table
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(0, 51, 102) # Dark Blue Header
    pdf.set_text_color(255, 255, 255)
    
    pdf.cell(55, 10, "Timestamp (IST)", 1, 0, 'C', True)
    pdf.cell(35, 10, "Entity", 1, 0, 'C', True)
    pdf.cell(40, 10, "Threat Level", 1, 0, 'C', True)
    pdf.cell(50, 10, "Deployment Zone", 1, 1, 'C', True)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", size=10)
    
    for row in rows:
        pdf.cell(55, 10, str(row[0]), 1)
        pdf.cell(35, 10, str(row[1]), 1)
        # Highlight Red if score > 70
        if row[2] > 70:
            pdf.set_text_color(255, 0, 0)
            pdf.cell(40, 10, f"{row[2]}% [CRITICAL]", 1)
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.cell(40, 10, f"{row[2]}%", 1)
        pdf.cell(50, 10, str(row[3]), 1)
        pdf.ln()

    # 5. Output Management
    report_filename = f"Chanakya_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    report_path = BASE_DIR / report_filename
    pdf.output(str(report_path))
    
    print(f"✅ Report successfully generated at: {report_path}")
    return str(report_path)

if __name__ == "__main__":
    generate_pdf_report()