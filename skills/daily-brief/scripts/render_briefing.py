#!/usr/bin/env python3
"""Render a daily-brief/v1 spec to self-contained HTML, print/phone PDFs, and a flashcard.
PDF mode needs Chrome/Chromium/Edge plus Poppler tools on PATH. --html-only needs Python 3.10+.
All fonts are bundled. No connected accounts or remote font services are called by this renderer.
"""
import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

SKILL = Path(__file__).resolve().parents[1]
CSS = SKILL / 'assets' / 'briefing.css'
LAYOUT_JS = SKILL / 'assets' / 'layout.js'
STATUS_WORDS = {'confirmed': '', 'planned': 'planned', 'suggested': 'suggested', 'usual': 'usual', 'unconfirmed': 'not confirmed', 'open': ''}
RELATIVE = re.compile(r'\b(today|tomorrow|tonight|yesterday)\b', re.I)
EMPTY_FIELDS = re.compile(r'none recorded|nothing recorded|\bOwner:|\bDeadline:', re.I)
PHONE_PAGE = (4.5, 9.25)
PHONE_CAL_HEIGHT = 640
MIN_FONT_PX = 11.9
SEP = ' · '
ALLOWED_FONTS = ('SourceSerif', 'SourceSans')


def font_css():
    fonts = [('Source Serif 4', 'normal', 'SourceSerif4-Roman.woff2'),
             ('Source Serif 4', 'italic', 'SourceSerif4-Italic.woff2'),
             ('Source Sans 3', 'normal', 'SourceSans3-Upright.woff2')]
    output = []
    for family, style, name in fonts:
        encoded = base64.b64encode((SKILL / 'assets' / 'fonts' / name).read_bytes()).decode('ascii')
        output.append(f"@font-face{{font-family:'{family}';font-style:{style};font-weight:200 900;font-display:block;src:url(data:font/woff2;base64,{encoded}) format('woff2');}}")
    return '\n'.join(output)


class SpecError(Exception):
    pass


def typo(s):
    s = str(s)
    if '--' in s:
        raise SpecError(f'double hyphen in text: {s!r}')
    s = s.replace('\u2248', 'about ')
    s = re.sub(r"(\w)'(\w)", '\\1\u2019\\2', s)
    return re.sub(r"(\w)'", '\\1\u2019', s)


def e(s):
    return html.escape(typo(s), quote=True)


def mins(t):
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', str(t))
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59 or (int(m.group(1)) == 24 and int(m.group(2)) != 0):
        raise SpecError(f'bad time {t!r}; use HH:MM 24-hour')
    return int(m.group(1)) * 60 + int(m.group(2))


def clock(m, suffix=True):
    hh, mm = divmod(m, 60)
    h12 = hh % 12 or 12
    ap = 'am' if hh % 24 < 12 else 'pm'
    return f'{h12}:{mm:02d}' + (f' {ap}' if suffix else '')


def time_text(x, calendar=False):
    """12-hour time text with 'about' for estimates. Calendar text drops am/pm; the hour lines carry it."""
    if x.get('time_text'):
        return x['time_text']
    if not x.get('start'):
        return ''
    s = mins(x['start'])
    a = ('about ' if x.get('start_est') else '')
    if not x.get('end'):
        t = a + clock(s, not calendar)
        return t[0].upper() + t[1:] if t.startswith('about') and not calendar else t
    en = mins(x['end'])
    same = (s < 720) == (en < 720)
    b = ('about ' if x.get('end_est') else '')
    if calendar:
        return f'{a}{clock(s, False)}\u2013{b}{clock(en, False)}'
    t = f'{a}{clock(s, not same)}\u2013{b}{clock(en)}'
    return t[0].upper() + t[1:] if t.startswith('about') else t


def need(obj, key, where):
    if obj.get(key) in (None, '', []):
        raise SpecError(f'{where}: missing {key}')
    return obj[key]


