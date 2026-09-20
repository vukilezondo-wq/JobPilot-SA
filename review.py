"""
Duplicate prevention + client-review handoff.

Two safeguards live here:

1. Duplicate prevention — a candidate should never end up with two
   application records against the same job. Vacancies are fingerprinted
   by title + company + location, so re-adding the same posting doesn't
   create a second entry, and a job that already has an application
   attached is skipped in the application engine.

2. CAPTCHA / low-confidence handoff — anything the system cannot safely
   finish itself (a CAPTCHA, an unanswerable screening question, a
   fact-guard flag on drafted text) is never resolved automatically and
   is never routed to a human operator on your side. It's marked
   CLIENT_REVIEW and given a unique link the client opens themselves to
   finish the last step and confirm submission. You are not in that loop.
"""
import hashlib
import secrets


def job_fingerprint(title: str, company: str, location: str) -> str:
    key = f"{title.strip().lower()}|{company.strip().lower()}|{location.strip().lower()}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def is_duplicate_job(jobs: list, title: str, company: str, location: str) -> bool:
    fp = job_fingerprint(title, company, location)
    return any(j.get('fingerprint') == fp for j in jobs)


def has_existing_application(applications: list, job_id: str) -> bool:
    return any(a['job_id'] == job_id for a in applications)


def new_review_token() -> str:
    return secrets.token_urlsafe(16)


def review_link(base_url: str, token: str) -> str:
    return f"{base_url}?review={token}"


def record_id(job_id: str, timestamp: str) -> str:
    return hashlib.sha1(f"{job_id}{timestamp}".encode()).hexdigest()[:12]
