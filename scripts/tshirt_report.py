"""Build the COSSA t-shirt collection report as a PDF — who's eligible for a
shirt, split into freshers (bundled into their dues) and continuing students
(paid add-on), and who has and hasn't collected theirs.

    python scripts/tshirt_report.py --out ~/Desktop/COSSA_Tshirt_Collection.pdf
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from scripts.audit_report import (  # noqa: E402
    BLUE, GREEN, AMBER, LOGO, TITLE, SUBTITLE, H2, NOTE, CELL,
    FOOTER, header_cell, table,
)


def fetch(conn):
    return conn.execute(
        "SELECT full_name, student_id, phone_number, match_type, paid_at, channel, "
        "shirt_collected, shirt_collected_at FROM dues.payments "
        "WHERE status = 'successful' AND tshirt ORDER BY match_type, paid_at"
    ).fetchall()


def collected_cell(collected: bool) -> Paragraph:
    colour = GREEN.hexval() if collected else AMBER.hexval()
    label = "COLLECTED" if collected else "NOT YET"
    return Paragraph(f'<font color="{colour}"><b>{label}</b></font>', CELL)


def section(story, title, rows, width):
    story.append(Paragraph(title, H2))
    if not rows:
        story.append(Paragraph("None.", CELL))
        return
    collected = sum(1 for r in rows if r["shirt_collected"])
    body = [[header_cell(h) for h in ("Name", "Student ID", "Phone", "Paid", "Status")]]
    for r in rows:
        body.append([
            r["full_name"],
            r["student_id"],
            r["phone_number"],
            f"{r['paid_at']:%d %b %Y}" if r["paid_at"] else "",
            collected_cell(r["shirt_collected"]),
        ])
    story.append(table(body, [width * 0.28, width * 0.18, width * 0.18, width * 0.16, width * 0.2]))
    story.append(Paragraph(f"{collected} of {len(rows)} collected, {len(rows) - collected} outstanding.", NOTE))
    story.append(Spacer(1, 4 * mm))


def build(rows, out_path: Path) -> dict:
    freshers = [r for r in rows if r["match_type"] == "fresher"]
    continuing = [r for r in rows if r["match_type"] != "fresher"]

    story = []
    width = A4[0] - 36 * mm

    logo = Image(str(LOGO), width=20 * mm, height=20 * mm)
    title_block = [Paragraph("COSSA Departmental Dues", TITLE), Paragraph("T-Shirt Collection", TITLE)]
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
        "A fresher's GHS 100 includes a t-shirt automatically. A continuing student only has one if they "
        "paid the t-shirt add-on at checkout — everyone else in that category isn't listed here at all.",
        NOTE,
    ))
    story.append(Spacer(1, 4 * mm))

    section(story, "1. Freshers (shirt included with dues)", freshers, width)
    section(story, "2. Continuing Students (paid the add-on)", continuing, width)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Powered by SasuSync.com in partnership with COSSA.", FOOTER))

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="COSSA T-Shirt Collection", author="COSSA",
    )
    doc.build(story)

    return {
        "freshers": len(freshers), "freshers_collected": sum(1 for r in freshers if r["shirt_collected"]),
        "continuing": len(continuing), "continuing_collected": sum(1 for r in continuing if r["shirt_collected"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=30) as conn:
        rows = fetch(conn)

    totals = build(rows, Path(args.out).expanduser())
    print(f"Wrote {args.out}")
    print(f"Freshers:   {totals['freshers_collected']} / {totals['freshers']} collected")
    print(f"Continuing: {totals['continuing_collected']} / {totals['continuing']} collected")


if __name__ == "__main__":
    main()
