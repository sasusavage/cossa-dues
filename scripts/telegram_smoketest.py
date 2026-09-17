"""One-off check that TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID actually reach the
right chat, run before going live: `python scripts/telegram_smoketest.py`.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.telegram_client import send_telegram  # noqa: E402

if __name__ == "__main__":
    try:
        result = send_telegram("COSSA Dues Portal: Telegram smoke test OK.")
        print("Sent:", result)
    except Exception as e:
        print("Failed:", e)
        print(
            "If this says 'chat not found', TELEGRAM_CHAT_ID probably needs a "
            "-100 prefix for a supergroup — see .env.example."
        )
