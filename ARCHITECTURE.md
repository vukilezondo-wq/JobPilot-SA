# JobPilot SA — Architecture for the Remaining Build (v2 → production)

This picks up exactly where `README.md`'s "Not yet built" list left off, with
real design decisions for each gap — not just a list of missing pieces.

---

## 1. Database schema (replaces `storage.py`'s flat JSON file)

Postgres, one schema, multi-tenant by `client_id`. Dedup is enforced at the
database level too, not just in application code, as defense in depth.

```sql
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    plan TEXT NOT NULL DEFAULT 'Free',       -- Free / Pro / Concierge
    plan_status TEXT NOT NULL DEFAULT 'active', -- active / past_due / cancelled
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT, email TEXT, phone TEXT, location TEXT,
    roles TEXT[] DEFAULT '{}',
    skills TEXT[] DEFAULT '{}',
    qualifications TEXT[] DEFAULT '{}',
    experience_text TEXT DEFAULT '',
    salary_min TEXT,
    cv_text TEXT DEFAULT '',
    cv_file_url TEXT,
    consent_automatic_applications BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,   -- from review.job_fingerprint()
    title TEXT, company TEXT, location TEXT, source TEXT, url TEXT,
    spec_text TEXT NOT NULL,
    match_score INT, decision TEXT,
    matched_required JSONB, missing_required JSONB, matched_preferred JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, fingerprint)   -- duplicate prevention enforced by the DB
);

CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,   -- PREPARED / CLIENT_REVIEW / SUBMITTED_VERIFIED
    route TEXT,
    summary_text TEXT, cover_letter_text TEXT,
    fact_flags JSONB DEFAULT '[]',
    questions JSONB DEFAULT '[]',
    flag_reason TEXT,
    review_token TEXT UNIQUE,
    verification_evidence TEXT,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id)   -- one application per job, enforced by the DB
);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    client_id UUID REFERENCES clients(id),
    action TEXT NOT NULL,        -- e.g. 'review_link_sent', 'plan_changed'
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Application-layer checks (fingerprint lookup, existing-application lookup)
stay exactly as `review.py` already does them — the `UNIQUE` constraints above
are a second line of defense against a race condition or a bug, not a
replacement for that logic.

---

## 2. Job-board discovery — what's actually compliant

Ranked by how automation-friendly and ToS-safe they are:

1. **Greenhouse Job Board API** (public, no auth): `GET
   https://boards-api.greenhouse.io/v1/boards/{company-token}/jobs` returns
   structured JSON per company. Good for tracking specific target employers,
   not broad discovery across the whole market.
2. **Lever Postings API** (public, no auth): `GET
   https://api.lever.co/v0/postings/{company}?mode=json` — same pattern.
3. **Licensed job-data APIs for broad discovery**: Adzuna (has a South
   Africa endpoint, free-tier API key) and Jooble both offer structured,
   ToS-compliant job search APIs rather than scraping. Start here for
   "search the whole market" functionality.
4. **Avoid**: scraping LinkedIn, Indeed, or PNet directly. Their ToS
   prohibits it, and it's the single most common reason these tools get
   IP-banned or shut down. If PNet is important for the SA market
   specifically, check whether they offer any official partner/employer
   API before building anything against their site.

Practical starting point: wire up Greenhouse + Lever for specific employers
your clients care about, and Adzuna/Jooble for general market search. That
covers real discovery without touching anything scraping-based.

---

## 3. Real submission automation — the honest limits

This is the highest-risk item in the whole build, so be deliberate:

- **No general ATS has a public, unauthenticated "submit an application"
  API.** Greenhouse and Lever's public APIs above are read-only (job
  postings). Actually submitting still means either (a) an official
  partnership/API agreement with the ATS vendor, or (b) filling their public
  web form via browser automation — which walks straight back into
  CAPTCHA and ToS risk.
- **Recommended default**: treat every source as "prepare & handoff" unless
  you've secured an explicit partner API. That means `route` in
  `applications` stays `CLIENT_REVIEW` far more often than a marketing
  pitch would like — but it's the version that doesn't get your clients'
  applications silently discarded by a bot-detector, and doesn't get your
  own infrastructure blocked.
- If you later pursue an official partnership (some ATS vendors do offer
  paid "apply API" access to approved integrators), that becomes a new,
  narrowly-scoped `route: AUTOMATED` path — but it should require an
  explicit audit before launch, since it's the one part of this system that
  acts on a client's behalf on an external, adversarial-to-bots platform.

---

## 4. Payment processing

South Africa–friendly processors: PayFast, Paystack, or Stripe (now
available in SA). Flow:

1. Client selects a plan on a hosted checkout page (not a dropdown).
2. Processor redirects/webhooks back on success.
3. Your backend verifies the webhook signature (every processor's docs cover
   this — never trust an unverified webhook call).
4. Backend updates `clients.plan` and `plan_status`, logs the event id in
   `audit_log` for idempotency (so a retried webhook doesn't double-process).
5. Every plan-gated action in the app (application-record limits, tier
   features) checks `plan_status` server-side — never trust a client-side
   plan selector, which is only a placeholder in the current MVP.
6. Handle `subscription.cancelled` / `payment.failed` webhook events by
   downgrading `plan_status`, not just successful payments.

---

## 5. Review-link delivery

Currently the link is just displayed in the Streamlit UI. For production:

1. On any application entering `CLIENT_REVIEW`, enqueue a notification job
   rather than sending inline (so a slow email provider doesn't block the
   UI).
2. Primary channel: email (SendGrid, Resend, or similar) — reliable and
   free at low volume.
3. Optional/premium channel: WhatsApp via Twilio's WhatsApp Business API —
   fits the "WhatsApp alerts" feature from your original plan.
4. Give the review token an expiry (e.g. 14 days) and mark it consumed once
   the client submits verification evidence, so a link can't be reused or
   linger indefinitely.
5. Log delivery attempts/success in `audit_log` so you can see if a client
   never received or never opened a review link — useful for support.

---

## 6. If you later add a real LLM for richer drafting

The templated `safe_summary()`/`safe_cover_letter()` in `factguard.py` are
deliberately incapable of inventing anything. If you want more natural
prose later via an LLM, use this two-layer pattern rather than trusting the
model alone:

**Layer 1 — constrained generation.** Pass the LLM only the candidate's
verified profile fields and the job's matched/missing requirement lines
(never the full raw CV, to reduce surface area for it to pull unverified
detail from). System prompt should say, explicitly:

> "Only use facts present in the VERIFIED PROFILE block below. Do not add,
> infer, imply, or embellish any skill, qualification, employer, or years
> of experience not explicitly stated there. If a required skill is not in
> the verified profile, do not describe the candidate as having it, and do
> not use vaguely-transferable language to imply they do — state plainly
> that it isn't covered. Keep claims traceable to the input, not
> persuasive."

**Layer 2 — `audit_generated_text()` runs regardless**, as a second,
independent check, exactly as it does today. This is belt-and-suspenders on
purpose: a good prompt reduces fabrication, but the audit function is what
actually blocks it from reaching a client if the prompt fails. Any sentence
it flags gets shown to the client for edit/removal before the application
is marked ready — the same behavior the MVP already has when the templated
version happens to get flagged.
