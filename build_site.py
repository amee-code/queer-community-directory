from __future__ import annotations

import base64
import csv
import html
import json
import os
import re
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PUBLISHED_CSV_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRQDMPDHu9vhPVw_XWFGH4xoOHcV5ugsGh1V3JaQc70_zkSO9PU1qtg7qPbFjnpuaOZOUh_GPkpR6nb/pub?output=csv'
SHEET_CSV_URL = os.environ.get('DIRECTORY_SOURCE_URL', PUBLISHED_CSV_URL).strip()
LOCAL_CSV = Path(os.environ.get('DIRECTORY_INPUT_CSV', BASE_DIR / 'Community Service Directory Registration.csv'))
OUTPUT_HTML = Path(os.environ.get('DIRECTORY_OUTPUT_HTML', BASE_DIR / 'index.html'))
COVER_IMAGE = Path(os.environ.get('DIRECTORY_COVER_IMAGE', BASE_DIR / 'queer_community_service_directory_poster.png'))

TITLE = 'Queer Community, Service Directory'
DESCRIPTION = 'A searchable directory of queer community members offering creative, practical, wellness, professional, and home services.'
APPROVED_VALUES = {'yes', 'y', 'true', '1', 'approved'}

FIELD_MAP = {
    'Timestamp': 'timestamp',
    'Full Name': 'full_name',
    'Business or Service Name': 'business',
    'What category best describes your service?': 'category',
    'Briefly describe what you offer': 'description',
    'WhatsApp Number (please include country code)': 'whatsapp',
    'City': 'city',
    'Website or Social Media Link': 'website',
    'Photo of your product or Service': 'photo',
}

CATEGORY_COLORS = {
    'Arts & Design': '#7C3AED',
    'Beauty and Wellness': '#DB2777',
    'Communication': '#2563EB',
    'Counseling & Mental Health': '#0F766E',
    'Education and Tutoring': '#CA8A04',
    'Event Services': '#EA580C',
    'Food & Catering': '#16A34A',
    'Home & Maintenance': '#475569',
    'Legal and Financial': '#4F46E5',
    'Tech and Development': '#0891B2',
    'Writing & Editing': '#64748B',
    'Wellness & Healing': '#059669',
}


def clean(v: object) -> str:
    if v is None:
        return ''
    s = str(v).replace('\r\n', '\n').replace('\r', '\n').strip()
    if s.lower() in {'nan', 'none', 'n/a', 'na', 'not applicable'}:
        return ''
    return s


def esc(v: object) -> str:
    return html.escape(clean(v), quote=True)


