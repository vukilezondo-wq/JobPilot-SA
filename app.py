"""
JobPilot SA — MVP v2

What changed from the previous ChatGPT build, and why:
- matching.py: scores against actual requirement lines instead of a flat
  40% floor, so an unrelated job no longer shows an inflated match %.
- factguard.py: application summaries/cover letters are assembled only
  from verified candidate fields (never free-generated), and any future
  LLM-drafted text can be audited against the candidate's real data
  before a client sees it.
- review.py: blocks duplicate applications against the same vacancy, and
  routes anything needing a CAPTCHA, an unanswerable question, or a
  fact-guard flag to a unique client-facing review link — never to you
  or a staff member.
- Renamed plans to Free / Pro / Concierge to match the three-tier
  structure discussed, gated by monthly application-record limits.

Still deliberately stubbed, for whoever continues this build:
- Real hosting, a multi-tenant database, and authentication. This uses
  one flat JSON file — fine for a single-user demo, not for real clients.
- Job-board discovery / scraping / APIs — vacancies are entered manually
  here as a test harness for the matching and safeguard logic.
- Real automatic submission against ATS platforms (Greenhouse, Lever,
  etc.) — this only classifies whether a route could plausibly be
  authorised; it does not fill or submit anything on a live site.
- Payment processing — plan selection is a dropdown, not a checkout.
- Email/WhatsApp delivery of the client-review link — it is only
  displayed on screen here.
"""
import hashlib
from datetime import datetime, timezone

import streamlit as st

from storage import load, save, now
from matching import match
from factguard import safe_summary, safe_cover_letter, audit_generated_text
from review import (
    job_fingerprint, is_duplicate_job, has_existing_application,
    new_review_token, review_link,
)
from discovery import search_adzuna

PLANS = {
    'Free': {'limit': 5, 'price': 0},
    'Pro': {'limit': 50, 'price': 149},
    'Concierge': {'limit': 10 ** 9, 'price': 349},
}

st.set_page_config(page_title='JobPilot SA', layout='wide')
data = load()

# --------------------------------------------------------------------
# Client review branch — this is where a CAPTCHA/flagged-case link lands.
# --------------------------------------------------------------------
query = st.query_params
if 'review' in query:
    token = query['review']
    record = next((a for a in data['applications'] if a.get('review_token') == token), None)
    st.title('JobPilot SA — Application Review')
    if not record:
        st.error('This review link is invalid or has expired.')
        st.stop()

    st.subheader(f"{record['title']} — {record['company']}")
    st.write(f"**Why this needs you:** {record.get('flag_reason', 'Manual review required.')}")

    st.markdown('### Drafted summary')
    st.write(record.get('summary', ''))
    st.markdown('### Drafted cover letter')
    st.write(record.get('cover_letter', ''))

    if record.get('fact_flags'):
        st.warning('These lines could not be verified against your profile — edit or remove before sending:')
        for flag in record['fact_flags']:
            st.write(f"- {flag}")

    unanswered = [q for q in record.get('questions', []) if q['answer'] == 'ACTION_REQUIRED']
    if unanswered:
        st.markdown('### Unanswered screening questions')
        for q in unanswered:
            st.text_input(q['question'], key='rq_' + q['question'])

    st.markdown('---')
    st.write(
        'Finish this application yourself on the employer/job-board site '
        '(including solving any CAPTCHA), then confirm below.'
    )
    confirmation = st.text_input('Confirmation reference or email subject line (your evidence of submission)')
    if st.button('Mark as submitted'):
        if not confirmation.strip():
            st.error('Add some confirmation evidence first — nothing is marked verified without it.')
        else:
            record['status'] = 'SUBMITTED_VERIFIED'
            record['verification'] = confirmation.strip()
            record['submitted_at'] = now()
            save(data)
            st.success('Recorded — thank you.')
    st.stop()

