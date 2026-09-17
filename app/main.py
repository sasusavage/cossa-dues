import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from . import db, matching, payments_client, sms_client, telegram_client  # noqa: E402

log = logging.getLogger("cossa_dues")

APP_DIR = Path(__file__).parent
MIGRATION_SQL = (APP_DIR.parent / "migrations" / "001_dues_schema.sql").read_text()

CONTINUING_AMOUNT = float(os.environ.get("DUES_AMOUNT_CONTINUING", "50"))
FRESHER_AMOUNT = float(os.environ.get("DUES_AMOUNT_FRESHER", "100"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

app = FastAPI(title="COSSA Dues Portal")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@app.on_event("startup")
def run_migrations():
    with db.pool.connection() as conn:
        conn.execute(MIGRATION_SQL)
        conn.execute("DELETE FROM dues.pending_checks WHERE created_at < now() - interval '1 day'")


@app.get("/healthz")
def healthz():
    return {"ok": True}


def sanitize_ref_part(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s)[:20] or "na"


def category_label(match_kind: str) -> str:
    return "Continuing Student" if match_kind in ("continuing_exact", "continuing_name_only") else "New / Fresher Student"


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/check", response_class=HTMLResponse)
def check(
    request: Request,
    full_name: str = Form(...),
    student_id: str = Form(...),
    phone_number: str = Form(...),
    email: str = Form(""),
):
    full_name = full_name.strip()
    student_id = student_id.strip()
    phone_number = phone_number.strip()
    email = email.strip() or None

    if not full_name or not student_id or not phone_number:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Full name, student ID and phone number are all required."},
        )

    with db.pool.connection() as conn:
        result = matching.find_match(conn, full_name, student_id)

    if result.kind == "ambiguous":
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": "We found more than one matching record and can't be sure which is yours. "
                "Please use the issue form instead so we can check it by hand.",
                "full_name": full_name,
                "student_id": student_id,
                "phone_number": phone_number,
                "email": email or "",
            },
        )

    amount = CONTINUING_AMOUNT if result.kind in ("continuing_exact", "continuing_name_only") else FRESHER_AMOUNT
    user = result.user

    token = uuid.uuid4().hex
    with db.pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO dues.pending_checks
                (token, full_name, student_id, phone_number, email, match_type,
                 matched_user_id, department, program, amount)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                token, full_name, student_id, phone_number, email, result.kind,
                user["id"] if user else None,
                user["department"] if user else None,
                user["program"] if user else None,
                amount,
            ),
        )

    return templates.TemplateResponse(
        "confirm.html",
        {
            "request": request,
            "token": token,
            "category_label": category_label(result.kind),
            "amount": amount,
            "full_name": full_name,
        },
    )


@app.post("/pay")
def pay(request: Request, token: str = Form(...)):
    with db.pool.connection() as conn:
        chk = conn.execute("SELECT * FROM dues.pending_checks WHERE token = %s", (token,)).fetchone()

        if not chk or chk["created_at"] < datetime.utcnow() - timedelta(hours=1):
            return templates.TemplateResponse(
                "index.html", {"request": request, "error": "That check has expired — please try again."}
            )

        if chk["matched_user_id"]:
            identity_clause = "matched_user_id = %s"
            identity_val = chk["matched_user_id"]
        else:
            identity_clause = "matched_user_id IS NULL AND UPPER(student_id) = %s"
            identity_val = chk["student_id"].upper()

        existing_paid = conn.execute(
            f"SELECT * FROM dues.payments WHERE status = 'successful' AND {identity_clause} "
            "ORDER BY id DESC LIMIT 1",
            (identity_val,),
        ).fetchone()
        if existing_paid:
            return RedirectResponse(f"/receipt/{existing_paid['reference']}", status_code=303)

        reusable = conn.execute(
            f"SELECT * FROM dues.payments WHERE status = 'pending' "
            f"AND created_at > now() - interval '2 hours' AND {identity_clause} "
            "ORDER BY id DESC LIMIT 1",
            (identity_val,),
        ).fetchone()

        if reusable:
            checkout_url = reusable["checkout_url"]
        else:
            reference = f"cossadues-{sanitize_ref_part(chk['student_id'])}-{uuid.uuid4().hex[:8]}"
            resp = payments_client.create_payment(
                reference=reference,
                amount=float(chk["amount"]),
                email=chk["email"],
                redirect_url=f"{APP_BASE_URL}/receipt/{reference}",
                metadata={
                    "student_id": chk["student_id"],
                    "full_name": chk["full_name"],
                    "match_type": chk["match_type"],
                },
            )
            checkout_url = resp["checkout_url"]
            conn.execute(
                """
                INSERT INTO dues.payments
                    (reference, full_name, student_id, matched_user_id, match_type,
                     department, program, phone_number, email, amount, status, checkout_url)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)
                """,
                (
                    reference, chk["full_name"], chk["student_id"], chk["matched_user_id"], chk["match_type"],
                    chk["department"], chk["program"], chk["phone_number"], chk["email"], chk["amount"],
                    checkout_url,
                ),
            )

    return RedirectResponse(checkout_url, status_code=303)


