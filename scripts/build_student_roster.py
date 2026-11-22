"""Build dues.student_roster: COSSA's own CS/IT, Accra-campus student list.

Two sources, reconciled:
1. Seed from the shared `users` table (read-only, never written to), filtered
   to campus = Accra and department in {Computer Science, Information
   Technology}. No Techiman, no other departments, nothing from `users` is
   ever modified.
2. Reconcile against a faculty student register (a local text file, --input,
   one "Full Name  StudentID  Phone" row per line — never commit this file,
   it's real students' personal data): for each register row, if an existing
   roster row's name matches but the student ID differs, the register's ID
   wins (it's the more authoritative, more current source) and the roster
   row is updated. A register row with no name match in the roster is
   inserted as new.

Prints anything that looks off (duplicate IDs, suspiciously short IDs, more
than one roster row matching a single register name) instead of guessing.

    python scripts/build_student_roster.py --input ~/Downloads/register.txt
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

from app.matching import normalize_name  # noqa: E402

ID_RE = re.compile(r"\b(\d{3}D?[A-Z]{2,4}\d{6,8})\b")


def parse_register(text: str):
    rows = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("LEVEL") or line.startswith("Full Name"):
            continue
        id_match = ID_RE.search(line)
        if not id_match:
            print(f"SKIPPED (no ID found): {line!r}")
            continue
        student_id = id_match.group(1)
        if "BIS" in student_id:
            continue
        name = line[:id_match.start()].strip()
        phone = line[id_match.end():].strip() or "Not Provided"
        department = "CS" if "CS" in student_id else ("IT" if "IT" in student_id else None)
        if not department:
            print(f"SKIPPED (not CS/IT): {line!r}")
            continue
        rows.append({"full_name": name, "student_id": student_id.upper(), "phone_number": phone,
                      "department": department})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", required=True,
        help="path to a local register text file (one 'Name  StudentID  Phone' row per line) — never commit it",
    )
    args = parser.parse_args()

    register_rows = parse_register(Path(args.input).expanduser().read_text())
    print(f"Parsed {len(register_rows)} CS/IT rows from the register.")

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        conn.execute((ROOT / "migrations" / "008_student_roster.sql").read_text())

        seeded = conn.execute(
            """
            INSERT INTO dues.student_roster (student_id, full_name, department, phone_number, source)
            SELECT UPPER(student_id),
                   TRIM(COALESCE(surname,'') || ' ' || COALESCE(firstname,'') || ' ' || COALESCE(othernames,'')),
                   CASE WHEN department = 'Department of Computer Science' THEN 'CS' ELSE 'IT' END,
                   phone_number, 'users_table'
            FROM users
            WHERE campus = 'Accra'
              AND department IN ('Department of Computer Science', 'Department of Information Technology')
            ON CONFLICT (student_id) DO NOTHING
            RETURNING student_id
            """
        ).fetchall()
        print(f"Seeded {len(seeded)} new roster rows from the Accra CS/IT users.")

        roster = conn.execute("SELECT student_id, full_name FROM dues.student_roster").fetchall()
        by_name_words = {}
        for r in roster:
            key = frozenset(normalize_name(r["full_name"]))
            by_name_words.setdefault(key, []).append(r["student_id"])

        updated, inserted, ambiguous, unmatched_new = 0, 0, [], []
        for reg in register_rows:
            key = frozenset(normalize_name(reg["full_name"]))
            candidates = [
                sid for words, ids in by_name_words.items() for sid in ids
                if words and key and (words.issubset(key) or key.issubset(words))
            ]
            candidates = list(dict.fromkeys(candidates))

            # An exact ID match among the candidates means this register row already
            # matches a roster row precisely — nothing to resolve, regardless of how
            # many other roster rows happen to share overlapping name words.
            if reg["student_id"] in candidates:
                continue

            if len(candidates) > 1:
                ambiguous.append((reg["full_name"], reg["student_id"], candidates))
                continue

            if len(candidates) == 1:
                existing_id = candidates[0]
                conn.execute(
                    """
                    UPDATE dues.student_roster
                    SET student_id = %s, full_name = %s, phone_number = %s, source = 'register_pdf',
                        updated_at = now()
                    WHERE student_id = %s
                    """,
                    (reg["student_id"], reg["full_name"], reg["phone_number"], existing_id),
                )
                print(f"UPDATED ID: {reg['full_name']} — {existing_id} -> {reg['student_id']}")
                updated += 1
                continue

            # No match at all — brand new student (typically a fresh Level 100 intake).
            # ON CONFLICT is just a safety net (e.g. the name-match logic missing an
            # existing row); rowcount tells us whether a row actually landed.
            try:
                cur = conn.execute(
                    """
                    INSERT INTO dues.student_roster (student_id, full_name, department, phone_number, source)
                    VALUES (%s,%s,%s,%s,'register_pdf')
                    ON CONFLICT (student_id) DO NOTHING
                    """,
                    (reg["student_id"], reg["full_name"], reg["department"], reg["phone_number"]),
                )
                if cur.rowcount:
                    inserted += 1
            except psycopg.Error as e:
                unmatched_new.append((reg["full_name"], reg["student_id"], str(e)))

        dupes = conn.execute(
            "SELECT student_id, count(*) FROM dues.student_roster GROUP BY student_id HAVING count(*) > 1"
        ).fetchall()
        total = conn.execute("SELECT count(*) AS n FROM dues.student_roster").fetchone()["n"]

    print(f"\nIDs updated from register: {updated}")
    print(f"New students inserted: {inserted}")
    print(f"Total roster size: {total}")
    if ambiguous:
        print(f"\n{len(ambiguous)} AMBIGUOUS name match(es) — left untouched, review by hand:")
        for name, rid, cands in ambiguous:
            print(f"  {name} ({rid}) could match: {cands}")
    if unmatched_new:
        print(f"\n{len(unmatched_new)} row(s) failed to insert:")
        for name, rid, err in unmatched_new:
            print(f"  {name} ({rid}): {err}")
    if dupes:
        print(f"\nDuplicate student_id rows (shouldn't happen): {dupes}")


if __name__ == "__main__":
    main()
