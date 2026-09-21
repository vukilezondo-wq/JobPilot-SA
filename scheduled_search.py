"""
Scheduled search — runs daily via GitHub Actions (see
.github/workflows/daily-search.yml), with no app to open and nothing for
the client to click. This is the actual "hands-off" version: it searches
Adzuna for every target role in candidate_profile.json, scores results
with the same matching.py logic the app uses, skips anything already
seen (seen_jobs.json, committed back to the repo each run), and emails a
digest of new PASS/REVIEW matches.

Nothing here submits an application — it only finds and scores vacancies,
exactly like the on-demand search in the app, just running on its own
schedule instead of waiting for someone to click a button.
"""
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import the app's own modules
from discovery import search_adzuna
from matching import match
from review import job_fingerprint

HERE = Path(__file__).resolve().parent
PROFILE_PATH = HERE / 'candidate_profile.json'
SEEN_PATH = HERE / 'seen_jobs.json'
MIN_SCORE_TO_NOTIFY = 45  # REVIEW or better — don't spam with HOLD-tier noise


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def send_email(subject: str, body: str) -> None:
    host = os.environ['SMTP_HOST']
    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ['SMTP_USER']
    password = os.environ['SMTP_PASS']
    to_addr = os.environ['NOTIFY_EMAIL']

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = to_addr

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())


def main():
    candidate = load_json(PROFILE_PATH, {})
    if not candidate or not candidate.get('roles'):
        print('candidate_profile.json is empty or has no target roles — nothing to search. '
              'Fill it in with your real profile first.')
        return

    seen = set(load_json(SEEN_PATH, []))
    app_id = os.environ['ADZUNA_APP_ID']
    app_key = os.environ['ADZUNA_APP_KEY']
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
        return

    new_matches.sort(key=lambda j: j['score'], reverse=True)
    lines = [f"{len(new_matches)} new job match(es) found today:\n"]
    for j in new_matches:
        lines.append(
            f"{j['score']}% [{j['decision']}] — {j['title']} at {j['company']} ({j['location']})\n"
            f"  {j['url']}\n"
        )
    body = '\n'.join(lines)
    print(body)

    try:
        send_email(f"JobPilot SA — {len(new_matches)} new match(es)", body)
        print('Email sent.')
    except KeyError as e:
        print(f'Email not sent — missing environment variable/secret: {e}')
    except Exception as e:
        print(f'Email send failed: {e}')


if __name__ == '__main__':
    main()
