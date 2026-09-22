"""Incident briefing as a PDF (fpdf2).

Timestamps are stored in UTC and converted to ``LOCAL_TZ`` here, with the
column labelled by the zone's abbreviation — v1 wrote UTC values under an
"IST" heading. fpdf2's core fonts are latin-1 only, so every cell is
sanitised; identities and reasons can contain anything a user typed.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("chanakya.report")

KEEP_REPORTS = 20
MAX_CELL = 38


def _latin1(text) -> str:
    return str(text if text is not None else "").encode("latin-1", "replace").decode("latin-1")


def _cell(text, width: int = MAX_CELL) -> str:
    text = _latin1(text)
    return text if len(text) <= width else text[: width - 1] + "~"


def _local(iso_utc: str, tz: ZoneInfo) -> str:
    try:
        moment = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return _cell(iso_utc, 20)
    return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def generate_pdf_report(db, out_dir=None, tz_name: str | None = None, limit: int = 500) -> Path:

    from config import settings

    out_dir = Path(out_dir if out_dir is not None else settings.REPORTS_DIR)
    tz = ZoneInfo(tz_name or settings.LOCAL_TZ)
    tz_label = datetime.now(tz).strftime("%Z") or str(tz)

    items, total = db.list_incidents(limit=limit, offset=0)
    stats = db.stats(hours=24)
    critical = len([i for i in items if i["threat_score"] >= 70])

    pdf = _Report(tz_label)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 9, "SUMMARY", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    for line in (
        f"Incidents in this report: {len(items)} (of {total} stored)",
        f"Critical (score >= 70): {critical}",
        f"Last 24 h: {stats['total']} incidents, {stats['unacknowledged']} unacknowledged",
        f"Times shown in {tz_label}; stored in UTC.",
    ):
        pdf.cell(0, 7, _latin1(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    widths = (38, 18, 34, 34, 16, 22, 28)
    headers = (f"Time ({tz_label})", "Camera", "Object", "Identity", "Score", "Zone", "Status")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(0, 51, 102)
    pdf.set_text_color(255, 255, 255)
    for w, h in zip(widths, headers, strict=True):
        pdf.cell(w, 8, _cell(h, 20), border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=8)

    if not items:
        pdf.cell(sum(widths), 8, "No incidents recorded.", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
    for inc in items:
        row = (
            _local(inc["timestamp"], tz),
            _cell(inc.get("camera") or "-", 10),
            _cell(inc["object_type"], 18),
            _cell(inc.get("identity") or "Unknown", 18),
            f"{inc['threat_score']}%",
            _cell(inc["zone_level"], 12),
            "acknowledged" if inc.get("acknowledged") else _cell(inc.get("category", ""), 12),
        )
        hot = inc["threat_score"] >= 70
        if hot:
            pdf.set_text_color(200, 0, 0)
        for w, value in zip(widths, row, strict=True):
            pdf.cell(w, 7, value, border=1)
        pdf.ln()
        if hot:
            pdf.set_text_color(0, 0, 0)
        reasons = ", ".join(inc.get("reasons") or [])
        if reasons:
            pdf.set_font("Helvetica", "I", 7)
            pdf.cell(sum(widths), 5, _cell("   " + reasons, 120), border="LRB", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=8)

    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"Chanakya_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}.pdf"
    path = out_dir / name
    pdf.output(str(path))
    _prune(out_dir)
    log.info("report written: %s (%d incidents)", path.name, len(items))
    return path


def _prune(out_dir: Path) -> None:
    reports = sorted(out_dir.glob("Chanakya_Report_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in reports[KEEP_REPORTS:]:
        with contextlib.suppress(OSError):  # already gone or locked: not worth failing a report
            old.unlink()


def _make_report_class():
    from fpdf import FPDF

    class Report(FPDF):
        def __init__(self, tz_label: str) -> None:
            super().__init__()
            self.tz_label = tz_label

        def header(self) -> None:
            self.set_font("Helvetica", "B", 14)
            self.set_text_color(180, 0, 0)
            self.cell(0, 9, "PROJECT CHANAKYA - INCIDENT BRIEFING", align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "I", 9)
            self.set_text_color(0, 0, 0)
            generated = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S UTC")
            self.cell(0, 6, f"Generated {generated}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(4)

        def footer(self) -> None:
            self.set_y(-14)
            self.set_font("Helvetica", "I", 8)
            self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")

    return Report


class _Report:
    """Lazy proxy so ``fpdf`` is imported only when a report is generated."""

    def __new__(cls, tz_label: str):
        return _make_report_class()(tz_label)
