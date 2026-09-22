"""
JobPilot SA — MVP v6 (multi-client, database-backed)

The single biggest change from v5: this is no longer one profile per
deployment. Every client identifies themselves by email on entry, and
db.py keeps their profile, vacancies, and applications completely
separate from every other client's — tested explicitly in db.py's own
test run (client isolation, per-client job dedup, per-client application
dedup all verified before this was wired in here).

IMPORTANT — read this before treating this as production-ready:
Clients are identified by email with NO PASSWORD. That's enough to keep
one client's data from colliding with another's, but it is NOT secure
authentication — anyone who knows or guesses a client's email could open
their profile. This is a deliberate, disclosed limitation, not something
hidden: add real authentication (e.g. a proper login provider) before
this holds any client's data in a setting where that matters. See
ARCHITECTURE.md for what a production auth/hosting setup looks like.

Everything else — matching, fact-guard, CAPTCHA/review-link handoff,
tiers — works exactly as in v5, just scoped per client now instead of
per deployment.
"""
import hashlib
from datetime import datetime, timezone

import streamlit as st

import db
from matching import match
from factguard import safe_summary, safe_cover_letter, audit_generated_text
from discovery import search_adzuna
from review import job_fingerprint, new_review_token, review_link

PLANS = {
    'Free': {'limit': 5, 'price': 0},
    'Pro': {'limit': 50, 'price': 149},
    'Concierge': {'limit': 10 ** 9, 'price': 349},
}

st.set_page_config(page_title='JobPilot SA', layout='wide')
db.init_db()

# --------------------------------------------------------------------
# Client review branch — the CAPTCHA/flagged-case link destination.
# No email/identity needed here: the token itself is the access key.
# --------------------------------------------------------------------
query = st.query_params
if 'review' in query:
    record = db.get_application_by_token(query['review'])
    st.title('JobPilot SA — Application Review')
    if not record:
        st.error('This review link is invalid or has expired.')
        st.stop()

    st.subheader(f"{record['title']} — {record['company']}")
    st.write(f"**Why this needs you:** {record.get('flag_reason') or 'Manual review required.'}")
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
    st.write('Finish this application yourself (including any CAPTCHA), then confirm below.')
    confirmation = st.text_input('Confirmation reference or email subject line (your evidence of submission)')
    if st.button('Mark as submitted'):
        if not confirmation.strip():
            st.error('Add some confirmation evidence first — nothing is marked verified without it.')
        else:
            db.mark_submitted(record['id'], confirmation.strip())
            st.success('Recorded — thank you.')
    st.stop()

# --------------------------------------------------------------------
# Sign up / log in (real password authentication — see db.py's module
# docstring for why passkeys aren't hand-built here).
# --------------------------------------------------------------------
st.title('JobPilot SA')
st.caption('Matching, fact-guarded drafting, duplicate prevention, and client-review handoff')

if 'client' not in st.session_state:
    st.session_state.client = None

if st.session_state.client is None:
    mode = st.radio('', ['Log in', 'Sign up'], horizontal=True, label_visibility='collapsed')

    if mode == 'Sign up':
        with st.form('signup_form'):
            su_email = st.text_input('Email')
            su_password = st.text_input('Password', type='password')
            su_password2 = st.text_input('Confirm password', type='password')
            st.caption('At least 10 characters, including a letter and a number.')
            submitted = st.form_submit_button('Create account')
        if submitted:
            if su_password != su_password2:
                st.error('Passwords do not match.')
            elif not su_email.strip():
                st.error('Email is required.')
            else:
                try:
                    client = db.create_client(su_email, su_password)
                    st.session_state.client = client
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    else:
        with st.form('login_form'):
            li_email = st.text_input('Email')
            li_password = st.text_input('Password', type='password')
            submitted = st.form_submit_button('Log in')
        if submitted:
            client = db.verify_login(li_email, li_password)
            if client is None:
                st.error('Incorrect email or password.')
            else:
                st.session_state.client = client
                st.rerun()
    st.stop()

client = st.session_state.client
client_id = client['client_id']

with st.sidebar:
    st.write(f"Signed in as **{client['email']}**")
    if st.button('Log out'):
        st.session_state.client = None
        st.rerun()
    with st.expander('Change password'):
        with st.form('change_pw_form'):
            new_pw = st.text_input('New password', type='password')
            new_pw2 = st.text_input('Confirm new password', type='password')
            pw_submit = st.form_submit_button('Update password')
        if pw_submit:
            if new_pw != new_pw2:
                st.error('Passwords do not match.')
            else:
                try:
                    db.change_password(client_id, new_pw)
                    st.success('Password updated.')
                except ValueError as e:
                    st.error(str(e))
    plan = st.selectbox('Plan', list(PLANS.keys()), index=list(PLANS.keys()).index(client.get('plan', 'Free')))
    if plan != client['plan']:
        db.save_candidate(client_id, {'plan': plan})
        client['plan'] = plan
    used = db.count_applications_this_month(client_id)
    st.metric('Application records this month', f"{used} / {PLANS[plan]['limit']}")
    st.write(f"R{PLANS[plan]['price']}/month" if PLANS[plan]['price'] else 'Free tier')
    st.info('CAPTCHA and low-confidence cases always go to the client via a review link — never to staff.')

