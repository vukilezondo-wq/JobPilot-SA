"""
Multi-client scheduled search — the real version of automation/scheduled_search.py.

The single-client version (automation/scheduled_search.py) reads one
candidate_profile.json. This version loops through every client stored
in the shared database (db.py) and emails each of them their own digest
— one scheduled run serving every client, instead of one repo per client.

Requires the SQLite database file (jobpilot.db) to persist between runs,
which means this needs to run somewhere with a persistent disk — a
GitHub Actions run on a fresh checkout won't have yesterday's database
unless it's committed back to the repo (fine for a small pilot, same
approach as v5's seen_jobs.json) or, for real scale, a small always-on
server / hosted database as ARCHITECTURE.md describes. This script
itself doesn't care which — it just needs db.DB_PATH to point at a file
that persists.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

import db
from discovery import search_adzuna
from matching import match
from review import job_fingerprint
from notify_whatsapp import send_whatsapp

MIN_SCORE_TO_NOTIFY = 45


def send_email(to_addr: str, subject: str, body: str) -> None:
    host = os.environ['SMTP_HOST'].strip()
    port = int(os.environ.get('SMTP_PORT', '587').strip())
    user = os.environ['SMTP_USER'].strip()
    password = os.environ['SMTP_PASS'].strip()

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = formataddr(('JobPilot SA', user))
    msg['To'] = to_addr

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())


def run_for_client(client: dict, app_id: str, app_key: str) -> None:
    client_id = client['client_id']
    new_matches = []

    for role in client['roles']:
        try:
            results = search_adzuna(app_id, app_key, role, client.get('location', 'South Africa'),
                                     results_per_page=15)
        except Exception as e:
            print(f"[{client['email']}] search failed for '{role}': {e}")
            continue

        for r in results:
            fp = job_fingerprint(r['title'], r['company'], r['location'])
            if db.is_duplicate_job(client_id, fp):
                continue
            result = match(client, r['spec'], r['title'])
            job_id = db.add_job(client_id, {'fingerprint': fp, **r, **result})
            if job_id and result['score'] >= MIN_SCORE_TO_NOTIFY:
                new_matches.append({**r, **result})

    if new_matches:
        new_matches.sort(key=lambda j: j['score'], reverse=True)
        lines = [f"{len(new_matches)} new job match(es) found today:\n"]
        for j in new_matches:
            lines.append(f"{j['score']}% [{j['decision']}] — {j['title']} at {j['company']} ({j['location']})\n  {j['url']}\n")
        subject = f"JobPilot SA — {len(new_matches)} new match(es)"
        body = '\n'.join(lines)
    else:
        subject = 'JobPilot SA — ran today, no new matches'
        body = ('The daily search ran successfully today but found no new matches above the '
                'notify threshold. This is a normal confirmation email, not an error.')

    try:
        send_email(client['email'], subject, body)
        print(f"[{client['email']}] {'sent ' + str(len(new_matches)) + ' match(es)' if new_matches else 'sent confirmation (no new matches)'}")
    except Exception as e:
        print(f"[{client['email']}] email failed: {e}")

    # WhatsApp is a genuinely separate, opt-in channel — its failure or
    # absence must never affect the email above, which is why this is in
    # its own try/except and only runs if the client opted in and Twilio
    # secrets are actually configured.
    if client.get('whatsapp_opt_in') and client.get('phone'):
        required_secrets = ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_FROM')
        if all(s in os.environ for s in required_secrets):
            try:
                whatsapp_body = body if len(body) <= 1500 else body[:1500] + '\n...(see email for full list)'
                send_whatsapp(client['phone'], whatsapp_body)
                print(f"[{client['email']}] WhatsApp sent")
            except Exception as e:
                print(f"[{client['email']}] WhatsApp failed: {e}")
        else:
            print(f"[{client['email']}] WhatsApp opted in but Twilio secrets not configured — skipped.")


def main():
    db.init_db()
    app_id = os.environ['ADZUNA_APP_ID'].strip()
    app_key = os.environ['ADZUNA_APP_KEY'].strip()

    clients = db.list_clients_with_roles()
    if not clients:
        print('No clients with target roles set — nothing to search.')
        return

    print(f'Running search for {len(clients)} client(s).')
    for client in clients:
        run_for_client(client, app_id, app_key)


if __name__ == '__main__':
    main()
