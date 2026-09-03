import logging
import os
import uuid
from .base import BaseSMSProvider, SMSResult

logger = logging.getLogger(__name__)

class LogSMSProvider(BaseSMSProvider):
    """Dev/test provider: logs to console/file, always succeeds. Used when SMS_PROVIDER=log or no creds."""
    name = "log"

    def send(self, to: str, body: str) -> SMSResult:
        logger.info(f"[SMS:log] to={to} body={body[:120]}")
        return SMSResult(success=True, provider_sid=f"log-{uuid.uuid4().hex[:12]}", segments=1, cost_estimate=0)

class TwilioSMSProvider(BaseSMSProvider):
    name = "twilio"

    def __init__(self, account_sid=None, auth_token=None, from_number=None):
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = from_number or os.getenv("TWILIO_FROM_NUMBER")

    def send(self, to: str, body: str) -> SMSResult:
        if not (self.account_sid and self.auth_token and self.from_number):
            return SMSResult(success=False, error="Twilio not configured")
        try:
            from twilio.rest import Client
            client = Client(self.account_sid, self.auth_token)
            msg = client.messages.create(body=body, from_=self.from_number, to=to)
            return SMSResult(success=True, provider_sid=msg.sid, segments=1)
        except Exception as e:
            return SMSResult(success=False, error=str(e)[:500])

class BeemSMSProvider(BaseSMSProvider):
    """Tanzania aggregator Beem Africa (https://apisms.beem.africa). Uses API key / secret."""
    name = "beem"

    def __init__(self, api_key=None, secret_key=None, sender_id=None):
        self.api_key = api_key or os.getenv("BEEM_API_KEY")
        self.secret_key = secret_key or os.getenv("BEEM_SECRET_KEY")
        self.sender_id = sender_id or os.getenv("BEEM_SENDER_ID", "SMMS")

    def send(self, to: str, body: str) -> SMSResult:
        if not (self.api_key and self.secret_key):
            return SMSResult(success=False, error="Beem not configured")
        try:
            import base64, requests
            creds = base64.b64encode(f"{self.api_key}:{self.secret_key}".encode()).decode()
            resp = requests.post(
                "https://apisms.beem.africa/v1/send",
                headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
                json={"source_addr": self.sender_id, "encoding": 0, "schedule_time": "", "message": body, "recipients": [{"recipient_id": 1, "dest_addr": to}]},
                timeout=10,
            )
            data = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {}
            if resp.status_code in (200, 201):
                sid = str(data.get("request_id") or data.get("sms_id") or uuid.uuid4().hex[:12])
                return SMSResult(success=True, provider_sid=sid, segments=1)
            return SMSResult(success=False, error=f"Beem {resp.status_code}: {resp.text[:300]}")
        except Exception as e:
            return SMSResult(success=False, error=str(e)[:500])