tab_candidate, tab_vacancies, tab_apps, tab_reports = st.tabs(
    ['Candidate', 'Vacancies', 'Applications', 'Client Reports']
)

with tab_candidate:
    st.header('Candidate profile')
    name = st.text_input('Full name', client.get('name', ''))
    phone = st.text_input('Phone', client.get('phone', ''))
    location = st.text_input('Preferred location', client.get('location', ''))
    roles = [x.strip() for x in st.text_input(
        'Target roles (comma separated)', ', '.join(client.get('roles', []))).split(',') if x.strip()]
    skills = [x.strip().lower() for x in st.text_input(
        'Verified skills (comma separated)', ', '.join(client.get('skills', []))).split(',') if x.strip()]
    qualifications = [x.strip() for x in st.text_input(
        'Verified qualifications (comma separated)', ', '.join(client.get('qualifications', []))).split(',') if x.strip()]
    experience = st.text_area('Verified experience summary', client.get('experience', ''), height=120)
    salary = st.text_input('Minimum salary (optional)', client.get('salary', ''))

    cv_text = client.get('cv_text', '')
    upload = st.file_uploader('Upload CV', type=['pdf', 'docx', 'txt'])
    if upload is not None:
        fname = upload.name.lower()
        raw = upload.read()
        if fname.endswith('.pdf'):
            from io import BytesIO
            from pypdf import PdfReader
            cv_text = '\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(raw)).pages)
        elif fname.endswith('.docx'):
            from io import BytesIO
            from docx import Document
            cv_text = '\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
        else:
            cv_text = raw.decode('utf-8', 'ignore')
        st.success(f"CV loaded: {len(cv_text.split())} words")

    if cv_text:
        with st.expander('Review extracted CV text'):
            st.text(cv_text[:12000])

    consent = st.checkbox(
        'I consent to automatic applications only where JobPilot has a legitimate, '
        'authorised submission route. I understand applications are never marked '
        'verified without submission evidence.',
        value=client.get('consent', False),
    )
    whatsapp_opt_in = st.checkbox(
        'Also send my daily job match notifications via WhatsApp (in addition to email). '
        'Requires a valid phone number above, in international format (e.g. +27821234567).',
        value=client.get('whatsapp_opt_in', False),
    )

    if st.button('Save candidate profile'):
        db.save_candidate(client_id, {
            'name': name, 'phone': phone, 'location': location, 'roles': roles,
            'skills': skills, 'qualifications': qualifications, 'experience': experience,
            'salary': salary, 'cv_text': cv_text, 'consent': consent,
            'whatsapp_opt_in': whatsapp_opt_in,
        })
        st.success('Saved')
        st.rerun()

with tab_vacancies:
    st.header('Vacancy intake and matching')

    st.subheader('Search job boards')
    st.caption('Uses Adzuna\'s South Africa job search API. Free key: register at https://developer.adzuna.com/')
    col1, col2 = st.columns(2)
    adzuna_id = col1.text_input('Adzuna app_id', st.session_state.get('adzuna_id', ''))
    adzuna_key = col2.text_input('Adzuna app_key', st.session_state.get('adzuna_key', ''), type='password')
    st.session_state['adzuna_id'], st.session_state['adzuna_key'] = adzuna_id, adzuna_key
    what = st.text_input('Search for', ', '.join(client.get('roles', [])) or 'e.g. product analyst')
    where = st.text_input('Location', client.get('location') or 'South Africa')

    if st.button('Search Adzuna'):
        try:
            found = search_adzuna(adzuna_id, adzuna_key, what, where)
        except Exception as e:
            st.error(f'Search failed: {e}')
            found = []
        added, skipped = 0, 0
        for f in found:
            fp = job_fingerprint(f['title'], f['company'], f['location'])
            if db.is_duplicate_job(client_id, fp):
                skipped += 1
                continue
            result = match(client, f['spec'], f['title'])
            job_id = db.add_job(client_id, {'fingerprint': fp, 'source': f['source'],
                                             'url': f['url'], **f, **result})
            if job_id:
                added += 1
            else:
                skipped += 1
        st.success(f'Added {added} new vacancies, skipped {skipped} already in your pipeline.')

    st.markdown('---')
    st.subheader('Or add a vacancy manually')
    with st.form('add_job'):
        title = st.text_input('Job title')
        company = st.text_input('Company')
        loc = st.text_input('Location')
        source = st.selectbox('Source', ['PNet', 'Employer site', 'Greenhouse', 'Lever', 'Other'])
        url = st.text_input('Vacancy URL')
        spec = st.text_area('Full job specification (paste the whole listing)', height=220)
        submitted = st.form_submit_button('Add and analyse')

    if submitted and title and company and spec:
        fp = job_fingerprint(title, company, loc)
        if db.is_duplicate_job(client_id, fp):
            st.error('This vacancy already exists in your pipeline — duplicate blocked.')
        else:
            result = match(client, spec, title)
            db.add_job(client_id, {
                'fingerprint': fp, 'title': title, 'company': company, 'location': loc,
                'source': source, 'url': url, 'spec': spec, **result,
            })
            st.success(f"{result['decision']} — {result['score']}% match")

    for j in db.list_jobs(client_id):
        st.markdown(f"**{j['title']} — {j['company']}** · {j['score']}% · `{j['decision']}`")
        st.caption(f"{j['source']} · {j['location']}")
        with st.expander('Match detail'):
            st.write('Matched required:', j.get('matched_required') or 'None')
            st.write('Missing required:', j.get('missing_required') or 'None')
            st.write('Matched preferred:', j.get('matched_preferred') or 'None')