def walk_strings(v, path='spec'):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk_strings(x, f'{path}[{i}]')
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from walk_strings(x, f'{path}.{k}')


def validate(spec):
    for k in ('schema', 'run_id', 'target_date', 'timezone', 'status', 'agenda', 'flashcard'):
        need(spec, k, 'spec')
    if spec['schema'] != 'daily-brief/v1':
        raise SpecError('unsupported report schema')
    ZoneInfo(spec['timezone'])
    if spec['status'] not in ('draft', 'final'):
        raise SpecError('status must be draft or final')
    dt.date.fromisoformat(spec['target_date'])
    mains = [x for x in spec['agenda'] if x.get('main')]
    if len(mains) != 1:
        raise SpecError('agenda: mark exactly one item with main: true')
    for i, x in enumerate(spec['agenda']):
        w = f'agenda[{i}]'
        need(x, 'title', w)
        if x.get('status', 'confirmed') not in STATUS_WORDS:
            raise SpecError(f'{w}.status must be one of {sorted(STATUS_WORDS)}')
        if not x.get('start') and not x.get('time_text'):
            raise SpecError(f'{w}: give start or time_text')
        for k in ('start', 'end'):
            if x.get(k):
                mins(x[k])
        if x.get('start') and x.get('end') and mins(x['end']) <= mins(x['start']):
            raise SpecError(f'{w}: end must be after start')
        if x.get('start') and mins(x['start']) >= 1440:
            raise SpecError(f'{w}: start must be before midnight')
        c = x.get('calendar')
        if c:
            if not x.get('start'):
                raise SpecError(f'{w}: a calendar block needs start')
            if c.get('lane') not in ('me', 'family'):
                raise SpecError(f'{w}.calendar.lane must be me or family')
            need(c, 'label', f'{w}.calendar')
    for i, n in enumerate(spec.get('calendar_notes', [])):
        mins(need(n, 'after', f'calendar_notes[{i}]'))
        need(n, 'text', f'calendar_notes[{i}]')
    for i, c in enumerate(spec.get('coming_up', [])):
        dt.date.fromisoformat(need(c, 'date', f'coming_up[{i}]'))
        need(c, 'text', f'coming_up[{i}]')
    for i, s in enumerate(spec.get('sheets', [])):
        need(s, 'title', f'sheets[{i}]')
        for j, p in enumerate(need(s, 'parts', f'sheets[{i}]')):
            if p.get('type') not in ('table', 'list', 'text'):
                raise SpecError(f'sheets[{i}].parts[{j}].type must be table, list, or text')
            if p['type'] == 'table':
                for r in need(p, 'rows', f'sheets[{i}].parts[{j}]'):
                    if len(r) != len(need(p, 'cols', f'sheets[{i}].parts[{j}]')):
                        raise SpecError(f'sheets[{i}].parts[{j}]: row has {len(r)} cells for {len(p["cols"])} columns')
    fc = spec['flashcard']
    need(fc, 'lines', 'flashcard')
    if len(fc['lines']) > 4 or any(len(x) > 50 for x in fc['lines']):
        raise SpecError('flashcard.lines: at most 4 lines, 50 characters or fewer each')
    # Legacy assessments are retained in old specs but are never printed or checked as visible prose.
    for path, s in walk_strings({k: v for k, v in spec.items() if k not in ('assessment', 'record', 'run_id', 'timezone', 'prepared_at', 'schema')}):
        if RELATIVE.search(s):
            raise SpecError(f'{path}: relative day word in {s!r}; write the weekday or date and let the renderer add today or tomorrow')
        if EMPTY_FIELDS.search(s):
            raise SpecError(f'{path}: empty-field phrase in {s!r}; leave the field out or write a natural sentence')
        typo(s)


# ---------- relative dates ----------
def rel_day(d, prep_date):
    delta = (d - prep_date).days
    long = f'{d.strftime("%A")} {d.day} {d.strftime("%B")}'
    if delta == 0:
        return f'Today, {long}'
    if delta == 1:
        return f'Tomorrow, {long}'
    return long


