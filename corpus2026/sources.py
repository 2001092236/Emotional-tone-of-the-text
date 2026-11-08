"""Historical (2026-only) acquisition from three public, dated primary/secondary archives.

No bypass of login, CAPTCHA, robots.txt, access denial or rate limits.
"""
from __future__ import annotations
import re
import time
from datetime import date
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .core import as_text, article_text, clean, document, extract_date, in_range, utc_iso

USER_AGENT = 'MGIMO-TextCorpus-Research/0.1 (academic source attribution; contact via GitHub repository)'
TRUMP_JSON = 'https://ix.cnn.io/data/truth-social/truth_archive.json'
PUTIN_LIST = 'https://kremlin.ru/events/president/transcripts'
ZELENSKYY_LIST = 'https://www.president.gov.ua/news/speeches'
TG_CHANNELS = {'putin': 'news_kremlin', 'zelenskyy': 'V_Zelenskiy_official'}


class AccessDenied(RuntimeError):
    pass


class Client:
    def __init__(self, *, delay: float = 0.4):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504],
                      allowed_methods=['GET'], respect_retry_after_header=True)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.mount('http://', HTTPAdapter(max_retries=retry))
        self._robot_cache = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        if origin not in self._robot_cache:
            rp = RobotFileParser()
            rp.set_url(origin + '/robots.txt')
            try:
                rsp = self.session.get(origin + '/robots.txt', timeout=12)
                if rsp.status_code in (401, 403, 429):
                    raise AccessDenied(f'robots.txt HTTP {rsp.status_code}: {origin}')
                if rsp.ok:
                    rp.parse(rsp.text.splitlines())
                elif rsp.status_code == 404:
                    rp.parse([])
                else:
                    raise AccessDenied(f'robots.txt unavailable ({rsp.status_code}): {origin}')
            except requests.RequestException as exc:
                raise AccessDenied(f'robots.txt check failed: {origin}: {exc}') from exc
            self._robot_cache[origin] = rp
        return self._robot_cache[origin].can_fetch(USER_AGENT, url)

    def get(self, url: str) -> requests.Response:
        """Follow only HTTPS redirects, checking robots.txt on *every* hop.

        Requests' default allow_redirects=True could silently cross to a host
        whose robots.txt denies automated access, so redirects are explicit.
        """
        current = url
        for _ in range(6):
            if not self.allowed(current):
                raise AccessDenied(f'robots.txt disallows {current}')
            rsp = self.session.get(current, timeout=(12, 35), allow_redirects=False)
            if rsp.status_code in (301, 302, 303, 307, 308):
                location = rsp.headers.get('Location')
                if not location:
                    raise AccessDenied(f'Redirect with no Location: {current}')
                next_url = urljoin(current, location)
                if urlparse(next_url).scheme != 'https':
                    raise AccessDenied(f'Unsafe redirect target: {next_url}')
                current = next_url
                continue
            if rsp.status_code in (401, 403, 429):
                raise AccessDenied(f'HTTP {rsp.status_code}: {current}')
            rsp.raise_for_status()
            time.sleep(self.delay)
            return rsp
        raise AccessDenied(f'Too many redirects: {url}')