# --------------------------------------------------------------------
# Main app
# --------------------------------------------------------------------
st.title('JobPilot SA')
st.caption('Matching, fact-guarded drafting, duplicate prevention, and client-review handoff')

with st.sidebar:
    plan = st.selectbox(
        'Plan', list(PLANS.keys()),
        index=list(PLANS.keys()).index(data['settings'].get('plan', 'Free')),
    )
    data['settings']['plan'] = plan
    save(data)
    this_month = datetime.now(timezone.utc).strftime('%Y-%m')
    used = sum(a.get('created_at', '').startswith(this_month) for a in data['applications'])
    st.metric('Application records this month', f"{used} / {PLANS[plan]['limit']}")
    st.write(f"R{PLANS[plan]['price']}/month" if PLANS[plan]['price'] else 'Free tier')
    st.info('CAPTCHA and low-confidence cases always go to the client via a review link — never to staff.')

tab_candidate, tab_vacancies, tab_apps, tab_reports = st.tabs(
    ['Candidate', 'Vacancies', 'Applications', 'Client Reports']
)

with tab_candidate:
    c = data['candidate']
    st.header('Candidate profile')
    c['name'] = st.text_input('Full name', c.get('name', ''))
    c['email'] = st.text_input('Email', c.get('email', ''))
    c['phone'] = st.text_input('Phone', c.get('phone', ''))
    c['location'] = st.text_input('Preferred location', c.get('location', ''))
    c['roles'] = [x.strip() for x in st.text_input(
        'Target roles (comma separated)', ','.join(c.get('roles', []))).split(',') if x.strip()]
    c['skills'] = [x.strip().lower() for x in st.text_input(
        'Verified skills (comma separated)', ','.join(c.get('skills', []))).split(',') if x.strip()]
    c['qualifications'] = [x.strip() for x in st.text_input(
        'Verified qualifications (comma separated)', ','.join(c.get('qualifications', []))).split(',') if x.strip()]
    c['experience'] = st.text_area('Verified experience summary', c.get('experience', ''), height=120)
    c['salary'] = st.text_input('Minimum salary (optional)', c.get('salary', ''))

    upload = st.file_uploader('Upload CV', type=['pdf', 'docx', 'txt'])
    if upload is not None:
        name = upload.name.lower()
        raw = upload.read()
        if name.endswith('.pdf'):
            from io import BytesIO
            from pypdf import PdfReader
            data['cv_text'] = '\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(raw)).pages)
        elif name.endswith('.docx'):
            from io import BytesIO
            from docx import Document
            data['cv_text'] = '\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
        else:
            data['cv_text'] = raw.decode('utf-8', 'ignore')
        st.success(f"CV loaded: {len(data['cv_text'].split())} words")

    if data.get('cv_text'):
        with st.expander('Review extracted CV text'):
            st.text(data['cv_text'][:12000])

    data['settings']['consent'] = st.checkbox(
        'I consent to automatic applications only where JobPilot has a legitimate, '
        'authorised submission route. I understand applications are never marked '
        'verified without submission evidence.',
        value=data['settings'].get('consent', False),
    )

    if st.button('Save candidate profile'):
        save(data)
        st.success('Saved')

