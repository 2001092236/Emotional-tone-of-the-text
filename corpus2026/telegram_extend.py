"""One-off, resuming Telegram public-preview backfill strictly within 2026.

Starts from the oldest *already archived* message ID. Resumes in bounded
batches; preserves partial progress and access-denied errors in the report.
No cron, account credentials or CAPTCHA / anti-bot bypass.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .core import merge_jsonl, read_jsonl
from .sources import Client, AccessDenied, TG_CHANNELS, parse_telegram_preview


def resume_public_preview(*, leader: str, data_dir: Path, since: date,
                          until: date, max_pages: int = 320, delay: float = .5,
                          client=None, batch_pages: int = 20) -> dict:
    if leader not in TG_CHANNELS:
        raise ValueError('Supported leaders: putin, zelenskyy')
    if since != date(2026, 1, 1) or until.year != 2026 or since > until:
        raise ValueError('Only 2026 historical date interval is allowed')
    if not 1 <= max_pages <= 400:
        raise ValueError('max_pages must be in 1..400')
    src = 'telegram_' + TG_CHANNELS[leader].lower()
    filename = data_dir / (leader + '.jsonl')
    saved = [d for d in read_jsonl(filename, leader).values() if d.get('source') == src]
    msg_ids = []
    for d in saved:
        match = re.search(r'/(\d+)$', d.get('url', ''))
        if match:
            msg_ids.append(int(match.group(1)))
    if not msg_ids:
        raise ValueError('No existing Telegram message IDs: first run initial backfill')
    before = min(msg_ids)
    initial_before = before
    current = client or Client(delay=delay)
    url_base = 'https://t.me/s/' + TG_CHANNELS[leader]
    inserted, pages, scanned, recent_page_dates, warnings = 0, 0, 0, [], []
    buffer = []
    old_streak = 0
    end_reason = 'max_pages_reached'
    reached_lower_boundary = False

    def checkpoint():
        nonlocal inserted
        if buffer:
            before_total = len(read_jsonl(filename, leader))
            after_total, _ = merge_jsonl(filename, leader, buffer)
            inserted += after_total - before_total
            buffer.clear()

    for _ in range(max_pages):
        url = f'{url_base}?before={before}'
        try:
            html = current.get(url).text
        except (AccessDenied, Exception) as err:
            warnings.append(f'{type(err).__name__}: {str(err)[:300]}')
            end_reason = 'access_error'
            break
        ids = [int(n) for n in re.findall(
            r'data-post=[\"\']' + re.escape(TG_CHANNELS[leader]) + r'/(\d+)', html, re.I)]
        if not ids:
            warnings.append(f'No message IDs in page {url}')
            end_reason = 'empty_or_changed_preview'
            break
        oldest = min(ids)
        if oldest >= before:
            warnings.append(f'History did not move backwards at {url}')
            end_reason = 'pagination_not_progressing'
            break
        before = oldest
        parsed = parse_telegram_preview(html, leader)
        pages += 1
        scanned += len(ids)
        dated = [d['date'] for d in parsed]
        if dated:
            recent_page_dates.append(min(dated))
        for d in parsed:
            if since.isoformat() <= d['date'] <= until.isoformat():
                buffer.append(d)
        if pages % batch_pages == 0:
            checkpoint()
        if dated and max(dated) < since.isoformat():
            old_streak += 1
        else:
            old_streak = 0
        if old_streak >= 2:
            end_reason = 'older_than_2026_reached'
            reached_lower_boundary = True
            break
    checkpoint()
    response = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'leader': leader, 'source': src,
        'window': ['2026-01-01', until.isoformat()],
        'initial_before_message_id': initial_before, 'last_before_message_id': before,
        'pages_fetched': pages, 'message_identifiers_observed': scanned,
        'new_text_documents': inserted, 'total_text_documents': len([d for d in read_jsonl(filename,leader).values() if d.get('source') == src]),
        'oldest_date_on_pages': min(recent_page_dates) if recent_page_dates else None,
        'reached_lower_boundary': reached_lower_boundary,
        'stop_reason': end_reason, 'warnings': warnings,
        'external_completeness_verified': False,
        'note': 'Достижение января и переход в 2025 означает окончание пагинации, но не гарантирует полноту медиа/удалённых сообщений.',
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'telegram_extend_report.json').write_text(json.dumps(response,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return response


def main() -> None:
    p = argparse.ArgumentParser(description='Разовая дозагрузка истории Telegram (только 2026, без расписания)')
    p.add_argument('--leader', choices=sorted(TG_CHANNELS), default='zelenskyy')
    p.add_argument('--data-dir', type=Path, default=Path('data/2026'))
    p.add_argument('--until', default='2026-11-07')
    p.add_argument('--max-pages', type=int, default=320)
    p.add_argument('--delay', type=float, default=.5)
    args = p.parse_args()
    result=resume_public_preview(leader=args.leader,data_dir=args.data_dir,
        since=date(2026,1,1),until=date.fromisoformat(args.until),max_pages=args.max_pages,delay=args.delay)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['stop_reason'] not in ('older_than_2026_reached',):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
