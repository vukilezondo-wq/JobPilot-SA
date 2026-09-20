"""
Fact-guard layer.

Rule: anything sent to a client as drafted application content must be
traceable to something the candidate explicitly entered (verified
skills, qualifications, experience summary) or their raw uploaded CV
text. Nothing else is allowed to appear as a claim.

This is the layer that was missing from the Manus build — it confidently
reframed 15 years of insurance/QA work as "product analytics" experience
for a role needing SQL. That kind of generous reframing is exactly what
this module exists to stop.

Two things live here:
1. safe_summary() / safe_cover_letter() — generate application text
   using ONLY verified fields via templates. They are structurally
   incapable of inventing a skill or qualification, because they never
   free-generate text; they assemble it from what the candidate typed.
2. audit_generated_text() — if an LLM is later plugged in for richer
   copywriting, run its output through this before it reaches a client.
   It flags any qualification/experience-sounding claim that doesn't
   trace back to the candidate's verified data or CV text, so a human
   can strip or fix it before sending.
"""
import re
from matching import tokenize

CLAIM_MARKERS = [
    'experience', 'certified', 'certification', 'degree', 'diploma',
    'proficient', 'expert', 'skilled', 'years of', 'qualified', 'trained',
    'licensed', 'accredited',
]


def safe_summary(candidate: dict, matched_required: list, matched_preferred: list) -> str:
    exp = candidate.get('experience', '').strip()
    skills = candidate.get('skills', [])
    quals = candidate.get('qualifications', [])
    parts = []
    if exp:
        parts.append(exp)
    if skills:
        parts.append(f"Core skills: {', '.join(skills[:8])}.")
    if quals:
        parts.append(f"Qualifications: {', '.join(quals[:5])}.")
    if matched_required:
        parts.append(
            "Directly relevant to this role's stated requirements: "
            + "; ".join(matched_required[:3]) + "."
        )
    if not parts:
        return ("ACTION_REQUIRED: no verified experience, skills or qualifications "
                "on file to summarise — complete the candidate profile first.")
    return " ".join(parts)


def safe_cover_letter(candidate: dict, job_title: str, company: str, matched_required: list) -> str:
    name = candidate.get('name') or 'the applicant'
    exp = candidate.get('experience', '').strip()
    lines = [f"Dear Hiring Team at {company},"]
    if exp:
        lines.append(exp)
    if matched_required:
        lines.append(
            "This role's stated requirements that I can directly evidence include: "
            + "; ".join(matched_required[:4]) + "."
        )
    else:
        lines.append(
            "ACTION_REQUIRED: none of this profile's verified skills/qualifications "
            "matched this role's stated requirements — review before sending."
        )
    lines.append(
        f"I would welcome the opportunity to discuss the {job_title} role further.\n\nRegards,\n{name}"
    )
    return "\n\n".join(lines)


def audit_generated_text(text: str, candidate: dict, cv_text: str) -> list:
    """Flags sentences containing qualification/experience-style claims
    that don't appear anywhere in the candidate's verified fields or raw
    CV text. Use this on any externally-generated (LLM) copy before a
    client sees it — the templated functions above don't need it, since
    they can't invent claims in the first place."""
    verified_pool = tokenize(" ".join([
        *candidate.get('skills', []),
        *candidate.get('qualifications', []),
        candidate.get('experience', ''),
        cv_text or '',
    ]))
    flags = []
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        low = sentence.lower()
        if any(marker in low for marker in CLAIM_MARKERS):
            sentence_tokens = tokenize(sentence)
            if sentence_tokens and not (sentence_tokens & verified_pool):
                flags.append(sentence.strip())
    return flags
