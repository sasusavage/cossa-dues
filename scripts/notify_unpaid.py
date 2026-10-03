"""Text everyone who tried to pay but hasn't paid, to say payment is now live.

Dry run by default — prints who would be texted and sends nothing. Pass
--send to actually send. Anyone with a successful payment (matched by student
ID or phone number) is excluded, and each phone number is texted at most once.

    python scripts/notify_unpaid.py          # dry run
    python scripts/notify_unpaid.py --send   # send for real
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

RECIPIENTS_SQL = """
SELECT DISTINCT ON (p.phone_number)
       p.full_name, p.student_id, p.phone_number, p.status, p.created_at
FROM dues.payments p
WHERE p.status <> 'successful'
  AND p.phone_number NOT IN (
        SELECT phone_number FROM dues.payments WHERE status = 'successful'
      )
  AND UPPER(p.student_id) NOT IN (
        SELECT UPPER(student_id) FROM dues.payments WHERE status = 'successful'
      )
ORDER BY p.phone_number, p.created_at DESC
"""


def build_message() -> str:
    base = os.environ.get("APP_BASE_URL", "").rstrip("/")
    return (
        "COSSA Dues: payment is now live. Pay at "
        f"{base} (continuing GHS {os.environ.get('DUES_AMOUNT_CONTINUING', '50')}, "
        f"fresher GHS {os.environ.get('DUES_AMOUNT_FRESHER', '100')}). Thank you!"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="actually send the SMS")
    args = parser.parse_args()

    message = build_message()
    print(f"Message ({len(message)} chars):\n{message}\n")

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=15) as conn:
        rows = conn.execute(RECIPIENTS_SQL).fetchall()

    print(f"{len(rows)} recipient(s):")
    for r in rows:
        print(f"  {r['full_name']} | {r['student_id']} | {r['phone_number']} | last status: {r['status']}")

    if not args.send:
        print("\nDry run — nothing sent. Re-run with --send to text these people.")
        return

    sent = failed = 0
    for r in rows:
        try:
            sms_client.send_sms(r["phone_number"], message)
            sent += 1
        except Exception as exc:
            failed += 1
            print(f"FAILED {r['phone_number']}: {exc}")
    print(f"\nSent: {sent}, failed: {failed}")


if __name__ == "__main__":
    main()
