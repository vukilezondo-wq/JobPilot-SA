# JobPilot SA — MVP v2 (safeguard-hardened matching + review engine)

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

## Files
- `app.py` — the Streamlit UI (candidate profile, vacancy intake, application
  engine, client reports, and the client-review link destination).
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
2. **Job-board discovery** — vacancies are entered manually here as a test
   harness for the matching logic. Real discovery means job-board APIs
   (Greenhouse/Lever job board APIs are the most automation-friendly;
   LinkedIn/Indeed are far more restrictive and detection-prone) or a
   licensed data feed.
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
