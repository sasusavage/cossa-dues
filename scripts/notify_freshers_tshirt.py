"""Text every fresher who has paid, telling them to contact the VP for their t-shirt.

Dry run by default — prints who would be texted and sends nothing. Pass
--send to actually send. Each phone number is texted at most once.

    python scripts/notify_freshers_tshirt.py          # dry run
    python scripts/notify_freshers_tshirt.py --send   # send for real
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app import sms_client  # noqa: E402

VP_PHONE = "+233 53 796 8305"

RECIPIENTS_SQL = """
SELECT DISTINCT ON (phone_number)
       full_name, student_id, phone_number
FROM dues.payments
WHERE status = 'successful' AND match_type = 'fresher'
ORDER BY phone_number, paid_at DESC
"""


def normalise_gh_phone(raw: str) -> str | None:
    """Return +233XXXXXXXXX for a Ghana number, or None if it doesn't look valid."""
    digits = re.sub(r"[^0-9+]", "", raw)
    if digits.startswith("+233") and len(digits) == 13:
        return digits
    if digits.startswith("233") and len(digits) == 12:
        return "+" + digits
    if digits.startswith("0") and len(digits) == 10:
        return "+233" + digits[1:]
    return None


def build_message() -> str:
    return (
        "COSSA Dues: thank you for paying. To collect your COSSA t-shirt, "
        f"contact the Vice President on {VP_PHONE}."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="actually send the SMS")
    args = parser.parse_args()

    message = build_message()
    print(f"Message ({len(message)} chars):\n{message}\n")

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=15) as conn:
        rows = conn.execute(RECIPIENTS_SQL).fetchall()

    targets = []
    print(f"{len(rows)} fresher(s) who paid:")
    for r in rows:
        phone = normalise_gh_phone(r["phone_number"])
        status = phone or "INVALID NUMBER — will be skipped"
        print(f"  {r['full_name']} | {r['student_id']} | {r['phone_number']} -> {status}")
        if phone:
            targets.append((r, phone))

    if not args.send:
        print("\nDry run — nothing sent. Re-run with --send to text these people.")
        return

    sent = failed = 0
    for r, phone in targets:
        try:
            sms_client.send_sms(phone, message)
            sent += 1
        except Exception as exc:
            failed += 1
            print(f"FAILED {phone}: {exc}")
    print(f"\nSent: {sent}, failed: {failed}, skipped (invalid number): {len(rows) - len(targets)}")


if __name__ == "__main__":
    main()