def collect_trump(client: Client, since: date, until: date, *, max_items: int = 0) -> tuple[list[dict], list[str]]:
    """CNN published JSON; this is a *secondary archive* of Truth Social posts."""
    raw = client.get(TRUMP_JSON).json()
    if isinstance(raw, dict):
        rows = raw.get('posts', raw.get('data', raw.get('statuses', [])))
    else:
        rows = raw
    if not isinstance(rows, list):
        raise ValueError('Unexpected CNN archive format')
    docs, errors = [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = utc_iso(r.get('created_at') or r.get('created_at_utc') or r.get('date'))
        if not in_range(ts, since, until):
            continue
        msg = as_text(r.get('content') or r.get('content_text') or r.get('text'))
        if not msg:
            continue
        external = str(r.get('id') or r.get('post_id') or '')
        if not external:
            errors.append('Trump archive row without post ID')
            continue
        docs.append(document(leader='trump', source='cnn_truth_archive', external=external,
                             published=ts, url=r.get('url') or f'https://truthsocial.com/@realDonaldTrump/posts/{external}',
                             title='Truth Social · ' + ts[:10], text=msg, genre='social_post',
                             attribution='secondary_archive', language='en',
                             is_repost=bool(r.get('reblog') or r.get('reblogged') or r.get('retruth'))))
        if max_items and len(docs) >= max_items:
            break
    return docs, errors


def listing_urls(html: str, base: str, leader: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    seen = set(); out = []
    for anchor in soup.select('a[href]'):
        absolute = urljoin(base, anchor.get('href', ''))
        url = urlparse(absolute)
        if leader == 'putin':
            valid = re.fullmatch(r'/events/president/transcripts/\d{4,6}', url.path)
        else:
            valid = re.fullmatch(r'/news/[^/]+-\d{3,6}', url.path)
        if valid and absolute not in seen:
            seen.add(absolute); out.append(absolute.split('#')[0].split('?')[0])
    return out


def _putin_speaker_text(soup: BeautifulSoup) -> tuple[str, str]:
    """Conservatively separate Putin's turns where speaker labels are available.
    If none detected, retain the whole transcript with unverified attribution.
    """
    root = soup.select_one('div[itemprop="articleBody"]') or soup.select_one('.read__text') or soup.select_one('article')
    if not root:
        return '', 'missing_text'
    paragraphs = [clean(p.get_text(' ', strip=True)) for p in root.select('p')]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return '', 'missing_text'
    sections, speaker, encountered = [], False, False
    putin_re = re.compile(r'^(?:(?:В\.\s*){1,2}Путин|Владимир\s+(?:Владимирович\s+)?Путин|Путин)\s*:', re.I)
    other_re = re.compile(r'^(?:[А-ЯЁ]\.\s*){1,2}[А-ЯЁ][а-яё]+\s*:|^(?:[А-ЯЁ][а-яё]+\s+){1,3}[А-ЯЁ][а-яё]+\s*:|^(?:Вопрос|Ведущий|Корреспондент|Журналист)\s*:', re.I)
    for p in paragraphs:
        if putin_re.match(p):
            speaker = True; encountered = True
            sections.append(putin_re.sub('', p, count=1).strip())
        elif other_re.match(p):
            speaker = False; encountered = True
        elif speaker:
            sections.append(p)
    if encountered:
        return '\n'.join(s for s in sections if s), 'direct_speech_segment' if sections else 'no_putin_turn'
    return '\n'.join(paragraphs), 'mixed_unverified'


def parse_official_article(html: str, url: str, leader: str) -> dict | None:
    soup = BeautifulSoup(html, 'html.parser')
    ts = extract_date(soup)
    if not ts:
        return None
    h1 = soup.select_one('h1')
    title = clean(h1.get_text(' ', strip=True)) if h1 else ''
    if leader == 'putin':
        body, attribution = _putin_speaker_text(soup)
        genre, language, source = 'speech_or_transcript', 'ru', 'kremlin_transcripts'
    else:
        body = article_text(soup, ('.article_content', '.news__text', '.text', '.article-text', 'article', 'main'))
        attribution = 'official_speech_text'
        genre, language, source = 'speech_or_address', 'uk', 'zelenskyy_speeches'
    if not body or len(body) < 30:
        return None
    return document(leader=leader, source=source, external=urlparse(url).path.rsplit('/', 1)[-1],
                    published=ts, url=url, title=title, text=body, genre=genre,
                    attribution=attribution, language=language)


def collect_official(client: Client, leader: str, since: date, until: date,
                     *, max_pages: int = 110, max_items: int = 0) -> tuple[list[dict], list[str]]:
    if leader not in ('putin', 'zelenskyy'):
        raise ValueError('Unknown official archive')
    base = PUTIN_LIST if leader == 'putin' else ZELENSKYY_LIST
    docs, errors, seen = [], [], set()
    older_pages, empty_pages = 0, 0
    for page in range(1, max_pages + 1):
        list_url = (base if page == 1 else f'{base}/{page}') if leader == 'putin' else f'{base}?page={page}'
        try:
            listing = client.get(list_url).text
        except AccessDenied:
            raise
        except Exception as exc:
            errors.append(f'Index {list_url}: {type(exc).__name__}: {exc}')
            break  # Partial corpus must be reported, not silently declared complete
        urls = [u for u in listing_urls(listing, list_url, leader) if u not in seen]
        if not urls:
            empty_pages += 1
            if empty_pages >= 2:
                break
            continue
        empty_pages = 0
        page_valid_dates = []
        for url in urls:
            seen.add(url)
            try:
                doc = parse_official_article(client.get(url).text, url, leader)
                if not doc:
                    errors.append(f'Unparsed article/date: {url}')
                    continue
                page_valid_dates.append(doc['date'])
                if in_range(doc['published_at'], since, until):
                    docs.append(doc)
                if max_items and len(docs) >= max_items:
                    return docs, errors
            except AccessDenied:
                raise
            except Exception as exc:
                errors.append(f'Article {url}: {type(exc).__name__}: {exc}')
        if page_valid_dates and all(day < since.isoformat() for day in page_valid_dates):
            older_pages += 1
        else:
            older_pages = 0
        if older_pages >= 2:
            break
    return docs, errors


def parse_telegram_preview(html: str, leader: str) -> list[dict]:
    """Parse Telegram public preview pages; never ascribe Kremlin press posts to Putin personally."""
    if leader not in TG_CHANNELS:
        raise ValueError('Unsupported Telegram channel')
    soup = BeautifulSoup(html, 'html.parser')
    channel = TG_CHANNELS[leader]
    records = []
    for message in soup.select('.tgme_widget_message[data-post]'):
        address = message.get('data-post') or ''
        match = re.fullmatch(r'([^/]+)/(\d+)', address)
        if not match or match.group(1).casefold() != channel.casefold():
            continue
        t = message.select_one('a.tgme_widget_message_date time[datetime], time[datetime]')
        timestamp = utc_iso(t.get('datetime')) if t else None
        content = message.select_one('.tgme_widget_message_text')
        body = content.get_text(' ', strip=True) if content else ''
        if timestamp and body.strip():
            records.append(document(
                leader=leader, source='telegram_' + channel.lower(),
                external=match.group(2), published=timestamp,
                url=f'https://t.me/{channel}/{match.group(2)}',
                title=f'Telegram · {timestamp[:10]}', text=body,
                genre='channel_post',
                attribution='institutional_press_channel' if leader == 'putin' else 'leader_channel_unverified_author',
                language='ru' if leader == 'putin' else 'uk'))
    return records


def collect_telegram_public(client: Client, leader: str, since: date, until: date,
                            *, max_pages: int = 110, max_items: int = 0) -> tuple[list[dict], list[str]]:
    """Public no-login preview with ?before=<oldest_message_id>. Completeness never assumed."""
    if leader not in TG_CHANNELS:
        raise ValueError('Unsupported Telegram channel')
    channel = TG_CHANNELS[leader]
    base = f'https://t.me/s/{channel}'
    docs, errors, seen = [], [], set()
    before = None
    old_streak = 0
    for page in range(max_pages):
        url = base + (f'?before={before}' if before is not None else '')
        try:
            html = client.get(url).text
        except AccessDenied:
            raise
        except Exception as exc:
            errors.append(f'Telegram index {url}: {type(exc).__name__}: {exc}')
            break
        parsed = parse_telegram_preview(html, leader)
        message_ids = [int(n) for n in re.findall(
            r'data-post=[\"\']' + re.escape(channel) + r'/(\d+)', html, re.I)]
        if not message_ids:
            errors.append(f'No Telegram message identifiers on {url}; possible blocked or changed preview')
            break
        oldest = min(message_ids)
        if before is not None and oldest >= before:
            errors.append(f'No backward progress in Telegram history at {url}')
            break
        page_dates = []
        for d in parsed:
            page_dates.append(d['date'])
            if not in_range(d['published_at'], since, until) or d['id'] in seen:
                continue
            docs.append(d)
            seen.add(d['id'])
            if max_items and len(docs) >= max_items:
                return docs, errors
        if page_dates and all(day < since.isoformat() for day in page_dates):
            old_streak += 1
        else:
            old_streak = 0
        if old_streak >= 2:
            break
        before = oldest
    else:
        errors.append('Maximum Telegram preview pages reached; archive may be incomplete')
    return docs, errors