@app.get("/receipt/{reference}", response_class=HTMLResponse)
def receipt(request: Request, reference: str):
    with db.pool.connection() as conn:
        row = conn.execute("SELECT * FROM dues.payments WHERE reference = %s", (reference,)).fetchone()
        if not row:
            raise HTTPException(404)

        if row["status"] == "pending":
            # The redirect back here can happen before the webhook lands, so
            # proactively ask SasuSync ourselves rather than leaving the
            # student stuck on a stale "pending" page.
            try:
                live = payments_client.get_payment(reference)
            except Exception:
                live = None

            if live and live["status"] == "successful":
                conn.execute(
                    "UPDATE dues.payments SET status = 'successful', paid_at = %s, updated_at = now() "
                    "WHERE reference = %s AND status != 'successful'",
                    (live["paid_at"], reference),
                )
                row = conn.execute("SELECT * FROM dues.payments WHERE reference = %s", (reference,)).fetchone()
            elif live and live["status"] == "failed":
                conn.execute(
                    "UPDATE dues.payments SET status = 'failed', updated_at = now() WHERE reference = %s",
                    (reference,),
                )
                row = conn.execute("SELECT * FROM dues.payments WHERE reference = %s", (reference,)).fetchone()

    if row["status"] == "successful":
        return templates.TemplateResponse("receipt.html", {"request": request, "payment": row})
    if row["status"] == "failed":
        return templates.TemplateResponse("failed.html", {"request": request, "payment": row})
    return templates.TemplateResponse("pending.html", {"request": request, "payment": row})


def fulfil_payment(payment: dict):
    message = (
        f"COSSA Dues receipt\nRef: {payment['reference']}\n"
        f"Name: {payment['full_name']}\nAmount: GHS {float(payment['amount']):.2f}\n"
        "Status: PAID. Thank you."
    )
    try:
        sms_client.send_sms(payment["phone_number"], message)
        with db.pool.connection() as conn:
            conn.execute("UPDATE dues.payments SET sms_sent = true WHERE reference = %s", (payment["reference"],))
    except Exception:
        log.exception("Failed to send SMS receipt for %s", payment["reference"])

    try:
        telegram_client.send_telegram(
            "✅ <b>Dues paid</b>\n"
            f"Name: {payment['full_name']}\n"
            f"Student ID: {payment['student_id']}\n"
            f"Category: {payment['match_type']}\n"
            f"Amount: GHS {float(payment['amount']):.2f}\n"
            f"Phone: {payment['phone_number']}\n"
            f"Ref: {payment['reference']}"
        )
        with db.pool.connection() as conn:
            conn.execute(
                "UPDATE dues.payments SET telegram_notified = true WHERE reference = %s", (payment["reference"],)
            )
    except Exception:
        log.exception("Failed to send Telegram notification for %s", payment["reference"])


@app.post("/webhooks/sasusync/payment")
async def sasusync_webhook(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    secret = os.environ["SASUSYNC_WEBHOOK_SECRET"]
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    signature = request.headers.get("X-Webhook-Signature", "")

    if not hmac.compare_digest(signature, expected):
        # 200 so SasuSync stops retrying a delivery that will never verify.
        return {"status": 0}

    payload = json.loads(raw)
    event = payload.get("event")
    data = payload.get("data", {})
    reference = data.get("reference")
    if not reference:
        return {"status": 0}

    if event == "payment.succeeded":
        with db.pool.connection() as conn:
            updated = conn.execute(
                """
                UPDATE dues.payments
                SET status = 'successful', paid_at = %s, payer_phone = %s, payer_name = %s, updated_at = now()
                WHERE reference = %s AND status != 'successful'
                RETURNING *
                """,
                (data.get("paid_at"), data.get("payer"), data.get("payer_name"), reference),
            ).fetchone()
        if updated:
            background_tasks.add_task(fulfil_payment, updated)
    elif event == "payment.failed":
        with db.pool.connection() as conn:
            conn.execute(
                "UPDATE dues.payments SET status = 'failed', updated_at = now() "
                "WHERE reference = %s AND status = 'pending'",
                (reference,),
            )

    return {"status": 1}


@app.get("/issue", response_class=HTMLResponse)
def issue_form(request: Request):
    return templates.TemplateResponse("issue.html", {"request": request})


@app.post("/issue", response_class=HTMLResponse)
def issue_submit(
    request: Request,
    full_name: str = Form(...),
    student_id: str = Form(...),
    phone_number: str = Form(...),
    email: str = Form(""),
    category: str = Form(...),
    reason: str = Form(...),
):
    full_name = full_name.strip()
    student_id = student_id.strip()
    phone_number = phone_number.strip()
    email = email.strip() or None
    reason = reason.strip()

    with db.pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO dues.issue_reports (full_name, student_id, phone_number, email, category, reason)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (full_name, student_id, phone_number, email, category, reason),
        )

    try:
        telegram_client.send_telegram(
            "⚠️ <b>Dues issue report</b>\n"
            f"Name: {full_name}\n"
            f"Student ID: {student_id}\n"
            f"Phone: {phone_number}\n"
            f"Email: {email or '-'}\n"
            f"Category: {category}\n"
            f"Reason: {reason}"
        )
    except Exception:
        log.exception("Failed to send Telegram notification for issue report from %s", student_id)

    return templates.TemplateResponse("issue_thanks.html", {"request": request})