def parse_timestamp(s: str) -> datetime | None:
    s = clean(s)
    for fmt in ('%Y/%m/%d %I:%M:%S %p CST', '%Y/%m/%d %I:%M:%S %p'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def month_name(dt: datetime | None) -> str:
    return dt.strftime('%B %Y') if dt else 'Monthly Edition'


def date_display(dt: datetime | None) -> str:
    if not dt:
        return 'Monthly'
    return f'{dt.strftime("%B")} {dt.day}, {dt.year}'


def initials(name: str, business: str) -> str:
    base = business or name or 'Service'
    words = re.findall(r'[A-Za-zÀ-ÿ0-9]+', base)
    if not words:
        return 'S'
    return (words[0][:2] if len(words) == 1 else words[0][0] + words[1][0]).upper()


def display_url(raw: str) -> tuple[str, str]:
    raw = clean(raw)
    if not raw:
        return '', ''
    display = raw.replace('https://', '').replace('http://', '').rstrip('/')
    if raw.startswith('@'):
        return display, ''
    href = raw if re.match(r'^https?://', raw, re.I) else 'https://' + raw
    return display, href


def whatsapp_link(raw: str) -> tuple[str, str]:
    raw = clean(raw)
    if not raw:
        return '', ''
    if '@' in raw and not re.search(r'\d', raw):
        return raw, ''
    compact = re.sub(r'[^\d+]', '', raw.replace('±', '+'))
    if compact.startswith('00'):
        compact = '+' + compact[2:]
    compact = compact.replace('+3106', '+316')
    digits = re.sub(r'\D', '', compact)
    return (raw, f'https://wa.me/{digits}') if len(digits) >= 8 else (raw, '')


def image_data_uri(path: Path) -> str:
    if not path.exists():
        return ''
    mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def fetch_csv() -> Path:
    if SHEET_CSV_URL:
        out = Path(tempfile.gettempdir()) / 'directory_source.csv'
        req = urllib.request.Request(SHEET_CSV_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            out.write_bytes(resp.read())
        return out
    return LOCAL_CSV


def load_entries(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        has_approved_column = bool(reader.fieldnames and 'Approved' in reader.fieldnames)

    entries = []
    for row in rows:
        # Lightweight moderation: if an Approved column exists, only approved rows go live.
        # This lets local/demo CSVs without that column still preview normally.
        if has_approved_column:
            approved = clean(row.get('Approved', '')).lower()
            if approved not in APPROVED_VALUES:
                continue

        e = {out: clean(row.get(col, '')) for col, out in FIELD_MAP.items()}
        e['display_website'], e['website_href'] = display_url(e['website'])
        e['display_whatsapp'], e['whatsapp_href'] = whatsapp_link(e['whatsapp'])
        e['initials'] = initials(e['full_name'], e['business'])
        e['search_blob'] = ' '.join(e.get(k, '') for k in ('business', 'full_name', 'category', 'description', 'city')).lower()
        entries.append(e)
    return sorted(entries, key=lambda x: (x['category'].lower(), x['business'].lower()))


def render(entries: list[dict]) -> str:
    dates = [parse_timestamp(e['timestamp']) for e in entries]
    dates = [d for d in dates if d]
    latest = max(dates) if dates else None
    edition = month_name(latest)
    updated = date_display(latest)
    categories = sorted(Counter(e['category'] for e in entries).items(), key=lambda kv: kv[0].lower())
    cities = sorted(Counter(e['city'] for e in entries).items(), key=lambda kv: (-kv[1], kv[0]))
    cover_uri = image_data_uri(COVER_IMAGE)
    cover = f'<div class="cover-card"><img src="{cover_uri}" alt="{esc(TITLE)} cover art"></div>' if cover_uri else ''

    category_summary = ''.join(
        f'<div class="summary-row"><span class="dot" style="background:{CATEGORY_COLORS.get(cat, "#64748B")}"></span><span>{esc(cat)}</span><strong>{count}</strong></div>'
        for cat, count in categories
    ) or '<p class="muted">No approved listings yet.</p>'
    city_list = ', '.join(f'{esc(city)} ({count})' for city, count in cities if city) or 'No approved listings yet.'

    cards: list[str] = []
    current = None
    for e in entries:
        cat = e['category'] or 'Other'
        color = CATEGORY_COLORS.get(cat, '#64748B')
        if cat != current:
            cards.append(f'<section class="category-break" data-category-block="{esc(cat)}"><h2><span style="background:{color}"></span>{esc(cat)}</h2></section>')
            current = cat
        contact_rows = []
        if e['display_whatsapp']:
            contact = f'<a href="{esc(e["whatsapp_href"])}" target="_blank" rel="noopener">{esc(e["display_whatsapp"])}</a>' if e['whatsapp_href'] else f'<span>{esc(e["display_whatsapp"])}</span>'
            contact_rows.append(f'<div><strong>WhatsApp</strong>{contact}</div>')
        if e['display_website']:
            contact = f'<a href="{esc(e["website_href"])}" target="_blank" rel="noopener">{esc(e["display_website"])}</a>' if e['website_href'] else f'<span>{esc(e["display_website"])}</span>'
            contact_rows.append(f'<div><strong>Web</strong>{contact}</div>')
        contacts = '<div class="contact-grid">' + ''.join(contact_rows) + '</div>' if contact_rows else '<div class="contact-grid muted">Contact details not listed</div>'
        desc = esc(e['description']).replace('\n', '<br>')
        cards.append(f'''
<article class="card" data-category="{esc(cat)}" data-search="{esc(e['search_blob'])}">
  <div class="card-accent" style="background:{color}"></div>
  <div class="card-top">
    <div class="avatar" style="background:linear-gradient(135deg,{color},#111827)">{esc(e['initials'])}</div>
    <div><h3>{esc(e['business'])}</h3><p class="person">{esc(e['full_name'])}</p></div>
  </div>
  <div class="meta-row"><span>{esc(e['city'])}</span><span>{esc(cat)}</span></div>
  <p class="description">{desc}</p>
  {contacts}
</article>''')

    entries_json = json.dumps(entries, ensure_ascii=False)
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(TITLE)} - {esc(edition)}</title>
<style>
:root {{ --ink:#1f2350; --muted:#667085; --line:#E8DFF0; --card:#fff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:linear-gradient(180deg,#fff7fb 0%,#f7f8ff 100%); color:var(--ink); }}
a {{ color:#2563EB; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
.hero {{ padding:30px 24px 32px; background:radial-gradient(circle at top left, rgba(243,194,255,.55) 0, transparent 28rem), linear-gradient(180deg,#FFF8F2 0%,#FFF 100%); border-bottom:1px solid #F1E6F8; }}
.hero-inner,.shell,.footer {{ max-width:1120px; margin:0 auto; }}
.eyebrow {{ text-transform:uppercase; letter-spacing:.16em; font-size:12px; font-weight:800; color:#8B5CF6; margin-bottom:12px; }}
.cover-card {{ border-radius:28px; overflow:hidden; box-shadow:0 18px 50px rgba(65,23,120,.14); border:1px solid #F1E6F8; background:white; }}
.cover-card img {{ display:block; width:100%; height:auto; }}
.hero-copy {{ padding:20px 4px 0; display:grid; grid-template-columns:1.4fr .9fr; gap:20px; align-items:start; }}
h1 {{ margin:0 0 10px; font-size:clamp(34px,4.5vw,58px); line-height:1; letter-spacing:-.05em; color:#15165F; }}
.hero-copy p {{ max-width:760px; margin:0; color:#44506b; font-size:17px; line-height:1.55; }}
.tagline {{ margin-top:10px; color:#7C3AED; font-weight:800; font-size:18px; }}
.stats {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
.stat {{ background:white; border:1px solid #EEDDF7; border-radius:20px; padding:16px; box-shadow:0 10px 24px rgba(91,33,182,.06); }}
.stat strong {{ display:block; font-size:28px; line-height:1; }} .stat span {{ display:block; margin-top:6px; font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:#7e7a9a; }}
.shell {{ padding:24px 24px 56px; }}
.controls {{ margin-top:18px; background:rgba(255,255,255,.94); border:1px solid rgba(238,221,247,.95); border-radius:24px; padding:18px; box-shadow:0 18px 46px rgba(91,33,182,.08); position:sticky; top:12px; z-index:10; backdrop-filter:blur(10px); }}
.search-row {{ display:grid; grid-template-columns:1fr auto; gap:12px; }}
.search-row input {{ width:100%; border:1px solid var(--line); border-radius:999px; padding:14px 18px; font-size:15px; outline:none; }}
.search-row input:focus {{ border-color:#A855F7; box-shadow:0 0 0 4px rgba(168,85,247,.12); }}
.clear-btn {{ border:none; border-radius:999px; padding:0 18px; background:#1f2350; color:white; font-weight:750; cursor:pointer; }}
.search-help {{ margin:10px 6px 0; color:#667085; font-size:13px; }}
.layout {{ display:grid; grid-template-columns:280px 1fr; gap:22px; margin-top:22px; align-items:start; }}
.sidebar {{ background:white; border:1px solid var(--line); border-radius:24px; padding:20px; box-shadow:0 12px 30px rgba(15,23,42,.07); position:sticky; top:130px; }}
.sidebar h2 {{ margin:0 0 12px; font-size:17px; }} .sidebar p {{ color:var(--muted); font-size:13px; line-height:1.55; margin:0 0 16px; }}
.summary-row {{ display:grid; grid-template-columns:12px 1fr auto; gap:9px; align-items:center; padding:8px 0; border-bottom:1px dashed var(--line); font-size:13px; }} .dot {{ width:11px; height:11px; border-radius:999px; display:block; }}
.city-note {{ margin-top:18px; padding:14px; border-radius:18px; background:#FBF5FF; font-size:13px; color:#475569; line-height:1.45; border:1px solid #F1E6F8; }}
.cards {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }}
.category-break {{ grid-column:1/-1; margin:14px 0 0; }} .category-break h2 {{ margin:0; display:flex; align-items:center; gap:10px; font-size:22px; letter-spacing:-.035em; }} .category-break h2 span {{ width:13px; height:13px; border-radius:50%; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:24px; padding:18px; box-shadow:0 14px 30px rgba(15,23,42,.08); position:relative; overflow:hidden; min-height:250px; }} .card[hidden], .category-break[hidden] {{ display:none!important; }}
.card-accent {{ position:absolute; top:0; left:0; right:0; height:6px; }} .card-top {{ display:grid; grid-template-columns:56px 1fr; gap:13px; align-items:center; }} .avatar {{ width:56px; height:56px; border-radius:18px; color:white; display:grid; place-items:center; font-weight:900; }}
h3 {{ margin:0; font-size:20px; line-height:1.15; letter-spacing:-.035em; }} .person {{ margin:5px 0 0; color:var(--muted); font-size:14px; }}
.meta-row {{ display:flex; flex-wrap:wrap; gap:7px; margin-top:14px; }} .meta-row span {{ display:inline-flex; align-items:center; border:1px solid #E9EAF3; background:#FAFAFF; color:#475569; border-radius:999px; padding:5px 9px; font-size:12px; font-weight:700; }}
.description {{ color:#334155; line-height:1.52; margin:14px 0 16px; font-size:14px; }} .contact-grid {{ display:grid; gap:8px; }} .contact-grid>div {{ display:grid; grid-template-columns:76px 1fr; gap:8px; padding-top:8px; border-top:1px solid #F1F5F9; font-size:13px; align-items:baseline; }} .contact-grid strong {{ color:#64748B; text-transform:uppercase; letter-spacing:.08em; font-size:10px; }}
.footer {{ padding:0 24px 32px; color:#64748B; font-size:12px; line-height:1.55; }} .no-results {{ display:none; background:white; border:1px solid var(--line); border-radius:24px; padding:28px; text-align:center; color:var(--muted); }} .no-results.show {{ display:block; }} .muted {{ color:#94A3B8; font-size:13px; }}
@media (max-width:900px) {{ .hero-copy,.layout {{ grid-template-columns:1fr; }} .stats {{ grid-template-columns:repeat(2,1fr); }} .sidebar,.controls {{ position:static; }} .cards {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header class="hero"><div class="hero-inner"><div class="eyebrow">Updated monthly · {esc(edition)}</div>{cover}<div class="hero-copy"><div><h1>{esc(TITLE)}</h1><p>{esc(DESCRIPTION)}</p><div class="tagline">Find community. Share resources. We’re stronger together.</div></div><div class="stats"><div class="stat"><strong>{len(entries)}</strong><span>Approved listings</span></div><div class="stat"><strong>{len(categories)}</strong><span>Categories</span></div><div class="stat"><strong>{len([c for c,_ in cities if c])}</strong><span>Cities / Areas</span></div><div class="stat"><strong>{esc(updated)}</strong><span>Last update</span></div></div></div></div></header>
<main class="shell"><section class="controls"><div class="search-row"><input id="search" type="search" placeholder="Search descriptions, services, categories, names, or cities..."><button id="clear" class="clear-btn">Clear</button></div><p class="search-help">Search looks across service descriptions, category names, business names, contact names, and city.</p></section><section class="layout"><aside class="sidebar"><h2>Category index</h2><p>Use this as a quick overview, or type a category name into search.</p>{category_summary}<div class="city-note"><strong>Areas represented:</strong><br>{city_list}</div></aside><section><div id="cards" class="cards">{''.join(cards)}</div><div id="noResults" class="no-results">No listings match your current search.</div></section></section></main>
<footer class="footer"><p><strong>Moderation note:</strong> This directory is generated from the linked Google Form responses sheet. Only rows with <strong>Approved = yes</strong> are displayed. The form login/email field is not displayed.</p></footer>
<script>
window.directoryEntries = {entries_json};
const search = document.getElementById('search'), clear = document.getElementById('clear'), cards = [...document.querySelectorAll('.card')], breaks = [...document.querySelectorAll('.category-break')], noResults = document.getElementById('noResults');
function applyFilters() {{ const q = search.value.trim().toLowerCase(); let visible = 0; cards.forEach(card => {{ const show = !q || card.dataset.search.includes(q); card.hidden = !show; if (show) visible++; }}); breaks.forEach(block => {{ const cat = block.dataset.categoryBlock; block.hidden = !cards.some(card => !card.hidden && card.dataset.category === cat); }}); noResults.classList.toggle('show', visible === 0); }}
search.addEventListener('input', applyFilters); clear.addEventListener('click', () => {{ search.value = ''; applyFilters(); search.focus(); }});
</script>
</body>
</html>'''


def main() -> None:
    csv_path = fetch_csv()
    entries = load_entries(csv_path)
    OUTPUT_HTML.write_text(render(entries), encoding='utf-8')
    print(f'Wrote {OUTPUT_HTML}')


if __name__ == '__main__':
    main()
