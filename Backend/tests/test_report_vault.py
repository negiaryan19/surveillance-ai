import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.database_manager import DatabaseManager
from src.report_generator import generate_pdf_report
from src.security_vault import decrypt_bytes, decrypt_file, encrypt_bytes, encrypt_file, load_key

BACKEND = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ vault
def test_key_created_once_with_mode_600(tmp_path):
    key_file = tmp_path / "k" / "secret.key"
    k1 = load_key(key_file)
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert load_key(key_file) == k1  # never regenerated


def test_concurrent_first_creation_yields_one_key(tmp_path):
    key_file = tmp_path / "secret.key"
    keys = []
    threads = [threading.Thread(target=lambda: keys.append(load_key(key_file))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(keys)) == 1


def test_corrupt_key_raises_clear_error(tmp_path):
    key_file = tmp_path / "secret.key"
    key_file.write_bytes(b"not-a-key")
    with pytest.raises(RuntimeError, match="invalid"):
        load_key(key_file)


def test_encrypt_file_never_in_place_and_round_trips(tmp_path):
    key_file = tmp_path / "secret.key"
    src = tmp_path / "r.pdf"
    src.write_bytes(b"%PDF-1.4 hello")
    enc = encrypt_file(src, key_file=key_file)
    assert enc == tmp_path / "r.pdf.enc" and src.read_bytes() == b"%PDF-1.4 hello"
    assert enc.read_bytes() != src.read_bytes()
    out = decrypt_file(enc, key_file=key_file)
    assert out == src and out.read_bytes() == b"%PDF-1.4 hello"
    with pytest.raises(RuntimeError, match="wrong key"):
        decrypt_bytes(b"garbage", key_file=key_file)
    assert decrypt_bytes(encrypt_bytes(b"x", key_file), key_file) == b"x"


def test_decrypt_tool_end_to_end(tmp_path):
    key_file = tmp_path / "secret.key"
    src = tmp_path / "r.pdf"
    src.write_bytes(b"%PDF-1.4 tool")
    enc = encrypt_file(src, key_file=key_file)
    out = tmp_path / "decoded.pdf"
    res = subprocess.run(
        [
            sys.executable,
            str(BACKEND / "tools" / "decrypt_report.py"),
            str(enc),
            "-o",
            str(out),
            "--key",
            str(key_file),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert out.read_bytes() == b"%PDF-1.4 tool"
    bad = subprocess.run(
        [sys.executable, str(BACKEND / "tools" / "decrypt_report.py"), str(src), "--key", str(key_file)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert bad.returncode == 1 and "error" in bad.stderr


# ------------------------------------------------------------------ report
def pdf_text(path: Path) -> str:
    """Enough of the PDF's content streams to check for plain (uncompressed) text."""
    from fpdf import FPDF  # noqa: F401 - make sure it is importable

    raw = path.read_bytes()
    try:
        import zlib

        chunks = []
        for m in __import__("re").finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
            try:
                chunks.append(zlib.decompress(m.group(1)).decode("latin-1"))
            except Exception:  # noqa: BLE001
                chunks.append(m.group(1).decode("latin-1", "replace"))
        return "\n".join(chunks)
    except Exception:  # noqa: BLE001
        return raw.decode("latin-1", "replace")


import re  # noqa: E402


def test_report_converts_to_local_tz_and_survives_unicode(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    iid = db.log_incident(
        camera="alpha",
        object_type="Person 🚨",
        threat_score=91,
        zone_level="CRITICAL",
        identity="Zoë",
        reasons=["Breached Critical Zone"],
    )
    import sqlite3

    with sqlite3.connect(tmp_path / "db.sqlite") as conn:
        conn.execute("UPDATE incidents SET timestamp='2026-09-22T06:30:00Z' WHERE id=?", (iid,))
    path = generate_pdf_report(db, out_dir=tmp_path / "reports", tz_name="Asia/Kolkata")
    assert path.is_file() and path.read_bytes().startswith(b"%PDF") and path.name.startswith("Chanakya_Report_")
    text = pdf_text(path)
    assert "2026-09-22 12:00:00" in text  # 06:30 UTC -> 12:00 IST
    assert "IST" in text and "91%" in text


def test_report_on_empty_db_and_pruning(tmp_path):
    db = DatabaseManager(tmp_path / "db.sqlite")
    out = tmp_path / "reports"
    path = generate_pdf_report(db, out_dir=out)
    assert path.read_bytes().startswith(b"%PDF") and "No incidents" in pdf_text(path)
    for i in range(25):
        p = out / f"Chanakya_Report_2000010{i:02d}_000000_aaaaaa.pdf"
        p.write_bytes(b"%PDF")
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
    generate_pdf_report(db, out_dir=out)
    assert len(list(out.glob("Chanakya_Report_*"))) == 20
