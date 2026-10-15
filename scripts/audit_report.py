"""Build the COSSA dues payment statement as a PDF from the live database.

Follows the layout of the September audit: executive summary, collections by
category, full ledger, pending follow-up, issue reports, expenses and system
notes. Money figures count only successful payments (confirmed by SasuSync's
signed webhook) and recorded expenses. Pending and voided rows are listed but
never counted as money.

    python scripts/audit_report.py --out ~/Desktop/COSSA_Dues_Statement.pdf

Pass --paid-only for a collections report with no pending section at all —
just who has paid, the category breakdown, expenses and the balance:

    python scripts/audit_report.py --out ~/Desktop/COSSA_Collections.pdf --paid-only
"""

import argparse
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
LOGO = ROOT / "app" / "static" / "cossa-logo.jpeg"

BLUE = colors.HexColor("#0f4c81")
BAND = colors.HexColor("#f3f6fa")
GRID = colors.HexColor("#d8dee6")
GREEN = colors.HexColor("#1e7b34")
AMBER = colors.HexColor("#b7791f")
RED = colors.HexColor("#c0392b")

# Expenses paid out but not yet recorded in dues.expenses. Remove an entry
# once it has been inserted into the table, or it will be counted twice.
EXTRA_EXPENSES = [
    {
        "spent_at": datetime(2026, 10, 1),
        "paid_to": "Zadok Nana Kwasi Akpah",
        "reason": "Refreshments for the lectures",
        "amount": Decimal("200.00"),
    },
]

CATEGORY_LABELS = {
    "continuing_exact": "Continuing",
    "continuing_name_only": "Continuing (ID changed)",
    "continuing_override": "Continuing (vouched by exec)",
    "fresher": "Fresher / not found",
}

STATUS_COLOURS = {"successful": GREEN, "pending": AMBER, "failed": RED, "open": RED, "resolved": GREEN}

