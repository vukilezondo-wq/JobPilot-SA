"""
Job-board discovery — automated search instead of manual paste-in.

Uses Adzuna's job search API (https://developer.adzuna.com), which covers
South Africa and is a licensed, ToS-compliant data source — not scraping.
This directly replaces the "you have to paste in every vacancy yourself"
limitation of the manual-entry test harness.

To use this, get a free API key:
1. Go to https://developer.adzuna.com/
2. Register (free) and create an app
3. You'll get an `app_id` and `app_key` — enter them in the app's
   Vacancies tab under "Search job boards"

Free tier limits apply (a few thousand calls/month) — fine for individual
client use, but track usage if this scales to many clients at once.
"""
import requests

ADZUNA_COUNTRY = 'za'  # South Africa


def parse_adzuna_results(payload: dict) -> list:
    """Separated from the network call so this can be unit-tested without
    hitting the API."""
    jobs = []
    for r in payload.get('results', []):
        company = (r.get('company') or {}).get('display_name', 'Unknown')
        location = (r.get('location') or {}).get('display_name', '')
        jobs.append({
            'title': (r.get('title') or '').strip(),
            'company': company,
            'location': location,
            'spec': r.get('description', ''),
            'url': r.get('redirect_url', ''),
            'source': 'Adzuna',
            'external_id': str(r.get('id', '')),
        })
    return jobs


def search_adzuna(app_id: str, app_key: str, what: str, where: str = 'South Africa',
                   results_per_page: int = 10, page: int = 1) -> list:
    """Raises requests.HTTPError on a bad response (e.g. invalid credentials)
    so the caller can show a clear error instead of silently returning
    nothing."""
    if not app_id or not app_key:
        raise ValueError('Adzuna app_id and app_key are required — see module docstring.')
    url = f'https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/{page}'
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'what': what,
        'where': where,
        'results_per_page': results_per_page,
        'content-type': 'application/json',
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return parse_adzuna_results(resp.json())
