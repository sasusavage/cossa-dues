"""Mark a student's COSSA t-shirt as collected (or undo that).

Only works on a student who's actually eligible for one: any fresher who
has paid dues (it's bundled into their GHS 100), or a continuing student
who paid the t-shirt add-on. No admin UI yet, so this is how it's recorded.

    python scripts/mark_tshirt_collected.py --student-id 227IT01001392
    python scripts/mark_tshirt_collected.py --student-id 227IT01001392 --undo
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--undo", action="store_true", help="mark it as not collected instead")
    args = parser.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        row = conn.execute(
            "SELECT reference, full_name, status, tshirt, shirt_collected FROM dues.payments "
            "WHERE UPPER(student_id) = %s AND status = 'successful'",
            (args.student_id.strip().upper(),),
        ).fetchone()

        if not row:
            print(f"No successful payment found for student ID {args.student_id}.")
            return
        if not row["tshirt"]:
            print(f"{row['full_name']} ({args.student_id}) hasn't paid for a t-shirt — nothing to mark.")
            return

        collected = not args.undo
        conn.execute(
            "UPDATE dues.payments SET shirt_collected = %s, "
            "shirt_collected_at = CASE WHEN %s THEN now() ELSE NULL END, updated_at = now() "
            "WHERE reference = %s",
            (collected, collected, row["reference"]),
        )
        print(f"{row['full_name']} ({args.student_id}): shirt marked as "
              f"{'collected' if collected else 'not collected'}.")


if __name__ == "__main__":
    main()
