# Handoff prompt — paste this to Manus, ChatGPT, or a developer

Copy everything in the box below as your instruction when you hand over the
project.

---

You are continuing a project called JobPilot SA. I'm attaching the full
codebase as a zip. Before you write or change anything, read `README.md`
and `ARCHITECTURE.md` in full.

**Locked files — do not modify:**
`matching.py`, `factguard.py`, `review.py`

These three files implement safety-critical logic that has already been
written, tested, and verified to behave correctly on specific test cases
(a genuine skills match scores well; an unrelated job scores near zero
instead of an inflated percentage; unverifiable claims are flagged instead
of invented). You may **import and call** these files from new code, but
you may not rewrite, "improve," refactor, simplify, or change any scoring
logic, thresholds, matching approach, or text-generation approach inside
them — including if you believe your version would look better or perform
better. If you think one of them has a genuine bug, stop and describe the
bug to me in plain language instead of fixing it yourself.

**Your job is to build the six things listed in README.md's "Not yet
built" section**, using the specific approach described in
`ARCHITECTURE.md` for each:
1. Real database (the schema is already specified — use it, don't design
   a different one)
2. Job-board discovery (use only the sources listed as compliant —
   Greenhouse/Lever public APIs, Adzuna/Jooble. Do not scrape LinkedIn,
   Indeed, or PNet directly, even if it looks technically easy)
3. Application submission (default every source to "prepare and hand off
   to the client" unless I explicitly confirm we have an official partner
   API with a specific ATS vendor — do not build browser automation that
   fills and submits forms on live job sites, and do not attempt to solve,
   bypass, or work around a CAPTCHA under any circumstance)
4. Payment processing (server-side plan/subscription status only — never
   trust a client-side plan selector for gating features)
5. Review-link delivery via email (and WhatsApp if in scope) instead of
   just displaying the link
6. If you add an LLM for richer application drafting, follow the two-layer
   pattern in ARCHITECTURE.md section 6 exactly: constrained system prompt
   AND `audit_generated_text()` run on every output before a client sees
   it. Do not skip the audit step because the prompt "should" be enough.

**Rules while you work:**
- If you are uncertain whether something is ToS-compliant, technically
  feasible without violating a platform's rules, or within the scope I've
  described, stop and ask me rather than making an assumption and
  proceeding. I would rather you ask a question than confidently guess
  wrong on this project specifically.
- After any change, run this regression check and show me the output
  before I approve merging it:

  ```python
  from matching import match
  candidate_good = {'skills': ['sql', 'python', 'a/b testing', 'product analytics'],
                     'qualifications': [], 'roles': ['product analyst'],
                     'experience': '3 years as a product analyst using SQL and Python for A/B testing.'}
  candidate_bad = {'skills': ['account management', 'quality assurance', 'management reporting'],
                    'qualifications': ['insurance industry certificate'],
                    'roles': ['relationship manager'], 'experience': '15+ years in insurance quality assurance.'}
  spec = '''Product Analyst - Yoco
  Required:
  - 2+ years experience with SQL and data analysis
  - Experience with product analytics tools
  - Strong understanding of A/B testing methodology
  Preferred:
  - Experience with dbt'''
  print(match(candidate_good, spec, 'Product Analyst'))  # expect PASS/REVIEW, score well above 45
  print(match(candidate_bad, spec, 'Product Analyst'))   # expect HOLD, score near 0
  ```

  If either result looks different from the expectation in the comment,
  something touched the locked logic (directly or indirectly) — stop and
  flag it to me instead of proceeding.
- At the end of each work session, explicitly confirm in your summary that
  you did not modify `matching.py`, `factguard.py`, or `review.py`.

Start by telling me your proposed build order for the six items above,
and wait for my confirmation before writing code.

---
