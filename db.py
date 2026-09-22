"""
Multi-client database layer — replaces storage.py's single flat JSON file.

Implements the schema from ARCHITECTURE.md (simplified to SQLite for a
zero-config database that works both in the Streamlit app and in the
scheduled automation script, with no separate database server to run).
Every client is isolated by their own row; jobs and applications are
scoped to a client_id, with duplicate-prevention enforced at the database
level via UNIQUE constraints — not just in application code.

Client accounts require a password (see create_client/verify_login below)
— salted and hashed with PBKDF2-HMAC-SHA256, 200,000 iterations, a
standard-library-only approach (no extra dependency) that is a reasonable
baseline for this kind of app. This is real authentication, not the
email-only placeholder from earlier versions.

On passkeys specifically: true WebAuthn/passkey support needs
browser-level cryptographic ceremonies that Streamlit's Python-only
rendering model doesn't support well — building it by hand here would be
a large, security-sensitive undertaking without the right tooling. If
passkeys matter for this product, the realistic path is a real
authentication provider (e.g. Supabase Auth, Clerk, Auth0 — several have
free tiers and passkeys built in) rather than a hand-rolled
implementation. Password auth below is the practical baseline in the
meantime.
"""
import binascii
import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = 'jobpilot.db'
PBKDF2_ITERATIONS = 200_000


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------- passwords

def check_password_strength(password: str) -> str:
    """Returns an empty string if the password is acceptable, otherwise a
    message explaining what to fix."""
    if len(password) < 10:
        return 'Password must be at least 10 characters long.'
    if not re.search(r'[A-Za-z]', password):
        return 'Password must include at least one letter.'
    if not re.search(r'[0-9]', password):
        return 'Password must include at least one number.'
    return ''


def _hash_password(password: str, salt: bytes = None) -> tuple:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return binascii.hexlify(salt).decode(), binascii.hexlify(dk).decode()


def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    if not salt_hex or not hash_hex:
        return False
    salt = binascii.unhexlify(salt_hex)
    _, dk_hex = _hash_password(password, salt)
    return hmac.compare_digest(dk_hex, hash_hex)