def short_rel(d, prep_date):
    delta = (d - prep_date).days
    base = f'{d.strftime("%a")} {d.day} {d.strftime("%b")}'
    return {0: 'Today', 1: 'Tomorrow'}.get(delta, base) + ('' if delta not in (0, 1) else f' ({base})')


# ---------- memo ----------
def memo_html(spec, prep, prep_date, sheet_refs):
    d = dt.date.fromisoformat(spec['target_date'])
    delta = (d - prep_date).days
    kicker = {0: 'Today\u2019s brief', 1: 'Tomorrow\u2019s brief'}.get(delta, 'Daily brief')
    prepared = f'Prepared {prep.strftime("%A")} {prep.day} {prep.strftime("%B")} at {clock(prep.hour * 60 + prep.minute)}'
    if spec['status'] == 'draft':
        prepared += SEP + 'draft'
    warn = f'<div class="warn"><b>Note:</b> {e(spec["source_warning"])}</div>' if spec.get('source_warning') else ''
    head = (f'<div class="mhead"><div class="kicker">{kicker}</div><h1>{d.strftime("%A")} {d.day} {d.strftime("%B %Y")}</h1>'
            f'<div class="prep">{prepared}</div>{warn}</div>')
    parts = [f'<section class="s-memo">{head}</section>']

    rows = []
    for x in spec['agenda']:
        if x.get('calendar_only'):
            continue
        st = x.get('status', 'confirmed')
        word = STATUS_WORDS[st]
        extras = [w for w in (word, x.get('length')) if w]
        stx = f'<span class="st">{e(", ".join(extras))}</span>' if extras and st != 'open' else ''
        who = f' <span class="who">{e(x["who"])}</span>' if x.get('who') else ''
        lead = '<span class="lead">Main outcome</span>' if x.get('main') else ''
        body = f'{lead}<span class="ti">{e(x["title"])}</span>{stx}{who}'
        if x.get('detail'):
            body += f'<span class="dt">{e(x["detail"])}</span>'
        if x.get('deadline'):
            body += f'<span class="dl">{e(x["deadline"])}</span>'
        cls = ' class="main"' if x.get('main') else (' class="open"' if st == 'open' else '')
        rows.append(f'<tr{cls}><td class="t">{e(time_text(x))}</td><td>{body}</td></tr>')
    parts.append(f'<section class="s-memo"><h2>Agenda</h2><table class="agenda split">{"".join(rows)}</table></section>')

    if spec.get('decisions'):
        items = []
        for x in spec['decisions']:
            by = f'<span class="by">{e(x["by"])}</span>' if x.get('by') else ''
            items.append(f'<li>{e(x["text"])}{by}</li>')
        items = ''.join(items)
        parts.append(f'<section class="s-memo"><h2>Decisions needed</h2><ul class="plain split">{items}</ul></section>')
    if spec.get('coming_up'):
        rows = ''.join(f'<tr><td class="d">{e(short_rel(dt.date.fromisoformat(c["date"]), prep_date))}</td><td>{e(c["text"])}</td></tr>'
                       for c in spec['coming_up'])
        parts.append(f'<section class="s-memo"><h2>Prepare now</h2><table class="cu split">{rows}</table></section>')
    refs = ['Calendar: <span data-refto="cal">next page</span>'] + [
        f'{e(t)}: <span data-refto="sheet-{i}">later page</span>' for i, t in sheet_refs]
    refs.append('Flashcard and morning check: separate file')
    parts.append(f'<section class="s-memo"><div class="mfoot">{SEP.join(refs)}.</div></section>')
    return ''.join(parts)