with tab_apps:
    st.header('Application engine')
    for j in db.list_jobs(client_id):
        if db.has_existing_application(j['id']):
            continue
        st.subheader(f"{j['title']} — {j['company']}")
        st.write(f"Match **{j['score']}%** · **{j['decision']}**")

        qtext = st.text_area('Application screening questions — one per line', key='q' + str(j['id']))
        answers = []
        for q in [x.strip() for x in qtext.splitlines() if x.strip()]:
            ql = q.lower()
            ans = None
            if 'email' in ql:
                ans = client.get('email')
            elif 'phone' in ql or 'mobile' in ql:
                ans = client.get('phone')
            elif 'location' in ql or 'city' in ql:
                ans = client.get('location')
            elif 'salary' in ql:
                ans = client.get('salary')
            elif 'experience' in ql:
                ans = client.get('experience')
            answers.append({'question': q, 'answer': ans or 'ACTION_REQUIRED',
                             'source': 'verified profile' if ans else 'not verified'})
        if answers:
            st.json(answers)

        summary = safe_summary(client, j.get('matched_required', []), j.get('matched_preferred', []))
        cover_letter = safe_cover_letter(client, j['title'], j['company'], j.get('matched_required', []))
        fact_flags = audit_generated_text(summary + " " + cover_letter, client, client.get('cv_text', ''))

        st.markdown('**Drafted summary:**')
        st.write(summary)
        st.markdown('**Drafted cover letter:**')
        st.write(cover_letter)

        needs_captcha = j['source'] in ('Employer site', 'Other')
        missing_answers = any(a['answer'] == 'ACTION_REQUIRED' for a in answers)
        needs_review = needs_captcha or missing_answers or bool(fact_flags)
        route = (f"{j['source']} — authorisation required" if j['source'] in ('Greenhouse', 'Lever', 'PNet')
                 else 'Manual / employer site — client must complete')
        st.write('**Submission route:**', route)

        if st.button('Create application record', key='mk' + str(j['id'])):
            if used >= PLANS[client['plan']]['limit']:
                st.error('Plan limit reached for this month.')
            else:
                record = {'route': route, 'summary': summary, 'cover_letter': cover_letter,
                          'fact_flags': fact_flags, 'questions': answers}
                if needs_review:
                    reasons = []
                    if needs_captcha:
                        reasons.append('this source likely requires a CAPTCHA or manual portal steps')
                    if missing_answers:
                        reasons.append('one or more screening questions have no verified answer')
                    if fact_flags:
                        reasons.append('drafted text contains unverifiable claims')
                    record['status'] = 'CLIENT_REVIEW'
                    record['flag_reason'] = '; '.join(reasons)
                    record['review_token'] = new_review_token()
                    db.add_application(client_id, j['id'], record)
                    link = review_link('https://your-deployed-app-url', record['review_token'])
                    st.success('Sent for client review — nothing was submitted automatically.')
                    st.code(link)
                else:
                    record['status'] = 'PREPARED'
                    db.add_application(client_id, j['id'], record)
                    st.success('Prepared — ready for submission where an authorised route exists.')
                st.rerun()

with tab_reports:
    st.header('Client reports')
    apps = db.list_applications(client_id)
    if not apps:
        st.info('No records yet.')
    for a in apps:
        with st.expander(f"{a['title']} — {a['company']} · {a['status']}"):
            for k in ['route', 'status', 'created_at', 'verification', 'url']:
                st.write(f"**{k.replace('_', ' ').title()}:**", a.get(k))
            if a.get('fact_flags'):
                st.warning('Unverified claims flagged: ' + '; '.join(a['fact_flags']))
            st.markdown('### Full job specification')
            st.write(a['job_spec'])
            st.markdown('### Drafted summary')
            st.write(a.get('summary', ''))
            st.markdown('### Drafted cover letter')
            st.write(a.get('cover_letter', ''))
            st.markdown('### Application questions / answers')
            st.json(a['questions'])