@contextmanager
def get_conn(path: str = None):
    path = path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str = None) -> None:
    path = path or DB_PATH
    with get_conn(path) as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            location TEXT DEFAULT '',
            roles TEXT DEFAULT '[]',
            skills TEXT DEFAULT '[]',
            qualifications TEXT DEFAULT '[]',
            experience TEXT DEFAULT '',
            salary TEXT DEFAULT '',
            cv_text TEXT DEFAULT '',
            consent INTEGER DEFAULT 0,
            plan TEXT DEFAULT 'Free',
            whatsapp_opt_in INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            fingerprint TEXT NOT NULL,
            title TEXT, company TEXT, location TEXT, source TEXT, url TEXT,
            spec TEXT NOT NULL,
            match_score INTEGER, decision TEXT,
            matched_required TEXT DEFAULT '[]',
            missing_required TEXT DEFAULT '[]',
            matched_preferred TEXT DEFAULT '[]',
            note TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (client_id, fingerprint)
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            route TEXT,
            summary TEXT, cover_letter TEXT,
            fact_flags TEXT DEFAULT '[]',
            questions TEXT DEFAULT '[]',
            flag_reason TEXT,
            review_token TEXT UNIQUE,
            verification TEXT,
            submitted_at TEXT,
            created_at TEXT NOT NULL
        );
        ''')


# ---------------------------------------------------------------- clients

CANDIDATE_JSON_FIELDS = ('roles', 'skills', 'qualifications')
CANDIDATE_TEXT_FIELDS = ('name', 'phone', 'location', 'experience', 'salary', 'cv_text')


def _row_to_candidate(row: sqlite3.Row) -> dict:
    d = {k: row[k] for k in CANDIDATE_TEXT_FIELDS}
    d['email'] = row['email']
    for k in CANDIDATE_JSON_FIELDS:
        d[k] = json.loads(row[k])
    d['consent'] = bool(row['consent'])
    d['plan'] = row['plan']
    d['client_id'] = row['id']
    d['whatsapp_opt_in'] = bool(row['whatsapp_opt_in'])
    return d


def get_or_create_client(email: str, path: str = None) -> dict:
    """DEPRECATED for the app — kept only for automation scripts that
    already have a verified client and don't need to re-authenticate a
    human. The Streamlit app must use create_client()/verify_login()
    instead; this must never be reachable from an unauthenticated request."""
    path = path or DB_PATH
    email = email.strip().lower()
    with get_conn(path) as conn:
        row = conn.execute('SELECT * FROM clients WHERE email = ?', (email,)).fetchone()
        if row is None:
            raise ValueError(f'No account exists for {email} — use create_client() to sign up first.')
        return _row_to_candidate(row)


def create_client(email: str, password: str, path: str = None) -> dict:
    path = path or DB_PATH
    email = email.strip().lower()
    problem = check_password_strength(password)
    if problem:
        raise ValueError(problem)
    salt_hex, hash_hex = _hash_password(password)
    with get_conn(path) as conn:
        existing = conn.execute('SELECT 1 FROM clients WHERE email = ?', (email,)).fetchone()
        if existing:
            raise ValueError('An account with this email already exists — log in instead.')
        conn.execute(
            'INSERT INTO clients (email, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (email, salt_hex, hash_hex, now()),
        )
        row = conn.execute('SELECT * FROM clients WHERE email = ?', (email,)).fetchone()
        return _row_to_candidate(row)


def verify_login(email: str, password: str, path: str = None):
    """Returns the client dict on success, or None on a wrong email/password
    (deliberately not distinguishing which, so a failed attempt doesn't
    reveal whether an email is registered)."""
    path = path or DB_PATH
    email = email.strip().lower()
    with get_conn(path) as conn:
        row = conn.execute('SELECT * FROM clients WHERE email = ?', (email,)).fetchone()
    if row is None:
        return None
    if not _verify_password(password, row['password_salt'], row['password_hash']):
        return None
    return _row_to_candidate(row)


def change_password(client_id: int, new_password: str, path: str = None) -> None:
    path = path or DB_PATH
    problem = check_password_strength(new_password)
    if problem:
        raise ValueError(problem)
    salt_hex, hash_hex = _hash_password(new_password)
    with get_conn(path) as conn:
        conn.execute('UPDATE clients SET password_salt = ?, password_hash = ? WHERE id = ?',
                     (salt_hex, hash_hex, client_id))


def save_candidate(client_id: int, fields: dict, path: str = None) -> None:
    path = path or DB_PATH
    text_updates = {k: fields[k] for k in CANDIDATE_TEXT_FIELDS if k in fields}
    json_updates = {k: json.dumps(fields[k]) for k in CANDIDATE_JSON_FIELDS if k in fields}
    updates = {**text_updates, **json_updates}
    if 'consent' in fields:
        updates['consent'] = int(bool(fields['consent']))
    if 'plan' in fields:
        updates['plan'] = fields['plan']
    if 'whatsapp_opt_in' in fields:
        updates['whatsapp_opt_in'] = int(bool(fields['whatsapp_opt_in']))
    if not updates:
        return
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    with get_conn(path) as conn:
        conn.execute(f'UPDATE clients SET {set_clause} WHERE id = ?', (*updates.values(), client_id))


def list_clients_with_roles(path: str = None) -> list:
    path = path or DB_PATH
    """Every client with at least one target role set — used by the
    scheduled search to know who to search for."""
    with get_conn(path) as conn:
        rows = conn.execute('SELECT * FROM clients').fetchall()
    result = []
    for row in rows:
        c = _row_to_candidate(row)
        if c['roles']:
            result.append(c)
    return result


# ------------------------------------------------------------------- jobs

def is_duplicate_job(client_id: int, fingerprint: str, path: str = None) -> bool:
    path = path or DB_PATH
    with get_conn(path) as conn:
        row = conn.execute(
            'SELECT 1 FROM jobs WHERE client_id = ? AND fingerprint = ?', (client_id, fingerprint)
        ).fetchone()
    return row is not None


def add_job(client_id: int, job: dict, path: str = None):
    path = path or DB_PATH
    """Returns the new job's id, or None if it was a duplicate (the
    UNIQUE constraint is the real guarantee; the caller can also check
    is_duplicate_job first to give a friendlier message before trying)."""
    try:
        with get_conn(path) as conn:
            cur = conn.execute('''
                INSERT INTO jobs (client_id, fingerprint, title, company, location, source, url,
                                   spec, match_score, decision, matched_required, missing_required,
                                   matched_preferred, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                client_id, job['fingerprint'], job['title'], job['company'], job['location'],
                job['source'], job.get('url', ''), job['spec'], job['score'], job['decision'],
                json.dumps(job.get('matched_required', [])), json.dumps(job.get('missing_required', [])),
                json.dumps(job.get('matched_preferred', [])), job.get('note'), now(),
            ))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def _row_to_job(row: sqlite3.Row) -> dict:
    return {
        'id': row['id'], 'fingerprint': row['fingerprint'], 'title': row['title'],
        'company': row['company'], 'location': row['location'], 'source': row['source'],
        'url': row['url'], 'spec': row['spec'], 'score': row['match_score'], 'decision': row['decision'],
        'matched_required': json.loads(row['matched_required']),
        'missing_required': json.loads(row['missing_required']),
        'matched_preferred': json.loads(row['matched_preferred']),
        'note': row['note'], 'created_at': row['created_at'],
    }


