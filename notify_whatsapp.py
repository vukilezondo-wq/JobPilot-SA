"""
WhatsApp notifications via Twilio's WhatsApp Business API.

To use this:
1. Sign up at https://www.twilio.com (free trial credit available)
2. Enable the WhatsApp Sandbox (for testing) under Messaging → Try it out
   → Send a WhatsApp message — this gives you a sandbox WhatsApp number
   and a join code the recipient must send once to opt in
3. For production (messaging clients who haven't joined your sandbox),
   apply for a WhatsApp Business Sender — this requires business
   verification with Meta and takes longer; the sandbox is fine for
   testing with yourself or a pilot client in the meantime
4. Get your Account SID and Auth Token from the Twilio console
5. Set these as secrets: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
   TWILIO_WHATSAPP_FROM (e.g. 'whatsapp:+14155238886' for the sandbox)

This is a genuinely separate channel from email — if WhatsApp sending
fails for any reason (recipient hasn't joined the sandbox, no Twilio
credit, wrong number format), it must never block or fail the email
send, which is why every caller wraps this in its own try/except.
"""
import os
import requests

TWILIO_API_BASE = 'https://api.twilio.com/2010-04-01'


def build_whatsapp_request(account_sid: str, from_number: str, to_number: str, body: str) -> dict:
    """Separated from the actual network call so this can be unit-tested
    without hitting Twilio — mirrors the pattern used in discovery.py."""
    to_number = to_number.strip()
    if not to_number.startswith('+'):
        raise ValueError(
            f"Phone number '{to_number}' must be in international format starting with '+' "
            f"(e.g. +27821234567) for WhatsApp delivery."
        )
    return {
        'url': f'{TWILIO_API_BASE}/Accounts/{account_sid}/Messages.json',
        'data': {
            'From': from_number if from_number.startswith('whatsapp:') else f'whatsapp:{from_number}',
            'To': f'whatsapp:{to_number}',
            'Body': body,
        },
    }


def send_whatsapp(to_number: str, body: str) -> None:
    account_sid = os.environ['TWILIO_ACCOUNT_SID'].strip()
    auth_token = os.environ['TWILIO_AUTH_TOKEN'].strip()
    from_number = os.environ['TWILIO_WHATSAPP_FROM'].strip()

    req = build_whatsapp_request(account_sid, from_number, to_number, body)
    resp = requests.post(req['url'], data=req['data'], auth=(account_sid, auth_token), timeout=15)
    resp.raise_for_status()