def calendar_data(spec):
    blocks = []
    for x in spec['agenda']:
        c = x.get('calendar')
        if not c:
            continue
        blocks.append({'lane': c['lane'], 'start': x['start'], 'end': x.get('end'),
                       'label': e(c['label']), 'note': e(c['note']) if c.get('note') else '', 'main': bool(x.get('main')),
                       'time': e(time_text(x, calendar=True)), 'start_text': e(('about ' if x.get('start_est') else '') + clock(mins(x['start']), False))})
    return blocks


def calendar_html(spec, blocks):
    d = dt.date.fromisoformat(spec['target_date'])
    starts = [mins(b['start']) for b in blocks] + [mins(n['after']) for n in spec.get('calendar_notes', [])]
    ends = [mins(b['end']) for b in blocks if b.get('end')] + [mins(n['after']) + 60 for n in spec.get('calendar_notes', [])]
    h0 = max(0, min(starts) // 60) if starts else 8
    h1 = min(24, -(-max(ends + [s + 15 for s in starts]) // 60)) if starts else 18
    h1 = min(24, max(h1, h0 + 4))

    def hl(hh):
        return 'midnight' if hh in (0, 24) else ('noon' if hh == 12 else f'{hh % 12 or 12} {"am" if hh < 12 else "pm"}')
    rng = f'Shows {hl(h0)} to {hl(h1)}. Nothing is recorded outside these hours.'
    html_ = (f'<section class="s-cal cal" data-break="1" data-ref="cal"><h2>{d.strftime("%A")} {d.day} {d.strftime("%B")}: calendar</h2>'
             f'<div class="range">{rng}</div><div class="cal-head"><span></span><span>You</span><span class="fh">Household, when it affects you</span></div>'
             f'<div class="cal-body" id="cal"></div><div class="cal-over"></div></section>')
    return html_, h0, h1


def sheets_html(spec):
    out, refs = [], []
    for i, s in enumerate(spec.get('sheets', [])):
        parts = []
        for p in s['parts']:
            if p.get('heading'):
                parts.append(f'<h3>{e(p["heading"])}</h3>')
            if p['type'] == 'table':
                head = ''.join(f'<th>{e(c)}</th>' for c in p['cols'])
                rows = ''.join('<tr>' + ''.join(f'<td data-h="{e(h)}">{e(c)}</td>' for h, c in zip(p['cols'], r)) + '</tr>' for r in p['rows'])
                parts.append(f'<table class="grid split"><tr>{head}</tr>{rows}</table>')
            elif p['type'] == 'list':
                parts.append('<ul class="bul">' + ''.join(f'<li>{e(x)}</li>' for x in p['items']) + '</ul>')
            else:
                parts.append(f'<p>{e(p["text"])}</p>')
        intro = f'<p class="intro">{e(s["intro"])}</p>' if s.get('intro') else ''
        out.append(f'<section class="sheet-sup" data-break="1" data-ref="sheet-{i}"><h1 class="sheet-title">{e(s["title"])}</h1>{intro}{"".join(parts)}</section>')
        refs.append((i, s['title']))
    return ''.join(out), refs


def build_html(spec, prep):
    d = dt.date.fromisoformat(spec['target_date'])
    prep_date = prep.date()
    sheets, refs = sheets_html(spec)
    blocks = calendar_data(spec)
    cal, h0, h1 = calendar_html(spec, blocks)
    memo = memo_html(spec, prep, prep_date, refs)
    datestr = f'{d.strftime("%A")} {d.day} {d.strftime("%B %Y")}'
    head = f'<div class="run-head"><span>Daily brief{SEP}{datestr}</span><span>{"Draft" if spec["status"] == "draft" else ""}</span></div>'
    foot = (f'<div class="run-foot"><span>Prepared {prep.strftime("%a")} {prep.day} {prep.strftime("%b")} at {clock(prep.hour * 60 + prep.minute)}'
            f'{SEP}{e(spec["timezone"])}</span><span class="pg">Page 1</span></div>')
    notes = [{'after': n['after'], 'text': e(n['text'])} for n in spec.get('calendar_notes', [])]
    data = {'cal': blocks, 'cal_notes': notes, 'h0': h0, 'h1': h1, 'phone_page': PHONE_PAGE, 'phone_cal_height': PHONE_CAL_HEIGHT}
    data_js = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    tpl = f'<template id="sheet-tpl"><div class="sheet">{head}<div class="body"></div>{foot}</div></template>'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily brief {d.strftime("%a %d %b")}</title>
<style>{font_css()}</style>
<style>{CSS.read_text()}</style>
<script>var DATA={data_js};</script>
<script>{LAYOUT_JS.read_text()}</script>
</head><body>
{tpl}
<div id="flow">{memo}{cal}{sheets}</div>
{foot.replace('class="run-foot"', 'class="run-foot ph-only"').replace('<span class="pg">Page 1</span>', '<span class="pg"></span>')}
</body></html>
'''


def flashcard_html(spec):
    d = dt.date.fromisoformat(spec['target_date'])
    fc = spec['flashcard']
    lines = ''.join(f'<li>{e(x)}</li>' for x in fc['lines'])
    morning = ''.join(f'<li>{e(x)}</li>' for x in fc.get('morning', []))
    evening = ''.join(f'<li>{e(x)}</li>' for x in fc.get('evening', []))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Flashcard {d.strftime("%a %d %b")}</title>
<style>{font_css()}</style>
<style>
@page {{ size: 5in 3in; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background: #FFFFFF; color: #111111; }}
.card {{ width: 5in; height: 3in; padding: .28in .32in; page-break-after: always; font-family: 'Source Sans 3', sans-serif; }}
.card:last-child {{ page-break-after: auto; }}
.h {{ font-size: 13px; color: #555555; border-bottom: .75px solid #BBBBBB; padding-bottom: 3px; margin-bottom: 8px; }}
ol, ul {{ margin: 0; padding-left: 20px; font-family: 'Source Serif 4', serif; font-size: 16px; line-height: 1.4; }}
li {{ margin-bottom: 3px; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; column-gap: .25in; }}
.two ul {{ font-size: 14px; }}
.sub {{ font-size: 13px; font-weight: 600; margin-bottom: 4px; }}
</style></head><body>
<div class="card"><div class="h">{d.strftime("%A")} {d.day} {d.strftime("%B")}: outcomes to copy</div><ol>{lines}</ol></div>
<div class="card"><div class="h">Morning check and evening review</div><div class="two"><div><div class="sub">Morning</div><ul>{morning}</ul></div>
<div><div class="sub">Evening</div><ul>{evening}</ul></div></div></div>
</body></html>
'''


def record_md(spec, prep, name, spec_path):
    rec = spec.get('record', {})
    lines = [f'# Briefing record: {spec["target_date"]}', '',
             f'Prepared {prep.isoformat(timespec="minutes")}. Run `{spec.get("run_id", "")}`. Spec: `{spec_path.name}`.', '',
             '## Sources', '', '| Source | State | Detail |', '| --- | --- | --- |']
    for s in rec.get('sources', []):
        lines.append(f'| {s["name"]} | {"available" if s.get("state") == "ok" else "unavailable"} | {s.get("detail", "")} |')
    lines += ['', '## Basis for estimates', '']
    lines += [f'- {x}' for x in rec.get('estimates', [])]
    return '\n'.join(lines) + '\n'


def prose_text(spec):
    out = [spec.get('source_warning', '')]
    for x in spec['agenda']:
        out += [x['title'], x.get('detail', ''), x.get('deadline', '')]
    out += [x['text'] for x in spec.get('decisions', [])] + [c['text'] for c in spec.get('coming_up', [])]
    out += [n['text'] for n in spec.get('calendar_notes', [])]
    for s in spec.get('sheets', []):
        out.append(s.get('intro', ''))
        for p in s['parts']:
            if p['type'] == 'list':
                out += p['items']
            elif p['type'] == 'text':
                out.append(p['text'])
    fc = spec['flashcard']
    out += fc['lines'] + fc.get('morning', []) + fc.get('evening', [])
    lines = [typo(x).strip() for x in out if x and str(x).strip()]
    return '\n'.join(x if x.endswith(('.', '?', ':')) else x + '.' for x in lines) + '\n'


# ---------- portable browser and checks ----------
def browser_path(explicit=None):
    supplied = explicit or os.environ.get('DAILY_BRIEF_BROWSER')
    if supplied:
        path = Path(supplied).expanduser()
        if path.is_file():
            return str(path)
        raise SpecError('Requested browser executable was not found')
    for name in ('google-chrome', 'chromium', 'chromium-browser', 'chrome', 'msedge'):
        if shutil.which(name):
            return shutil.which(name)
    candidates = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                  Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')]
    for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        if os.environ.get(key):
            candidates += [Path(os.environ[key]) / 'Google/Chrome/Application/chrome.exe',
                           Path(os.environ[key]) / 'Microsoft/Edge/Application/msedge.exe']
    for path in candidates:
        if path.is_file():
            return str(path)
    raise SpecError('Chrome, Chromium, or Edge is required for PDF output; use --browser or --html-only')


def chrome(browser, args, profile):
    command = [browser, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
               '--disable-background-networking', '--disable-sync', '--metrics-recording-only',
               f'--user-data-dir={profile}', '--virtual-time-budget=5000', '--run-all-compositor-stages-before-draw']
    process = subprocess.run(command + args, capture_output=True, text=True, timeout=120)
    if process.returncode:
        raise SpecError('Browser failed; check browser permissions or use --html-only')
    return process.stdout


def attr(source, key):
    found = re.search(rf'data-{key}="([^"]*)"', source)
    return found.group(1) if found else None


def pdf_details(path):
    data = subprocess.run(['pdfinfo', str(path)], capture_output=True, text=True, check=True).stdout
    pages = re.search(r'Pages:\s+(\d+)', data)
    size = re.search(r'Page size:\s+([\d.]+) x ([\d.]+)', data)
    if not pages or not size:
        raise SpecError('Could not inspect PDF geometry')
    return int(pages.group(1)), *map(float, size.groups())


def verify_pdf(path, expected_size, expected_pages=None):
    pages, width, height = pdf_details(path)
    if any(abs(actual - expected) > 2 for actual, expected in zip((width, height), expected_size)):
        raise SpecError('Unexpected PDF page size: ' + path.name)
    if expected_pages is not None and pages != expected_pages:
        raise SpecError('Unexpected PDF page count: ' + path.name)
    text = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True, check=True).stdout
    for page in text.split('\f')[:pages]:
        if len(page.strip()) < 15:
            raise SpecError('Blank PDF page: ' + path.name)
    font_output = subprocess.run(['pdffonts', str(path)], capture_output=True, text=True, check=True).stdout.splitlines()[2:]
    fonts = [re.sub(r'^[A-Z]{6}\+', '', line.split()[0]) for line in font_output if line.split()]
    if not fonts or any(not font.startswith(ALLOWED_FONTS) for font in fonts):
        raise SpecError('Missing or unexpected fonts: ' + path.name)
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--name')
    parser.add_argument('--browser')
    parser.add_argument('--html-only', action='store_true')
    parser.add_argument('--example', action='store_true', help='Allow a marked fictional example in the package')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--max-letter-pages', type=int, default=12)
    args = parser.parse_args(argv)
    try:
        spec = json.loads(args.spec.read_text(encoding='utf-8'))
        validate(spec)
        tz = ZoneInfo(spec['timezone'])
        prep = dt.datetime.fromisoformat(spec['prepared_at']) if spec.get('prepared_at') else dt.datetime.now(tz)
        if prep.tzinfo is None:
            raise SpecError('prepared_at must include a timezone offset')
        prep = prep.astimezone(tz)
        name = args.name or f'{spec["target_date"]}-daily-brief-{dt.datetime.now(tz).strftime("%Y%m%d-%H%M%S")}'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name):
            raise SpecError('Output name must be a plain filename')
        out = args.out_dir.expanduser().resolve()
        public = SKILL.parent.parent if (SKILL.parent.parent / 'bundle.json').exists() else SKILL.parent
        if (out == public or public in out.parents) and not (args.example and spec.get('example') is True):
            raise SpecError('Save private reports outside the package; --example requires an explicitly marked fictional spec')
        browser = None
        if not args.html_only:
            browser = browser_path(args.browser)
            missing = [x for x in ('pdfinfo', 'pdffonts', 'pdftotext', 'pdftoppm') if not shutil.which(x)]
            if missing:
                raise SpecError('Poppler tools missing: ' + ', '.join(missing) + '; use --html-only')
        suffixes = ['.html', '-flashcard.html', '.json', '-record.md']
        if not args.html_only:
            suffixes += ['.pdf', '-phone.pdf', '-flashcard.pdf', '-validation.json']
        if not args.overwrite and any((out / (name + s)).exists() for s in suffixes):
            raise SpecError('Output revision already exists; choose another name or explicitly use --overwrite')
        out.mkdir(parents=True, exist_ok=True)
        html_path = out / (name + '.html')
        html_path.write_text(build_html(spec, prep), encoding='utf-8')
        card_path = out / (name + '-flashcard.html')
        card_path.write_text(flashcard_html(spec), encoding='utf-8')
        spec_path = out / (name + '.json')
        spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        (out / (name + '-record.md')).write_text(record_md(spec, prep, name, spec_path), encoding='utf-8')
        if args.html_only:
            print('HTML created. Open the main HTML normally for print, or append #phone for the phone layout. PDF layout was not verified.')
            return 0
        with tempfile.TemporaryDirectory(prefix='daily-brief-browser-') as profile:
            url = html_path.as_uri()
            letter_dom = chrome(browser, ['--dump-dom', url], profile)
            phone_dom = chrome(browser, ['--dump-dom', url + '#phone'], profile)
            if attr(letter_dom, 'fit') != 'ok':
                raise SpecError('Print page overflow or unfinished layout')
            for label, dom in [('print', letter_dom), ('phone', phone_dom)]:
                minimum = attr(dom, 'minfont')
                if not minimum or float(minimum.split()[0]) < MIN_FONT_PX:
                    raise SpecError('Minimum text size failed: ' + label)
            expected = int(attr(letter_dom, 'sheets') or 0)
            if not 1 <= expected <= args.max_letter_pages:
                raise SpecError('Print page budget exceeded')
            results = []
            for label, target, size, count in [('', url, (612, 792), expected),
                                               ('-phone', url + '#phone', (324, 666), None),
                                               ('-flashcard', card_path.as_uri(), (360, 216), 2)]:
                pdf = out / (name + label + '.pdf')
                chrome(browser, ['--no-pdf-header-footer', f'--print-to-pdf={pdf}', target], profile)
                pages = verify_pdf(pdf, size, count)
                image_dir = out / (name + label + '-pages')
                image_dir.mkdir(exist_ok=True)
                subprocess.run(['pdftoppm', '-scale-to', '1200', '-png', str(pdf), str(image_dir / 'page')], check=True, capture_output=True)
                results.append({'edition': label or 'print', 'pages': pages, 'checked': True})
        (out / (name + '-validation.json')).write_text(json.dumps({'checks_passed': True, 'visual_review_required': True, 'editions': results}, indent=2) + '\n')
        print('All mechanical checks passed. Inspect the generated page images before delivery.')
        return 0
    except (OSError, ValueError, KeyError, SpecError, subprocess.SubprocessError) as error:
        print('Render failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