def list_jobs(client_id: int, path: str = None) -> list:
    path = path or DB_PATH
    with get_conn(path) as conn:
        rows = conn.execute(
            'SELECT * FROM jobs WHERE client_id = ? ORDER BY created_at DESC', (client_id,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


# ---------------------------------------------------------------- applications

def has_existing_application(job_id: int, path: str = None) -> bool:
    path = path or DB_PATH
    with get_conn(path) as conn:
        row = conn.execute('SELECT 1 FROM applications WHERE job_id = ?', (job_id,)).fetchone()
    return row is not None


def add_application(client_id: int, job_id: int, record: dict, path: str = None):
    path = path or DB_PATH
    try:
        with get_conn(path) as conn:
            cur = conn.execute('''
                INSERT INTO applications (client_id, job_id, status, route, summary, cover_letter,
                                           fact_flags, questions, flag_reason, review_token,
                                           verification, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                client_id, job_id, record['status'], record.get('route'), record.get('summary', ''),
                record.get('cover_letter', ''), json.dumps(record.get('fact_flags', [])),
                json.dumps(record.get('questions', [])), record.get('flag_reason'),
                record.get('review_token'), record.get('verification', 'No submission evidence recorded.'),
                now(),
            ))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def _row_to_application(row: sqlite3.Row) -> dict:
    return {
        'id': row['id'], 'job_id': row['job_id'], 'status': row['status'], 'route': row['route'],
        'summary': row['summary'], 'cover_letter': row['cover_letter'],
        'fact_flags': json.loads(row['fact_flags']), 'questions': json.loads(row['questions']),
        'flag_reason': row['flag_reason'], 'review_token': row['review_token'],
        'verification': row['verification'], 'submitted_at': row['submitted_at'],
        'created_at': row['created_at'],
    }


def list_applications(client_id: int, path: str = None) -> list:
    path = path or DB_PATH
    with get_conn(path) as conn:
        rows = conn.execute('''
            SELECT a.*, j.title, j.company, j.location, j.source, j.url, j.spec AS job_spec
            FROM applications a JOIN jobs j ON j.id = a.job_id
            WHERE a.client_id = ? ORDER BY a.created_at DESC
        ''', (client_id,)).fetchall()
    out = []
    for r in rows:
        d = _row_to_application(r)
        d.update({'title': r['title'], 'company': r['company'], 'location': r['location'],
                   'source': r['source'], 'url': r['url'], 'job_spec': r['job_spec']})
        out.append(d)
    return out


def get_application_by_token(token: str, path: str = None):
    path = path or DB_PATH
    with get_conn(path) as conn:
        row = conn.execute('SELECT * FROM applications WHERE review_token = ?', (token,)).fetchone()
    return _row_to_application(row) if row else None


def mark_submitted(app_id: int, verification: str, path: str = None) -> None:
    path = path or DB_PATH
    with get_conn(path) as conn:
        conn.execute(
            'UPDATE applications SET status = ?, verification = ?, submitted_at = ? WHERE id = ?',
            ('SUBMITTED_VERIFIED', verification, now(), app_id),
        )


def count_applications_this_month(client_id: int, path: str = None) -> int:
    path = path or DB_PATH
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    with get_conn(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE client_id = ? AND created_at LIKE ?",
            (client_id, f'{month}%'),
        ).fetchone()
    return row['c']
