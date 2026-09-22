"""Decrypt a report downloaded with ``/api/report.pdf?encrypted=1``.

Usage: python tools/decrypt_report.py Chanakya_Report_x.pdf.enc [-o out.pdf] [--key database/secret.key]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from src.security_vault import decrypt_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("encrypted", help="the .enc file to decrypt")
    parser.add_argument("-o", "--output", help="where to write the PDF (default: strip .enc)")
    parser.add_argument("--key", help="path to secret.key (default: the configured KEY_FILE)")
    args = parser.parse_args(argv)
    try:
        out = decrypt_file(args.encrypted, args.output, key_file=args.key)
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
