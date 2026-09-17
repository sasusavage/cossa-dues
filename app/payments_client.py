import os

import httpx

BASE_URL = "https://sms.sasusync.com"


def _headers() -> dict:
    return {"X-API-Key": os.environ["SASUSYNC_API_KEY"]}


def create_payment(reference: str, amount: float, email: str | None, redirect_url: str, metadata: dict) -> dict:
    r = httpx.post(
        f"{BASE_URL}/api/v1/payments",
        headers=_headers(),
        json={
            "reference": reference,
            "amount": f"{amount:.2f}",
            "currency": "GHS",
            "email": email,
            "redirect_url": redirect_url,
            "metadata": metadata,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_payment(reference: str) -> dict:
    r = httpx.get(f"{BASE_URL}/api/v1/payments/{reference}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def refresh_payment(reference: str) -> dict:
    r = httpx.post(f"{BASE_URL}/api/v1/payments/{reference}/refresh", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()