with tab_vacancies:
    st.header('Vacancy intake and matching')

    st.subheader('Search job boards')
    st.caption(
        'Uses Adzuna\'s South Africa job search API. Free key: '
        'register at https://developer.adzuna.com/, then enter your app_id/app_key below.'
    )
    s = data['settings']
    col1, col2 = st.columns(2)
    s['adzuna_app_id'] = col1.text_input('Adzuna app_id', s.get('adzuna_app_id', ''))
    s['adzuna_app_key'] = col2.text_input('Adzuna app_key', s.get('adzuna_app_key', ''), type='password')
    default_what = ', '.join(data['candidate'].get('roles', [])) or 'e.g. product analyst'
    what = st.text_input('Search for', default_what)
    where = st.text_input('Location', data['candidate'].get('location', 'South Africa') or 'South Africa')

    if st.button('Search Adzuna'):
        save(data)
        try:
            found = search_adzuna(s['adzuna_app_id'], s['adzuna_app_key'], what, where)
        except ValueError as e:
            st.error(str(e))
            found = []
        except Exception as e:
            st.error(f'Search failed: {e}')
            found = []

        added, skipped = 0, 0
        for f in found:
            if is_duplicate_job(data['jobs'], f['title'], f['company'], f['location']):
                skipped += 1
                continue
            fp = job_fingerprint(f['title'], f['company'], f['location'])
            result = match(data['candidate'], f['spec'], f['title'])
            job = {
                'id': fp, 'fingerprint': fp, 'title': f['title'], 'company': f['company'],
                'location': f['location'], 'source': f['source'], 'url': f['url'],
                'spec': f['spec'], 'created_at': now(), **result,
            }
            data['jobs'].append(job)
            added += 1
        if found or added or skipped:
            save(data)
            st.success(f'Added {added} new vacancies, skipped {skipped} already in your pipeline.')

    st.markdown('---')
    st.subheader('Or add a vacancy manually')
    st.caption('Useful for a specific posting Adzuna doesn\'t carry, e.g. a direct Greenhouse/Lever listing.')

    with st.form('add_job'):
        title = st.text_input('Job title')
        company = st.text_input('Company')
        loc = st.text_input('Location')
        source = st.selectbox('Source', ['PNet', 'Employer site', 'Greenhouse', 'Lever', 'Other'])
        url = st.text_input('Vacancy URL')
        spec = st.text_area('Full job specification (paste the whole listing)', height=220)
        submitted = st.form_submit_button('Add and analyse')

    if submitted and title and company and spec:
        if is_duplicate_job(data['jobs'], title, company, loc):
            st.error('This vacancy already exists in your pipeline — duplicate blocked.')
        else:
            fp = job_fingerprint(title, company, loc)
            result = match(data['candidate'], spec, title)
            job = {
                'id': fp, 'fingerprint': fp, 'title': title, 'company': company,
                'location': loc, 'source': source, 'url': url, 'spec': spec,
                'created_at': now(), **result,
            }
            data['jobs'].append(job)
            save(data)
            st.success(f"{job['decision']} — {job['score']}% match")
            if job.get('note'):
                st.caption(job['note'])

    for j in data['jobs']:
        st.markdown(f"**{j['title']} — {j['company']}** · {j['score']}% · `{j['decision']}`")
        st.caption(f"{j['source']} · {j['location']}")
        with st.expander('Match detail'):
            st.write('Matched required:', j.get('matched_required') or 'None')
            st.write('Missing required:', j.get('missing_required') or 'None')
            st.write('Matched preferred:', j.get('matched_preferred') or 'None')
            if j.get('note'):
                st.caption(j['note'])

