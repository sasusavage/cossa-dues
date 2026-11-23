"""Resend the SMS receipt for a successful payment.

Two modes:
- --today: everyone who paid today and whose receipt never went out
  (sms_sent = false) — the normal case after a payment's SMS failed.
- --student-id ID: force a resend to one specific student regardless of
  sms_sent, e.g. because they lost the text and asked for another copy.

    python scripts/resend_receipt.py --today
    python scripts/resend_receipt.py --student-id 227IT01001392
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app import sms_client  # noqa: E402

APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")
VP_PHONE = os.environ.get("VP_PHONE", "+233 53 796 8305")


def build_message(payment: dict) -> str:
    link = f"{APP_BASE_URL}/r/{payment['short_code']}"
    message = f"COSSA Dues: GHS {float(payment['amount']):.2f} received. Receipt: {link}"
    if payment["tshirt"]:
        message += f" Your t-shirt is ready - contact the VP on {VP_PHONE} to collect it."
    return message


def send_one(conn, payment: dict) -> None:
    message = build_message(payment)
    sms_client.send_sms(payment["phone_number"], message)
    conn.execute("UPDATE dues.payments SET sms_sent = true WHERE reference = %s", (payment["reference"],))
    print(f"Sent to {payment['full_name']} ({payment['student_id']}) at {payment['phone_number']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--today", action="store_true", help="resend to today's payments missing a receipt")
    group.add_argument("--student-id", help="force a resend to this one student")
    args = parser.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        if args.today:
            rows = conn.execute(
                "SELECT reference, full_name, student_id, phone_number, amount, short_code, tshirt "
                "FROM dues.payments WHERE status = 'successful' AND paid_at::date = current_date "
                "AND NOT sms_sent ORDER BY paid_at"
            ).fetchall()
            if not rows:
                print("Nobody from today is missing a receipt.")
                return
        else:
            row = conn.execute(
                "SELECT reference, full_name, student_id, phone_number, amount, short_code, tshirt "
                "FROM dues.payments WHERE UPPER(student_id) = %s AND status = 'successful'",
                (args.student_id.strip().upper(),),
            ).fetchone()
            if not row:
                print(f"No successful payment found for student ID {args.student_id}.")
                return
            rows = [row]

        for row in rows:
            try:
                send_one(conn, row)
            except Exception as e:
                print(f"FAILED for {row['full_name']} ({row['student_id']}): {e}")


if __name__ == "__main__":
    main()