_base = getSampleStyleSheet()
TITLE = ParagraphStyle("Title2", parent=_base["Title"], textColor=BLUE, fontSize=20, leading=24, alignment=1)
SUBTITLE = ParagraphStyle("Sub", parent=_base["BodyText"], fontSize=9, leading=12, textColor=colors.HexColor("#333333"))
H2 = ParagraphStyle("H2", parent=_base["Heading2"], textColor=BLUE, fontSize=13, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("Body", parent=_base["BodyText"], fontSize=9, leading=12)
NOTE = ParagraphStyle("Note", parent=_base["BodyText"], fontSize=7.5, leading=10, textColor=colors.HexColor("#666666"))
CELL = ParagraphStyle("Cell", parent=_base["BodyText"], fontSize=8, leading=10)
FOOTER = ParagraphStyle("Footer", parent=NOTE, alignment=1)


def ghs(value) -> str:
    return f"GHS {Decimal(value):,.2f}"


def status_cell(status: str) -> Paragraph:
    colour = STATUS_COLOURS.get(status, colors.black).hexval()
    return Paragraph(f'<font color="{colour}"><b>{status.upper()}</b></font>', CELL)


def fetch(conn):
    payments = conn.execute(
        "SELECT full_name, student_id, match_type, amount, status, paid_at, created_at, tshirt "
        "FROM dues.payments ORDER BY created_at"
    ).fetchall()
    expenses = conn.execute(
        "SELECT spent_at, paid_to, reason, amount FROM dues.expenses ORDER BY spent_at"
    ).fetchall()
    issues = conn.execute(
        "SELECT full_name, student_id, category, status, created_at FROM dues.issue_reports ORDER BY created_at"
    ).fetchall()
    overrides = conn.execute(
        "SELECT student_id, full_name, created_at FROM dues.manual_overrides ORDER BY created_at"
    ).fetchall()
    webhooks = conn.execute(
        "SELECT verified, count(*) AS n FROM dues.webhook_events GROUP BY verified"
    ).fetchall()
    return payments, expenses, issues, overrides, webhooks


def table(rows, col_widths, right_cols=(), bold_rows=(), header=True):
    wrapped = [
        [c if isinstance(c, (Paragraph, Image)) else Paragraph(str(c), CELL) for c in row]
        for row in rows
    ]
    t = Table(wrapped, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    style = [
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BAND]),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    for c in right_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    for r in bold_rows:
        style.append(("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def header_cell(text: str) -> Paragraph:
    return Paragraph(f'<font color="white"><b>{text}</b></font>', CELL)


def build(payments, expenses, issues, overrides, webhooks, out_path: Path, paid_only: bool = False) -> dict:
    expenses = sorted(list(expenses) + EXTRA_EXPENSES, key=lambda e: e["spent_at"])
    voided = [p for p in payments if p["status"] == "voided"]
    live = [p for p in payments if p["status"] != "voided"]

    successful = [p for p in live if p["status"] == "successful"]
    failed = [p for p in live if p["status"] == "failed"]
    paid_ids = {p["student_id"].upper() for p in successful}

    # One pending line per student, and none for anyone who has since paid.
    pending_by_student = {}
    for p in live:
        if p["status"] == "pending" and p["student_id"].upper() not in paid_ids:
            pending_by_student[p["student_id"].upper()] = p  # ordered oldest first, so the latest wins
    pending = list(pending_by_student.values())

    collected = sum((Decimal(p["amount"]) for p in successful), Decimal("0"))
    spent = sum((Decimal(e["amount"]) for e in expenses), Decimal("0"))
    net = collected - spent
    pending_total = sum((Decimal(p["amount"]) for p in pending), Decimal("0"))
    failed_total = sum((Decimal(p["amount"]) for p in failed), Decimal("0"))

    by_cat: dict[str, list] = {}
    for p in successful:
        by_cat.setdefault(p["match_type"], []).append(p)

    story = []
    width = A4[0] - 36 * mm

    logo = Image(str(LOGO), width=20 * mm, height=20 * mm)
    title_block = [
        Paragraph("COSSA Departmental Dues", TITLE),
        Paragraph("Collections Report" if paid_only else "Payment Statement", TITLE),
    ]
    head = Table([[logo, title_block]], colWidths=[24 * mm, width - 24 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(head)
    story.append(Paragraph(
        "Computing Science Students' Association · Valley View University<br/>"
        f"Prepared for the COSSA Executive Committee · Generated {datetime.now():%A, %d %B %Y at %H:%M}",
        SUBTITLE,
    ))
    story.append(Spacer(1, 4 * mm))

    section = iter(range(1, 20))

    story.append(Paragraph(f"{next(section)}. Executive Summary", H2))
    if paid_only:
        summary = [
            [Paragraph("Collected (confirmed paid)", CELL),
             Paragraph(f'<font color="{GREEN.hexval()}"><b>{ghs(collected)}</b></font>', CELL),
             f"{len(successful)} payment(s)"],
            [Paragraph("Expenses", CELL), ghs(spent), f"{len(expenses)} item(s)"],
            [Paragraph("<b>Balance on hand</b>", CELL), Paragraph(f"<b>{ghs(net)}</b>", CELL), ""],
        ]
    else:
        summary = [
            [Paragraph("Collected (confirmed paid)", CELL),
             Paragraph(f'<font color="{GREEN.hexval()}"><b>{ghs(collected)}</b></font>', CELL),
             f"{len(successful)} payment(s)"],
            [Paragraph("Expenses", CELL), ghs(spent), f"{len(expenses)} item(s)"],
            [Paragraph("<b>Balance on hand</b>", CELL), Paragraph(f"<b>{ghs(net)}</b>", CELL), ""],
            [Paragraph("Pending / in progress", CELL), ghs(pending_total), f"{len(pending)} student(s)"],
            [Paragraph("Failed", CELL), ghs(failed_total), f"{len(failed)} payment(s)"],
            [Paragraph("Students who have started the process", CELL),
             "", str(len({p["student_id"].upper() for p in live}))],
        ]
    story.append(table(summary, [width * 0.5, width * 0.3, width * 0.2], right_cols=(2,), header=False))
    if paid_only:
        story.append(Paragraph(
            "Confirmed, successful payments only. Every one was verified by SasuSync's signed webhook, not "
            f"just by the student reaching the return page. {len(voided)} test or duplicate record(s) are "
            "voided and excluded from every figure.",
            NOTE,
        ))
    else:
        story.append(Paragraph(
            "\"Pending\" means a student opened checkout but has not completed payment. It is not money lost, "
            "and it is not counted in the balance. Every successful payment below was confirmed by SasuSync's "
            f"signed webhook, not just by the student reaching the return page. {len(voided)} test or duplicate "
            "record(s) are voided and excluded from every figure; they are kept in the system so the correction stays visible.",
            NOTE,
        ))

    story.append(Paragraph(f"{next(section)}. Collections by Category (confirmed paid only)", H2))
    cat_rows = [[header_cell("Category"), header_cell("Count"), header_cell("Amount (GHS)")]]
    for key, rows in by_cat.items():
        cat_rows.append([
            CATEGORY_LABELS.get(key, key),
            str(len(rows)),
            f"{sum(Decimal(r['amount']) for r in rows):,.2f}",
        ])
    cat_rows.append(["Total", str(len(successful)), f"{collected:,.2f}"])
    story.append(table(cat_rows, [width * 0.6, width * 0.2, width * 0.2], right_cols=(1, 2), bold_rows=[len(cat_rows) - 1]))

    if paid_only:
        story.append(Paragraph(f"{next(section)}. Students Who Have Paid", H2))
        ledger = [[header_cell(h) for h in ("Name", "Student ID", "Category", "Amount", "Paid")]]
        for p in successful:
            ledger.append([
                p["full_name"],
                p["student_id"],
                CATEGORY_LABELS.get(p["match_type"], p["match_type"]),
                f"GHS {Decimal(p['amount']):,.2f}",
                f"{p['paid_at']:%d %b %Y}" if p["paid_at"] else "",
            ])
        story.append(table(
            ledger,
            [width * 0.26, width * 0.17, width * 0.21, width * 0.16, width * 0.2],
            right_cols=(3,),
        ))
    else:
        story.append(Paragraph(f"{next(section)}. Full Transaction Ledger", H2))
        ledger = [[header_cell(h) for h in ("Name", "Student ID", "Category", "Amount", "Status", "Date")]]
        for p in live:
            when = p["paid_at"] if p["status"] == "successful" and p["paid_at"] else p["created_at"]
            ledger.append([
                p["full_name"],
                p["student_id"],
                CATEGORY_LABELS.get(p["match_type"], p["match_type"]),
                f"GHS {Decimal(p['amount']):,.2f}",
                status_cell(p["status"]),
                f"{when:%d %b %Y}",
            ])
        story.append(table(
            ledger,
            [width * 0.23, width * 0.15, width * 0.19, width * 0.13, width * 0.16, width * 0.14],
            right_cols=(3,),
        ))

        story.append(Paragraph(f"{next(section)}. Pending Payments Needing Follow-Up", H2))
        if pending:
            for p in pending:
                story.append(Paragraph(
                    f"• {p['full_name']} ({p['student_id']}) — {ghs(p['amount'])}, started {p['created_at']:%d %b %Y}.",
                    BODY,
                ))
            story.append(Paragraph(
                f"{len(pending)} student(s) totalling {ghs(pending_total)} have not completed payment. "
                "Students who have since paid are not listed here.",
                NOTE,
            ))
        else:
            story.append(Paragraph("No students are waiting to complete payment.", BODY))

    story.append(Paragraph(f"{next(section)}. Issue Reports (student-submitted)", H2))
    if issues:
        issue_rows = [[header_cell(h) for h in ("Name", "Student ID", "Category claimed", "Status")]]
        for i in issues:
            issue_rows.append([
                i["full_name"],
                i["student_id"],
                i["category"].replace("_", " ").capitalize(),
                status_cell(i["status"]),
            ])
        story.append(table(issue_rows, [width * 0.36, width * 0.22, width * 0.26, width * 0.16]))
    else:
        story.append(Paragraph("No issue reports.", BODY))

    story.append(Paragraph(f"{next(section)}. Expenses", H2))
    exp_rows = [[header_cell(h) for h in ("Date", "Paid to", "Reason", "Amount")]]
    for e in expenses:
        exp_rows.append([f"{e['spent_at']:%d %b %Y}", e["paid_to"], e["reason"], ghs(e["amount"])])
    exp_rows.append(["", "", Paragraph("<b>Total</b>", CELL), Paragraph(f"<b>{ghs(spent)}</b>", CELL)])
    story.append(table(exp_rows, [width * 0.18, width * 0.3, width * 0.32, width * 0.2], right_cols=(3,)))

    story.append(Paragraph(f"{next(section)}. System Integrity Notes", H2))
    verified = sum(w["n"] for w in webhooks if w["verified"])
    unverified = sum(w["n"] for w in webhooks if not w["verified"])
    notes = [
        f"• {verified} payment webhook(s) received and cryptographically verified (signed by SasuSync). "
        f"{unverified} unverified or rejected delivery attempt(s).",
        f"• {len(overrides)} manual override(s) on file. A continuing student not found in the university "
        "records is only added here after an executive vouches for them by name and student ID.",
    ]
    for o in overrides:
        notes.append(f"    – {o['full_name']} ({o['student_id']}), added {o['created_at']:%d %b %Y}.")
    for n in notes:
        story.append(Paragraph(n, BODY))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Powered by SasuSync.com in partnership with COSSA.", FOOTER))

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="COSSA Dues Payment Statement", author="COSSA",
    )
    doc.build(story)

    return {
        "collected": collected,
        "spent": spent,
        "net": net,
        "pending": pending_total,
        "paid_count": len(successful),
        "pending_count": len(pending),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="path of the PDF to write")
    parser.add_argument(
        "--paid-only", action="store_true",
        help="leave out pending payments entirely — a collections report of who has paid",
    )
    args = parser.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        data = fetch(conn)

    totals = build(*data, Path(args.out).expanduser(), paid_only=args.paid_only)
    print(f"Wrote {args.out}")
    print(f"Collected: {ghs(totals['collected'])} ({totals['paid_count']} paid)")
    print(f"Expenses:  {ghs(totals['spent'])}")
    print(f"Balance:   {ghs(totals['net'])}")
    if not args.paid_only:
        print(f"Pending:   {ghs(totals['pending'])} ({totals['pending_count']} students)")


if __name__ == "__main__":
    main()