with tab_apps:
    st.header('Application engine')
    c = data['candidate']

    for j in data['jobs']:
        if has_existing_application(data['applications'], j['id']):
            continue

        st.subheader(f"{j['title']} — {j['company']}")
        st.write(f"Match **{j['score']}%** · **{j['decision']}**")

        qtext = st.text_area('Application screening questions — one per line', key='q' + j['id'])
        answers = []
        for q in [x.strip() for x in qtext.splitlines() if x.strip()]:
            ql = q.lower()
            ans = None
            if 'email' in ql:
                ans = c.get('email')
            elif 'phone' in ql or 'mobile' in ql:
                ans = c.get('phone')
            elif 'location' in ql or 'city' in ql:
                ans = c.get('location')
            elif 'salary' in ql:
                ans = c.get('salary')
            elif 'experience' in ql:
                ans = c.get('experience')
            answers.append({
                'question': q,
                'answer': ans or 'ACTION_REQUIRED',
                'source': 'verified profile' if ans else 'not verified — needs candidate/client input',
            })
        if answers:
            st.json(answers)

        summary = safe_summary(c, j.get('matched_required', []), j.get('matched_preferred', []))
        cover_letter = safe_cover_letter(c, j['title'], j['company'], j.get('matched_required', []))
        fact_flags = audit_generated_text(summary + " " + cover_letter, c, data.get('cv_text', ''))

        st.markdown('**Drafted summary (built only from your verified fields):**')
        st.write(summary)
        st.markdown('**Drafted cover letter:**')
        st.write(cover_letter)

        needs_captcha = j['source'] in ('Employer site', 'Other')
        missing_answers = any(a['answer'] == 'ACTION_REQUIRED' for a in answers)
        needs_review = needs_captcha or missing_answers or bool(fact_flags)

        route = (
            f"{j['source']} — authorisation required" if j['source'] in ('Greenhouse', 'Lever', 'PNet')
            else 'Manual / employer site — client must complete'
        )
        st.write('**Submission route:**', route)

        if st.button('Create application record', key='mk' + j['id']):
            this_month = datetime.now(timezone.utc).strftime('%Y-%m')
            used = sum(a.get('created_at', '').startswith(this_month) for a in data['applications'])
            if used >= PLANS[data['settings'].get('plan', 'Free')]['limit']:
                st.error('Plan limit reached for this month.')
            else:
                ts = now()
                record = {
                    'id': hashlib.sha1(f"{j['id']}{ts}".encode()).hexdigest()[:12],
                    'job_id': j['id'], 'title': j['title'], 'company': j['company'],
                    'location': j['location'], 'source': j['source'], 'url': j['url'],
                    'job_spec': j['spec'], 'match_score': j['score'], 'decision': j['decision'],
                    'route': route, 'created_at': ts, 'summary': summary,
                    'cover_letter': cover_letter, 'fact_flags': fact_flags,
                    'questions': answers, 'submission_id': None,
                    'verification': 'No submission evidence recorded.',
                }
                if needs_review:
                    reasons = []
                    if needs_captcha:
                        reasons.append('this source likely requires a CAPTCHA or manual portal steps')
                    if missing_answers:
                        reasons.append('one or more screening questions have no verified answer')
                    if fact_flags:
                        reasons.append('drafted text contains claims that could not be verified against the profile')
                    record['status'] = 'CLIENT_REVIEW'
                    record['flag_reason'] = '; '.join(reasons)
                    record['review_token'] = new_review_token()
                    data['applications'].append(record)
                    save(data)
                    link = review_link('https://your-deployed-app-url', record['review_token'])
                    st.success('Sent for client review — nothing was submitted automatically.')
                    st.code(link)
                    st.caption('In production this link is emailed/WhatsApped to the client automatically — wire that up before launch.')
                else:
                    record['status'] = 'PREPARED'
                    data['applications'].append(record)
                    save(data)
                    st.success('Prepared — ready for submission where an authorised route exists.')

with tab_reports:
    st.header('Client reports')
    st.caption('Every record keeps the full job spec, drafted content, fact-guard flags, and verification status.')
    if not data['applications']:
        st.info('No records yet.')
    for a in reversed(data['applications']):
        with st.expander(f"{a['title']} — {a['company']} · {a['status']}"):
            for k in ['match_score', 'decision', 'source', 'route', 'status',
                      'created_at', 'submission_id', 'verification', 'url']:
                st.write(f"**{k.replace('_', ' ').title()}:**", a.get(k))
            if a.get('fact_flags'):
                st.warning('Unverified claims flagged by fact-guard: ' + '; '.join(a['fact_flags']))
            st.markdown('### Full job specification')
            st.write(a['job_spec'])
            st.markdown('### Drafted summary')
            st.write(a.get('summary', ''))
            st.markdown('### Drafted cover letter')
            st.write(a.get('cover_letter', ''))
            st.markdown('### Application questions / answers')
            st.json(a['questions'])
