# JobPilot SA — MVP v4 (adds true daily automation via GitHub Actions)

## What's new in v4 — real automation, no app to open
The daily search is now genuinely hands-off. `automation/scheduled_search.py`
runs automatically every day via GitHub Actions
(`.github/workflows/daily-search.yml`) — it searches Adzuna for your target
roles, scores results with the exact same `matching.py` logic the app uses,
skips anything already seen, and **emails you a digest of new matches**.
Nothing to click, nothing to open.

**One-time setup:**
1. Edit `automation/candidate_profile.json` in your GitHub repo with your
   real profile (name, roles, skills, qualifications, experience, location)
   — this is what the automation matches against, so keep it accurate.
2. In your repo, go to **Settings → Secrets and variables → Actions** and
   add these repository secrets:
   - `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` — your Adzuna credentials
   - `SMTP_HOST`, `SMTP_PORT` (587 for most providers), `SMTP_USER`,
     `SMTP_PASS` — an email account to send from. For Gmail: use an
     [App Password](https://myaccount.google.com/apppasswords), not your
     normal password.
   - `NOTIFY_EMAIL` — the address that should receive the daily digest
3. That's it — it runs automatically at 07:00 SAST every day. You can also
   trigger it manually any time from the repo's **Actions** tab → "Daily
   job search" → **Run workflow**, to test it immediately rather than
   waiting for the schedule.

This still only *finds and scores* jobs — it doesn't submit anything.
Submission still goes through the app's `CLIENT_REVIEW`/prepared flow,
exactly as before; this just removes the need to manually search.

## Run it
```
pip install -r requirements.txt
streamlit run app.py
```

## What this is
A testable prototype of the matching, fact-guard, and client-review-handoff
logic for an AI job-application assistant. It replaces two earlier builds
(one from Manus, one from ChatGPT) that both had a real flaw: the Manus
build scored a 15-year insurance broker at 92% against a SQL/analytics
role and drafted a confidently-overselling cover letter for it; the
ChatGPT build gave every job a 40% match floor regardless of actual
overlap. Both are fixed here — see `matching.py` and `factguard.py`.

## What's new in v3
Vacancy intake is no longer manual-only. The Vacancies tab now has a
**"Search job boards"** section that calls Adzuna's South Africa job
search API (`discovery.py`) — a licensed, ToS-compliant data source, not
scraping — and automatically runs every result through the same matching
and duplicate-prevention logic as before. Manual paste-in is still there
underneath, for a specific posting Adzuna doesn't carry (e.g. a direct
Greenhouse/Lever listing).

You'll need a free Adzuna API key: register at
https://developer.adzuna.com/, then enter the `app_id`/`app_key` in the
app's Vacancies tab.

## Files
- `app.py` — the Streamlit UI (candidate profile, vacancy intake, application
  engine, client reports, and the client-review link destination).
- `discovery.py` — automated job search via the Adzuna API. Query results
  feed straight into `matching.py`, exactly like a manually pasted vacancy.
- `matching.py` — scores a candidate against a job's actual requirement
  lines (not a flat keyword floor), weighting required lines far above
  preferred ones, and returns *which* lines matched/were missing.
- `factguard.py` — generates application summaries/cover letters using
  only the candidate's verified fields (skills, qualifications,
  experience, CV text) — it cannot invent a claim because it never
  free-generates text. Also includes `audit_generated_text()` to check
  any future LLM-drafted copy against the candidate's real data before a
  client sees it.
- `review.py` — duplicate-application prevention (jobs are fingerprinted
  by title+company+location) and the CAPTCHA/low-confidence handoff:
  anything the system can't safely finish gets a unique client-only
  review link, never routed to a human operator on the business side.
- `storage.py` — flat JSON file store. Fine for this single-user test
  harness; **must** be replaced with a real database before real users
  touch this (see "Not yet built" below).

## Safeguards implemented
- **No duplicate applications**: vacancy fingerprinting blocks re-adding
  the same posting; a job that already has an application record is
  skipped in the application engine.
- **No fabricated qualifications/answers**: `factguard.py` only builds
  text from verified fields; any screening question the system can't
  answer from verified data is marked `ACTION_REQUIRED`, never guessed.
- **No CAPTCHA bypassing**: sources likely to require a CAPTCHA or manual
  portal steps are flagged `CLIENT_REVIEW` and handed to the client via a
  unique link — the system never attempts to solve or route around one.
- **Nothing marked "verified" without evidence**: an application only
  becomes `SUBMITTED_VERIFIED` after the client enters a confirmation
  reference on the review page.
- **Transparent scoring**: every match shows the actual matched/missing
  requirement lines, not just an opaque percentage.

## Tiers (as discussed, gated by monthly application-record limits)
| | Free | Pro (R149/mo) | Concierge (R349/mo) |
|---|---|---|---|
| Matching + full job-spec reports | ✅ | ✅ | ✅ |
| Fact-guarded drafting | ✅ | ✅ | ✅ |
| Monthly application records | 5 | 50 | Unlimited |
| Client-review link handoff | ✅ | ✅ | ✅ (same flow — no staff involvement at any tier) |

Pricing/limits are just constants in `app.py` (`PLANS` dict) — trivial to
adjust.

## Not yet built (this is the actual scope for Manus, ChatGPT, or a developer to pick up)
1. **Hosting + real database + auth** — swap `storage.py`'s flat JSON file
   for Postgres/SQLite with per-client rows, deploy behind login. This is
   the biggest gap between "prototype" and "real product."
2. ~~Job-board discovery~~ — **done in v3** via Adzuna. Worth extending
   later with Greenhouse/Lever's public per-company APIs (see
   ARCHITECTURE.md section 2) for specific target employers, and with a
   second aggregator (e.g. Jooble) for broader coverage.
3. **Real submission automation** — this only classifies whether a source
   *could* have an authorised route; it doesn't fill or submit forms on a
   live site. Any real automation here must respect each platform's ToS —
   this is where most "auto-apply" tools get themselves banned.
4. **Payment processing** — plan selection is a dropdown; needs a real
   checkout (Stripe/Paystack/PayFast for SA) with webhook-driven plan
   status.
5. **Review-link delivery** — the client-review link is currently just
   displayed on screen. Wire up email or WhatsApp (e.g. Twilio) so it's
   actually sent to the client automatically.
6. **audit_generated_text() integration** — if/when a real LLM is added
   for richer copywriting, its output must be passed through this
   function before a client ever sees it, exactly like the templated
   functions already are.

No CAPTCHA, authentication, anti-bot control, or platform restriction is
bypassed anywhere in this codebase.
