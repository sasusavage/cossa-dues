# COSSA Dues Portal

Collects departmental dues for the Computing Science Students' Association
(Valley View University). Students enter their full name and student ID; the
app checks them against the university's existing student records to decide
whether they pay GHS 50 (continuing student) or GHS 100 (no matching record),
takes payment through SasuSync, and sends an SMS + Telegram confirmation once
paid.

## How matching works

Read-only lookups against the shared `users` table (owned by the existing
voting system — never written to by this app):

- Student ID matches **and** the submitted name contains the name on file →
  **continuing, GHS 50**.
- No ID match, but exactly one student's name on file is fully contained in
  the submitted name → **continuing, GHS 50** (covers a diploma student who
  topped up and got a new student ID).
- More than one name-only candidate → routed to the manual issue form instead
  of guessing.
- No match at all → **fresher, GHS 100**.

The determined category/amount is stored server-side (`dues.pending_checks`)
the moment a student is checked, so it can't be edited by tampering with the
confirmation form before paying.

Everything this app owns lives in its own `dues` Postgres schema
(`migrations/001_dues_schema.sql`, applied automatically on startup).

## Fallback: the issue form

`/issue` — for anyone the automatic check gets wrong (ambiguous name match,
disputes their category, etc). Full name, student ID, phone, optional email,
category and a reason, sent straight to the COSSA Telegram chat for manual
handling.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values
uvicorn app.main:app --reload
```

`scripts/telegram_smoketest.py` sends one test message so you can confirm
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` reach the right chat before relying on
it in production.

## Deploying on Coolify

1. Point a new Coolify application at this repo. The `Dockerfile` at the repo
   root is picked up automatically — no other build configuration needed.
2. Set these as the application's environment variables (see `.env.example`
   for the full list): `DATABASE_URL`, `SASUSYNC_API_KEY`,
   `SASUSYNC_WEBHOOK_SECRET`, `SASUSYNC_SENDER_ID`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `DUES_AMOUNT_CONTINUING`, `DUES_AMOUNT_FRESHER`, and
   `APP_BASE_URL` (the exact public HTTPS origin Coolify gives the app, no
   trailing slash — payment redirect URLs are built from this).
3. In the SasuSync admin, under **Payments → Systems**, set that system's
   webhook URL to exactly `https://<your-domain>/webhooks/sasusync/payment`
   — HTTPS, no trailing slash, must literally match this path or SasuSync's
   405-on-unmatched-path behavior will silently swallow every payment result.
4. Register/approve the `COSSA` sender ID for SMS if it isn't already
   (`POST /sender/id/register`) — an unapproved sender returns 403 on every
   send.
5. Health check path for Coolify: `/healthz`.

## Notes

- The app never trusts `redirect_url` to mean "paid" — only the signed
  `payment.succeeded` webhook, or a live `GET /api/v1/payments/{reference}`
  check, does that.
- Webhook fulfilment is idempotent on `reference`, so SasuSync's up-to-12-hour
  retry of undelivered results is harmless.
- `matched_user_id` deliberately has no foreign key onto the shared `users`
  table, so nothing here can ever block a delete in the voting system that
  owns it.
