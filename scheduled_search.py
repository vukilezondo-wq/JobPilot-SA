import json
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from email.utils import formataddr
from pathlib import Path

from discovery import search_adzuna
from matching import match
from review import job_fingerprint

HERE = Path(__file__).resolve().parent
PROFILE_PATH = HERE / 'candidate_profile.json'
SEEN_PATH = HERE / 'seen_jobs.json'
MIN_SCORE_TO_NOTIFY = 45


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def send_email(subject, body):
    host = os.environ['SMTP_HOST']
    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ['SMTP_USER']
    password = os.environ['SMTP_PASS']
    to_addr = os.environ['NOTIFY_EMAIL']
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = formataddr(('JobPilot SA', user))
    msg['To'] = to_addr
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())


def main():
    candidate = load_json(PROFILE_PATH, {})
    if not candidate or not candidate.get('roles'):
        print('candidate_profile.json is empty or has no target roles.')
        return

    seen = set(load_json(SEEN_PATH, []))
    app_id = os.environ['ADZUNA_APP_ID'].strip()
    app_key = os.environ['ADZUNA_APP_KEY'].strip()
    location = candidate.get('location', 'South Africa')

    new_matches = []
    for role in candidate['roles']:
        try:
            results = search_adzuna(app_id, app_key, role, location, results_per_page=15)
        except Exception as e:
            print(f'Search failed for "{role}": {e}')
            continue
        for r in results:
            fp = job_fingerprint(r['title'], r['company'], r['location'])
            if fp in seen:
                continue
            seen.add(fp)
            result = match(candidate, r['spec'], r['title'])
            if result['score'] >= MIN_SCORE_TO_NOTIFY:
                new_matches.append({**r, **result, 'fingerprint': fp})

    SEEN_PATH.write_text(json.dumps(sorted(seen), indent=2))

    if not new_matches:
        print('No new matches above the notify threshold today.')
        try:
            send_email('JobPilot SA — ran today, no new matches',
                        'The daily search ran successfully today but found no new matches '
                        'above the notify threshold. This is a normal confirmation email, '
                        'not an error — it just means nothing new came up today.')
            print('Confirmation email sent.')
        except Exception as e:
            print(f'Confirmation email failed: {e}')
        return
        try:
            send_email('JobPilot SA — ran today, no new matches',
                        'The daily search ran successfully today but found no new matches '
                        'above the notify threshold. This is a normal confirmation email, '
                        'not an error — it just means nothing new came up today.')
            print('Confirmation email sent.')
        except Exception as e:
            print(f'Confirmation email failed: {e}')
        return

    new_matches.sort(key=lambda j: j['score'], reverse=True)
    lines = [f"{len(new_matches)} new job match(es) found today:\n"]
    for j in new_matches:
        lines.append(f"{j['score']}% [{j['decision']}] — {j['title']} at {j['company']} ({j['location']})\n  {j['url']}\n")
    body = '\n'.join(lines)
    print(body)

    try:
        send_email(f"JobPilot SA — {len(new_matches)} new match(es)", body)
        print('Email sent.')
    except KeyError as e:
        print(f'Email not sent — missing secret: {e}')
    except Exception as e:
        print(f'Email send failed: {e}')


if __name__ == '__main__':
    main()
