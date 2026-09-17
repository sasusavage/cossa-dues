import os

import httpx

BASE_URL = "https://sms.sasusync.com"


def send_sms(phone: str, message: str) -> dict:
    sender = os.environ.get("SASUSYNC_SENDER_ID", "COSSA")
    r = httpx.post(
        f"{BASE_URL}/api/v1/send",
        headers={"X-API-Key": os.environ["SASUSYNC_API_KEY"]},
        json={"sender": sender, "recipients": [phone], "message": message},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
