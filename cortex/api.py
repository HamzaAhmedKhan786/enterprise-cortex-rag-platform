"""Narrow backend for Stripe webhooks; browser accounts remain in Streamlit."""
from fastapi import FastAPI, HTTPException, Request
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from cortex import billing, store

app = FastAPI(title="Cortex service endpoints", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 256 * 1024:
            raise HTTPException(413, "Body too large")
    store.initialize()
    try:
        return billing.webhook(bytes(raw), request.headers.get("stripe-signature", ""))
    except ValueError:
        raise HTTPException(400, "Invalid webhook signature, mode or payload") from None
    except Exception:
        # Failure is retryable; never acknowledge a failed reconciliation.
        raise HTTPException(503, "Webhook reconciliation unavailable") from None
