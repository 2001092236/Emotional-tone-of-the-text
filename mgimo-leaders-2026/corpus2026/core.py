"""Data model, 2026-only date guards, JSONL storage and HTML extraction."""
from __future__ import annotations
import hashlib
import html as html_lib
import json
import re
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from dateutil.parser import parse as dateparse

START = date(2026, 1, 1)
END = date(2026, 12, 31)
MONTHS = {
    'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4, 'травня': 5,
    'червня': 6, 'липня': 7, 'серпня': 8, 'вересня': 9, 'жовтня': 10,
    'листопада': 11, 'грудня': 12,
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5,
    'июня': 6, 'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10,
    'ноября': 11, 'декабря': 12,
}
LEADERS = {'trump': 'Дональд Трамп', 'putin': 'Владимир Путин', 'zelenskyy': 'Владимир Зеленский'}


def clean(text: str | None) -> str:
    return re.sub(r'[\t \xa0]+', ' ', (text or '')).strip()


def as_text(raw: object) -> str:
    if raw is None:
        return ''
    return clean(BeautifulSoup(str(raw), 'html.parser').get_text(' ', strip=True))


def utc_iso(raw: str | datetime | None) -> str | None:
    if not raw:
        return None
    try:
        dt = dateparse(raw) if isinstance(raw, str) else raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (ValueError, TypeError, OverflowError):
        return None


def in_range(timestamp: str | None, since: date, until: date) -> bool:
    if not timestamp:
        return False
    try:
        day = date.fromisoformat(timestamp[:10])
        return START <= day <= END and since <= day <= until
    except (ValueError, TypeError):
        return False


def extract_date(soup: BeautifulSoup) -> str | None:
    """Prioritize publish metadata over mentions of dates inside document body."""
    for selector, attr in [
        ('meta[property="article:published_time"]', 'content'),
        ('meta[name="datePublished"]', 'content'),
        ('meta[name="pubdate"]', 'content'),
        ('meta[name="date"]', 'content'),
        ('time[datetime]', 'datetime'),
    ]:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            result = utc_iso(tag.get(attr))
            if result:
                return result
    for block in soup.select('script[type="application/ld+json"]'):
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', block.get_text(' ', strip=True))
        if match:
            result = utc_iso(match.group(1))
            if result:
                return result
    # Header and date badges only: avoid a spurious event date in article text.
    areas = soup.select('h1, time, .date, .published, .publication-date, .article-date, .article__date')
    header = ' '.join(e.get_text(' ', strip=True) for e in areas[:8])
    if not header:
        header = soup.get_text(' ', strip=True)[:500]
    match = re.search(r'\b(\d{1,2})\s+([а-яіїєґ]+)\s+(20\d{2})\b', header.casefold())
    if match and match.group(2) in MONTHS:
        try:
            return date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1))).isoformat() + 'T00:00:00+00:00'
        except ValueError:
            return None
    match = re.search(r'\b(20\d{2}-\d\d-\d\d)\b', header)
    return utc_iso(match.group(1)) if match else None


def article_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        root = soup.select_one(selector)
        if not root:
            continue
        for tag in root.select('script, style, aside, nav, footer, .share, .social-links'):
            tag.decompose()
        chunks = [clean(p.get_text(' ', strip=True)) for p in root.select('p, blockquote')]
        chunks = [p for p in chunks if len(p) >= 8]
        if chunks:
            return '\n'.join(chunks)
    return ''


def doc_id(source: str, external: str) -> str:
    return hashlib.sha256((source + ':' + external).encode()).hexdigest()[:24]


def document(*, leader: str, source: str, external: str, published: str, url: str,
             title: str, text: str, genre: str, attribution: str, language: str,
             is_repost: bool = False) -> dict:
    if leader not in LEADERS:
        raise ValueError('Unsupported leader')
    normalized = clean(text)
    return {
        'id': doc_id(source, external), 'leader': leader, 'source': source,
        'date': published[:10], 'published_at': published, 'url': url,
        'title': clean(title), 'text': normalized, 'genre': genre,
        'attribution': attribution, 'language': language, 'is_repost': bool(is_repost),
        'content_hash': hashlib.sha256(normalized.encode()).hexdigest()[:20],
        'word_count': len(normalized.split()),
    }


def read_jsonl(path: Path, leader: str) -> dict[str, dict]:
    output = {}
    if path.exists():
        for row in path.read_text(encoding='utf-8').splitlines():
            if not row.strip():
                continue
            try:
                d = json.loads(row)
                if d.get('leader') == leader and '2026-01-01' <= d.get('date', '') <= '2026-12-31':
                    output[d['id']] = d
            except (json.JSONDecodeError, KeyError):
                continue
    return output


def merge_jsonl(path: Path, leader: str, docs: list[dict]) -> tuple[int, int]:
    existing = read_jsonl(path, leader)
    changed = 0
    for d in docs:
        if d['leader'] != leader or not ('2026-01-01' <= d['date'] <= '2026-12-31'):
            raise ValueError('Refusing out-of-scope document')
        if d['id'] not in existing or existing[d['id']].get('content_hash') != d['content_hash']:
            changed += 1
        existing[d['id']] = d
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_docs = sorted(existing.values(), key=lambda d: (d['date'], d['id']), reverse=True)
    path.write_text(''.join(json.dumps(d, ensure_ascii=False) + '\n' for d in sorted_docs), encoding='utf-8')
    return len(sorted_docs), changed
