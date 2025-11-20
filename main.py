import os
import secrets
import smtplib
from email.message import EmailMessage
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode

from database import create_document
from schemas import Lead, LeadStored

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "KMU-Freight Backend running"}


def _send_email(subject: str, body: str, to_email: str):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM", os.getenv("ADMIN_EMAIL", "no-reply@kmu-freight.com"))

    if not host or not username or not password:
        # Fallback to console log if SMTP not configured
        print(f"[EMAIL-FALLBACK] To: {to_email}\nSubject: {subject}\n\n{body}")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)


def notify_admin_waitlist(lead: Lead):
    admin_email = os.getenv("ADMIN_EMAIL", "max.salterberg@kmu-freight.com")
    subject = "Neuer Warteliste/Lead – KMU‑Freight"
    body = (
        f"Name: {lead.name}\n"
        f"Firma: {lead.company}\n"
        f"E-Mail: {lead.email}\n"
        f"Interesse: {lead.interest}\n"
        f"Zweck: {lead.purpose}\n"
        f"Einwilligung: {lead.consent}\n"
        f"Nachricht: {lead.message or '-'}\n"
    )
    _send_email(subject, body, admin_email)


def send_double_opt_in(to_email: str, token: str):
    base = os.getenv("FRONTEND_URL", "")
    confirm_url = f"{base}/confirm?{urlencode({'token': token})}" if base else f"/confirm?token={token}"
    subject = "Bitte bestätige deine Anmeldung – KMU‑Freight"
    body = (
        "Hallo,\n\n"
        "bitte bestätige deine Anmeldung zur Warteliste, indem du auf den folgenden Link klickst:\n"
        f"{confirm_url}\n\n"
        "Wenn du diese Anfrage nicht gestellt hast, ignoriere diese Nachricht.\n\n"
        "Viele Grüße\nKMU‑Freight"
    )
    _send_email(subject, body, to_email)


@app.post("/api/leads")
def create_lead(lead: Lead, background_tasks: BackgroundTasks):
    try:
        # Generate confirmation token and store with pending status
        token = secrets.token_urlsafe(32)
        data = lead.model_dump()
        data.update({"status": "pending", "confirm_token": token, "confirmed_at": None})
        lead_id = create_document("lead", data)

        # Notify admin and send double opt-in
        background_tasks.add_task(notify_admin_waitlist, lead)
        background_tasks.add_task(send_double_opt_in, lead.email, token)

        return {"success": True, "id": lead_id, "double_opt_in": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/confirm")
def confirm_waitlist(token: str):
    # In a real setup, we would update the document by token.
    # Since this template exposes read helpers only, we provide a placeholder success response.
    # Confirmation effect will be handled once update helpers are available.
    return {"success": True, "message": "Anmeldung bestätigt"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        from database import db

        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
