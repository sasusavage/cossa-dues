"""Log a dues payment collected in person (cash/MoMo handed to an exec),
not through SasuSync checkout.

If the student has a pending online attempt, it's converted into the paid
record (so the amount/category already determined for them is kept, and
any other pending attempts for the same student are voided as superseded).
Otherwise a new record is created directly as successful.

Sends the same SMS receipt and Telegram alert an online payment would, with
the payment marked as channel 'cash' throughout.

    python scripts/log_cash_payment.py \\
        --full-name "Sabina Agamah Williams" --student-id 227DIT0101339 \\
        --phone 0542109588 --category fresher
"""

import argparse
import logging
import os
import secrets
import sys
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app import sms_client, telegram_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("log_cash_payment")

SHORT_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
CONTINUING_AMOUNT = float(os.environ.get("DUES_AMOUNT_CONTINUING", "50"))
FRESHER_AMOUNT = float(os.environ.get("DUES_AMOUNT_FRESHER", "100"))
TSHIRT_AMOUNT = float(os.environ.get("TSHIRT_AMOUNT", "55"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")


def generate_short_code(length: int = 7) -> str:
    return "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(length))


def sanitize_ref_part(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "", s)[:20] or "na"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--category", choices=["continuing", "fresher"], required=True)
    parser.add_argument("--tshirt", action="store_true", help="dues plus the t-shirt add-on (continuing only)")
    parser.add_argument("--no-sms", action="store_true", help="skip the SMS receipt")
    parser.add_argument("--no-telegram", action="store_true", help="skip the Telegram alert")
    args = parser.parse_args()

    student_id = args.student_id.strip()
    full_name = args.full_name.strip()
    phone = args.phone.strip()
    wants_tshirt = args.tshirt and args.category == "continuing"
    base_amount = CONTINUING_AMOUNT if args.category == "continuing" else FRESHER_AMOUNT
    amount = base_amount + (TSHIRT_AMOUNT if wants_tshirt else 0)

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        # Make sure the channel column exists even if this runs before a deploy picks up the migration.
        conn.execute("ALTER TABLE dues.payments ADD COLUMN IF NOT EXISTS channel VARCHAR(20) NOT NULL DEFAULT 'online'")

        rows = conn.execute(
            "SELECT * FROM dues.payments WHERE UPPER(student_id) = %s ORDER BY created_at",
            (student_id.upper(),),
        ).fetchall()

        already_paid = next((r for r in rows if r["status"] == "successful"), None)
        if already_paid:
            log.info("%s (%s) already has a successful payment: %s — nothing logged.",
                      full_name, student_id, already_paid["reference"])
            return

        pending = [r for r in rows if r["status"] == "pending"]

        if pending:
            keep = pending[-1]
            for extra in pending[:-1]:
                conn.execute(
                    "UPDATE dues.payments SET status = 'voided', updated_at = now() WHERE reference = %s",
                    (extra["reference"],),
                )
                log.info("Voided superseded pending attempt %s", extra["reference"])

            payment = conn.execute(
                """
                UPDATE dues.payments
                SET status = 'successful', paid_at = now(), updated_at = now(),
                    channel = 'cash', full_name = %s, phone_number = %s,
                    payer_phone = %s, payer_name = %s, amount = %s, tshirt = %s
                WHERE reference = %s
                RETURNING *
                """,
                (full_name, phone, phone, full_name, amount, wants_tshirt, keep["reference"]),
            ).fetchone()
            log.info("Converted pending attempt %s into a cash payment.", payment["reference"])
        else:
            reference = f"cossadues-cash-{sanitize_ref_part(student_id)}-{uuid.uuid4().hex[:8]}"
            match_type = "continuing_override" if args.category == "continuing" else "fresher"
            for _ in range(5):
                short_code = generate_short_code()
                try:
                    payment = conn.execute(
                        """
                        INSERT INTO dues.payments
                            (reference, full_name, student_id, match_type, phone_number, amount,
                             status, paid_at, payer_phone, payer_name, short_code, channel, tshirt)
                        VALUES (%s,%s,%s,%s,%s,%s,'successful',now(),%s,%s,%s,'cash',%s)
                        RETURNING *
                        """,
                        (reference, full_name, student_id, match_type, phone, amount,
                         phone, full_name, short_code, wants_tshirt),
                    ).fetchone()
                    break
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    continue
            else:
                raise SystemExit("Could not allocate a receipt code, try again")
            log.info("Logged new cash payment %s", payment["reference"])

    log.info("%s | %s | GHS %.2f | %s%s", full_name, student_id, amount, args.category,
              " + t-shirt" if wants_tshirt else "")

    if not args.no_sms:
        link = f"{APP_BASE_URL}/r/{payment['short_code']}"
        message = f"COSSA Dues: GHS {amount:.2f} received (cash). Receipt: {link}"
        try:
            sms_client.send_sms(phone, message)
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as conn2:
                conn2.execute("UPDATE dues.payments SET sms_sent = true WHERE reference = %s", (payment["reference"],))
            log.info("SMS receipt sent to %s", phone)
        except Exception:
            log.exception("Failed to send SMS receipt")

    if not args.no_telegram:
        try:
            telegram_client.send_telegram(
                "✅ <b>Dues paid (cash)</b>\n"
                f"Name: {full_name}\n"
                f"Student ID: {student_id}\n"
                f"Category: {match_type if not pending else keep['match_type']}\n"
                f"Amount: GHS {amount:.2f}\n"
                f"Phone: {phone}\n"
                f"Ref: {payment['reference']}"
            )
            log.info("Telegram alert sent")
        except Exception:
            log.exception("Failed to send Telegram alert")


if __name__ == "__main__":
    main()
