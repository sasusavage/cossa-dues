"""Build the COSSA student register PDF: the CS/IT Accra roster, cross-
referenced against who has paid dues. Paid students are listed at the top
(freshers and continuing students separately), everyone else below as not
yet paid, followed by the same financial summary and expenses as the other
reports.

    python scripts/student_register_report.py --out ~/Desktop/COSSA_Student_Register.pdf
"""

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.matching import normalize_name  # noqa: E402
from scripts.audit_report import (  # noqa: E402
    GREEN, LOGO, TITLE, SUBTITLE, H2, NOTE, CELL, FOOTER,
    header_cell, table, ghs, EXTRA_EXPENSES,
)
from datetime import datetime  # noqa: E402


def fetch(conn):
    roster = conn.execute(
        "SELECT student_id, full_name, department FROM dues.student_roster ORDER BY department, full_name"
    ).fetchall()
    payments = conn.execute(
        "SELECT full_name, student_id, match_type, amount, paid_at FROM dues.payments WHERE status = 'successful'"
    ).fetchall()
    expenses = conn.execute(
        "SELECT spent_at, paid_to, reason, amount FROM dues.expenses ORDER BY spent_at"
    ).fetchall()
    return roster, payments, expenses


def match_payment(student, payments_by_id, payments_by_name):
    p = payments_by_id.get(student["student_id"])
    if p:
        return p
    key = frozenset(normalize_name(student["full_name"]))
    if not key:
        return None
    for words, p in payments_by_name:
        if words and (words.issubset(key) or key.issubset(words)):
            return p
    return None


def roster_table(rows, width, show_amount=True):
    if show_amount:
        body = [[header_cell(h) for h in ("Name", "Student ID", "Dept", "Amount", "Paid")]]
        widths = [width * 0.36, width * 0.22, width * 0.1, width * 0.16, width * 0.16]
    else:
        body = [[header_cell(h) for h in ("Name", "Student ID", "Dept")]]
        widths = [width * 0.5, width * 0.3, width * 0.2]
    for r in rows:
        if show_amount:
            body.append([
                r["full_name"], r["student_id"], r["department"],
                f"GHS {Decimal(r['payment']['amount']):,.2f}",
                f"{r['payment']['paid_at']:%d %b %Y}" if r["payment"]["paid_at"] else "",
            ])
        else:
            body.append([r["full_name"], r["student_id"], r["department"]])
    return table(body, widths, right_cols=([3] if show_amount else []))


def build(roster, payments, expenses, out_path: Path) -> dict:
    payments_by_id = {p["student_id"].upper(): p for p in payments}
    payments_by_name = [(frozenset(normalize_name(p["full_name"])), p) for p in payments]

    paid_fresher, paid_continuing, unpaid = [], [], []
    for s in roster:
        p = match_payment(s, payments_by_id, payments_by_name)
        if not p:
            unpaid.append(s)
        elif p["match_type"] == "fresher":
            paid_fresher.append({**s, "payment": p})
        else:
            paid_continuing.append({**s, "payment": p})

    expenses = sorted(list(expenses) + EXTRA_EXPENSES, key=lambda e: e["spent_at"])
    collected = sum((Decimal(p["amount"]) for p in payments), Decimal("0"))
    spent = sum((Decimal(e["amount"]) for e in expenses), Decimal("0"))
    net = collected - spent

    story = []
    width = A4[0] - 36 * mm

    logo = Image(str(LOGO), width=20 * mm, height=20 * mm)
    title_block = [Paragraph("COSSA Departmental Dues", TITLE), Paragraph("Student Register", TITLE)]
    head = Table([[logo, title_block]], colWidths=[24 * mm, width - 24 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(head)
    story.append(Paragraph(
        "Computing Science Students' Association · Valley View University<br/>"
        f"Prepared for the COSSA Executive Committee · Generated {datetime.now():%A, %d %B %Y at %H:%M}",
        SUBTITLE,
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Computer Science and Information Technology students, Accra campus, cross-checked against the "
        "faculty student register. Paid students are listed first, by category; everyone else follows as not yet paid.",
        NOTE,
    ))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(f"1. Paid — Freshers ({len(paid_fresher)})", H2))
    story.append(roster_table(sorted(paid_fresher, key=lambda r: r["full_name"]), width) if paid_fresher
                  else Paragraph("None.", CELL))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(f"2. Paid — Continuing Students ({len(paid_continuing)})", H2))
    story.append(roster_table(sorted(paid_continuing, key=lambda r: r["full_name"]), width) if paid_continuing
                  else Paragraph("None.", CELL))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(f"3. Not Yet Paid ({len(unpaid)})", H2))
    story.append(roster_table(sorted(unpaid, key=lambda r: (r["department"], r["full_name"])), width, show_amount=False)
                  if unpaid else Paragraph("None.", CELL))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("4. Account Summary", H2))
    summary = [
        [Paragraph("Collected (confirmed paid)", CELL),
         Paragraph(f'<font color="{GREEN.hexval()}"><b>{ghs(collected)}</b></font>', CELL)],
        [Paragraph("Expenses", CELL), ghs(spent)],
        [Paragraph("<b>Balance on hand</b>", CELL), Paragraph(f"<b>{ghs(net)}</b>", CELL)],
    ]
    story.append(table(summary, [width * 0.6, width * 0.4], header=False))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("5. Expenses", H2))
    exp_rows = [[header_cell(h) for h in ("Date", "Paid to", "Reason", "Amount")]]
    for e in expenses:
        exp_rows.append([f"{e['spent_at']:%d %b %Y}", e["paid_to"], e["reason"], ghs(e["amount"])])
    exp_rows.append(["", "", Paragraph("<b>Total</b>", CELL), Paragraph(f"<b>{ghs(spent)}</b>", CELL)])
    story.append(table(exp_rows, [width * 0.18, width * 0.3, width * 0.32, width * 0.2], right_cols=(3,)))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Powered by SasuSync.com in partnership with COSSA.", FOOTER))

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="COSSA Student Register", author="COSSA",
    )
    doc.build(story)

    return {
        "paid_fresher": len(paid_fresher), "paid_continuing": len(paid_continuing), "unpaid": len(unpaid),
        "collected": collected, "spent": spent, "net": net,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        roster, payments, expenses = fetch(conn)

    totals = build(roster, payments, expenses, Path(args.out).expanduser())
    print(f"Wrote {args.out}")
    print(f"Paid freshers: {totals['paid_fresher']}, paid continuing: {totals['paid_continuing']}, "
          f"not yet paid: {totals['unpaid']}")
    print(f"Collected: {ghs(totals['collected'])}  Expenses: {ghs(totals['spent'])}  Balance: {ghs(totals['net'])}")


if __name__ == "__main__":
    main()
