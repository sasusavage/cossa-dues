import re
from dataclasses import dataclass
from typing import Optional

USER_FIELDS = "id, student_id, surname, firstname, othernames, username, department, program"


def normalize_name(name: str) -> set:
    name = name.upper()
    name = re.sub(r"[^A-Z\s]", " ", name)
    return {w for w in name.split() if w}


def _db_name_words(row: dict) -> set:
    # Most rows have surname/firstname/othernames split out, but a batch of
    # accounts only ever got a full name in `username` — fall back to that
    # rather than treating them as nameless (they're real continuing
    # students, just missing the split fields).
    parts = " ".join(p for p in [row.get("surname"), row.get("firstname"), row.get("othernames")] if p)
    words = normalize_name(parts)
    if not words and row.get("username"):
        words = normalize_name(row["username"])
    return words


@dataclass
class MatchResult:
    kind: str  # "continuing_exact" | "continuing_name_only" | "fresher" | "ambiguous"
    user: Optional[dict] = None


def find_match(conn, full_name: str, student_id: str) -> MatchResult:
    """
    Looks the student up in the existing (shared, read-only) `users` table.

    - Exact match on student_id, and the submitted name contains every word
      of the school's name on file -> continuing_exact.
    - No id match, but exactly one user's name is fully contained in the
      submitted name -> continuing_name_only (the diploma-to-top-up case,
      where the student's ID changed but they're the same person).
    - More than one name-only candidate -> ambiguous; routed to the manual
      issue form rather than guessing which record is theirs.
    - No match at all -> fresher.
    """
    sid = student_id.strip().upper()
    input_words = normalize_name(full_name)

    row = conn.execute(
        f"SELECT {USER_FIELDS} FROM users WHERE UPPER(student_id) = %s", (sid,)
    ).fetchone()

    if row:
        db_words = _db_name_words(row)
        if db_words and db_words.issubset(input_words):
            return MatchResult("continuing_exact", row)

    rows = conn.execute(f"SELECT {USER_FIELDS} FROM users").fetchall()
    candidates = [r for r in rows if _db_name_words(r) and _db_name_words(r).issubset(input_words)]

    if len(candidates) == 1:
        return MatchResult("continuing_name_only", candidates[0])
    if len(candidates) > 1:
        return MatchResult("ambiguous")

    return MatchResult("fresher")
