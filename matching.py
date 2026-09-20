"""
Matching engine.

Design goals (fixing what both prior builds got wrong):
- No arbitrary score floor. The earlier ChatGPT build gave every job a
  40% minimum regardless of overlap; the Manus build scored a 15-year
  insurance broker at 92% against a Product Analyst / SQL role. Both
  produce match scores clients can't trust at a glance.
- Score against the job's actual requirement lines, not just raw keyword
  soup, and weight "required" lines far more heavily than "preferred"
  ones — missing a hard requirement should visibly hurt the score.
- Always return *why* a job scored the way it did (matched / missing
  requirement lines), because an opaque percentage is what let the
  previous builds' bad matches go unnoticed.
"""
import re

STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'your', 'you',
    'are', 'will', 'our', 'their', 'they', 'have', 'has', 'been', 'into',
    'job', 'role', 'work', 'years', 'experience', 'required', 'ability',
    'must', 'should', 'using', 'within', 'a', 'an', 'to', 'of', 'in', 'on',
    'as', 'is', 'be', 'we', 'can', 'it', 'or', 'at',
}

PREFERRED_MARKERS = [
    r'preferred', r'nice to have', r'advantageous', r'a plus', r'bonus',
    r'desirable',
]


def tokenize(text: str) -> set:
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9+#.-]{2,}', text.lower())
    return {w for w in words if w not in STOPWORDS}


def split_bullets(text: str) -> list:
    """Split a job spec into individual requirement-ish lines."""
    lines = re.split(r'\n+', text)
    bullets = [ln.strip(' -*•\t') for ln in lines if len(ln.strip(' -*•\t')) > 3]
    if not bullets:
        # No line breaks pasted in — fall back to sentence splitting.
        bullets = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    return bullets


def classify_bullets(spec: str):
    """Everything from the first 'preferred/nice-to-have'-style heading
    onward is treated as soft requirements; everything before it is
    treated as required. If no such heading exists, all of it is
    required — the safer default, since nothing should get a free pass
    just because the spec wasn't well-structured."""
    required, preferred = [], []
    in_preferred = False
    for bullet in split_bullets(spec):
        low = bullet.lower()
        if any(re.search(m, low) for m in PREFERRED_MARKERS):
            in_preferred = True
        (preferred if in_preferred else required).append(bullet)
    return required, preferred


def bullet_matches(bullet: str, verified_phrases: set) -> bool:
    """Checks a requirement line against the candidate's verified
    skills/qualifications two ways: first as an exact phrase match (so
    multi-word skills like 'a/b testing' or 'product analytics' are
    matched as whole phrases, not lost to word-by-word tokenizing), then
    falling back to word-level overlap for paraphrased wording."""
    low = bullet.lower()
    if any(phrase and phrase in low for phrase in verified_phrases):
        return True
    bullet_tokens = tokenize(bullet)
    phrase_tokens = set()
    for phrase in verified_phrases:
        phrase_tokens |= tokenize(phrase)
    return bool(bullet_tokens & phrase_tokens)


def match(candidate: dict, job_spec: str, job_title: str) -> dict:
    skills = {s.lower() for s in candidate.get('skills', [])}
    quals = {q.lower() for q in candidate.get('qualifications', [])}
    verified_terms = skills | quals

    required, preferred = classify_bullets(job_spec)
    matched_required = [b for b in required if bullet_matches(b, verified_terms)]
    missing_required = [b for b in required if not bullet_matches(b, verified_terms)]
    matched_preferred = [b for b in preferred if bullet_matches(b, verified_terms)]

    note = None
    if required:
        req_ratio = len(matched_required) / len(required)
    else:
        req_ratio = 0.5  # spec had no detectable requirement lines — stay neutral
        note = 'Job spec had no clear requirement lines — treat this score cautiously.'

    pref_ratio = (len(matched_preferred) / len(preferred)) if preferred else 0.0

    role_terms = {r.lower() for r in candidate.get('roles', []) if r}
    title_hit = any(r in job_title.lower() for r in role_terms)

    score = round(min(100, req_ratio * 75 + pref_ratio * 15 + (10 if title_hit else 0)))

    if score >= 75:
        decision = 'PASS'
    elif score >= 45:
        decision = 'REVIEW'
    else:
        decision = 'HOLD'

    return {
        'score': score,
        'decision': decision,
        'matched_required': matched_required,
        'missing_required': missing_required[:15],
        'matched_preferred': matched_preferred,
        'note': note,
    }
