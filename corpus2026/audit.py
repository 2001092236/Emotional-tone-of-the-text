"""Reproducible, no-network quality audit of the observed 2026 corpus.

An observed sample is *never* called a complete archive without an external
count / indexed source reference. Gaps in message IDs may include deletions,
media-only posts and unpublished entries, so they are diagnostic only.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .core import LEADERS

ALLOWED_START = date(2026, 1, 1)
SOURCES = {
    'cnn_truth_archive': {'leader': 'trump', 'kind': 'вторичный архив постов', 'role': 'личный аккаунт, авторство не удостоверено'},
    'telegram_news_kremlin': {'leader': 'putin', 'kind': 'сообщения ведомства', 'role': 'пресс-служба, не личная речь'},
    'telegram_v_zelenskiy_official': {'leader': 'zelenskyy', 'kind': 'публикации канала', 'role': 'автор отдельного сообщения не установлен'},
    'kremlin_transcripts': {'leader': 'putin', 'kind': 'официальная стенограмма', 'role': 'реплики требуют выделения спикера'},
    'zelenskyy_speeches': {'leader': 'zelenskyy', 'kind': 'официальные речи', 'role': 'подготовленный текст выступления'},
}


def _month_keys(start: date, end: date) -> list[str]:
    result = []
    m = start
    while (m.year, m.month) <= (end.year, end.month):
        result.append(m.strftime('%Y-%m'))
        m = date(m.year + int(m.month == 12), m.month % 12 + 1, 1)
    return result


def _largest_gap(dates: set[date], start: date, end: date) -> dict:
    """Largest consecutive interval without observed records (not evidence of absence)."""
    sequence = [start - timedelta(days=1), *sorted(d for d in dates if start <= d <= end), end + timedelta(days=1)]
    largest = (0, None, None)
    for prev, nxt in zip(sequence, sequence[1:]):
        n = (nxt - prev).days - 1
        if n > largest[0]:
            largest = (n, prev + timedelta(days=1), nxt - timedelta(days=1))
    return {'days': largest[0], 'start': largest[1].isoformat() if largest[1] else None,
            'end': largest[2].isoformat() if largest[2] else None}


def audit_files(data_dir: Path, *, end: date, out: Path | None = None) -> dict:
    if not ALLOWED_START <= end <= date(2026, 12, 31):
        raise ValueError('Дата аудита должна находиться внутри 2026 года')
    checks = Counter()
    source_rows = defaultdict(list)
    ids = set()
    hashes = Counter()
    invalid_examples = []
    report_path = data_dir / 'run_report.json'
    historical_report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    extension_path = data_dir / 'telegram_extend_report.json'
    extension_report = json.loads(extension_path.read_text(encoding='utf-8')) if extension_path.exists() else None

    for leader in LEADERS:
        filename = data_dir / f'{leader}.jsonl'
        if not filename.exists():
            checks[f'missing_file_{leader}'] += 1
            continue
        for line_number, line in enumerate(filename.read_text(encoding='utf-8').splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                checks['invalid_json'] += 1
                invalid_examples.append(f'{filename.name}:{line_number}: invalid JSON')
                continue
            if not isinstance(row, dict):
                checks['invalid_record_type'] += 1
                continue
            try:
                day = date.fromisoformat(str(row.get('date', '')))
            except ValueError:
                checks['invalid_date'] += 1
                invalid_examples.append(f'{filename.name}:{line_number}: invalid date')
                continue
            if day < ALLOWED_START or day > end:
                checks['out_of_period'] += 1
                invalid_examples.append(f'{filename.name}:{line_number}: {day.isoformat()}')
                continue
            rid = row.get('id')
            if not rid:
                checks['missing_id'] += 1
                continue
            if rid in ids:
                checks['duplicate_id'] += 1
                continue
            ids.add(rid)
            if row.get('leader') != leader:
                checks['wrong_leader'] += 1
                continue
            if not row.get('url') or urlparse(str(row['url'])).scheme not in ('http', 'https'):
                checks['missing_or_invalid_url'] += 1
            if not isinstance(row.get('text'), str) or len(row.get('text', '').strip()) < 2:
                checks['missing_text'] += 1
            if not row.get('attribution'):
                checks['missing_attribution'] += 1
            source = row.get('source', 'missing_source')
            h = str(row.get('content_hash') or '')
            if h:
                hashes[h] += 1
            source_rows[source].append(row)
    all_rows = [r for rows in source_rows.values() for r in rows]
    months = _month_keys(ALLOWED_START, end)
    results = {}
    for source, meta in SOURCES.items():
        rows = source_rows.get(source, [])
        dated = [date.fromisoformat(r['date']) for r in rows]
        dates = set(dated)
        count = Counter(r['date'][:7] for r in rows)
        source_report = (historical_report.get('sources') or {}).get(meta['leader'], {})
        subkey = 'telegram' if source.startswith('telegram_') else 'truth_social' if source.startswith('cnn_') else 'official'
        source_warning = (source_report.get('subsources') or {}).get(subkey, {})
        # In the original historical run, statuses represent ingestion status,
        # NOT an independent comparison against all source publications.
        numeric_ids = []
        for row in rows:
            if source.startswith('telegram_'):
                try:
                    numeric_ids.append(int(row.get('url', '').rstrip('/').rsplit('/', 1)[-1]))
                except ValueError:
                    pass
        stats = {
            'leader': meta['leader'], 'kind': meta['kind'], 'attribution': meta['role'],
            'observed': len(rows), 'unique_days': len(dates),
            'first_date': min(dates).isoformat() if dates else None,
            'last_date': max(dates).isoformat() if dates else None,
            'by_month': {m: count[m] for m in months},
            'empty_months': [m for m in months if count[m] == 0],
            'largest_unobserved_interval': _largest_gap(dates, ALLOWED_START, end),
            'median_words': round(sorted([int(r.get('word_count') or 0) for r in rows])[len(rows)//2], 1) if rows else None,
            'ingestion_status_initial': source_warning.get('status', 'не проверялся'),
            'external_completeness_verified': False,
        }
        if numeric_ids:
            lo, hi = min(numeric_ids), max(numeric_ids)
            stats['telegram_ids'] = {
                'min': lo, 'max': hi, 'unique_observed': len(set(numeric_ids)),
                'possible_identifier_span': hi - lo + 1,
                'note': 'Пропущенные номера НЕ равны недостающим текстам: среди них могли быть удалённые или мультимедийные сообщения.',
            }
        results[source] = stats
    total = len(all_rows)
    leaders = {key: sum(row.get('leader') == key for row in all_rows) for key in LEADERS}
    summary = {
        'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'window': {'since': '2026-01-01', 'until': end.isoformat()},
        'source_of_truth': 'data/2026/*.jsonl (исходные записи)',
        'total_observed': total, 'leaders': leaders,
        'source_count': {s: len(v) for s, v in sorted(source_rows.items())},
        'duplicate_content_hash_count': sum(n - 1 for n in hashes.values() if n > 1),
        'checks': dict(checks), 'invalid_examples': invalid_examples[:20],
        'sources': results,
        'completeness_verified': False,
        'not_complete_reason': 'Ни для одного канала не получен независимый источник полного числа публикаций и подтверждение доступности всех дней.',
        'extension': extension_report,
        'methodology': [
            'Ненайденные документы не равны отсутствующим высказываниям.',
            'Пустой месяц и длинный интервал без документов являются сигналами для проверки, а не оценкой активности.',
            'Посты пресс-службы нельзя интерпретировать как личную речь политика.',
            'Разрывы чисел Telegram не измеряют полноту из-за медиа, удалений и других типов сообщений.',
        ],
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description='Офлайн-аудит наблюдаемого корпуса за 2026 год')
    p.add_argument('--data-dir', type=Path, default=Path('data/2026'))
    p.add_argument('--until', default='2026-11-07')
    p.add_argument('--out', type=Path, default=Path('docs/data/audit.json'))
    args = p.parse_args()
    result = audit_files(args.data_dir, end=date.fromisoformat(args.until), out=args.out)
    print(json.dumps({'total': result['total_observed'], 'leaders': result['leaders'],
                      'checks': result['checks'],
                      'sources': {s: {'n': v['observed'], 'empty_months': v['empty_months'],
                                      'max_gap': v['largest_unobserved_interval']['days']}
                                  for s,v in result['sources'].items()}}, ensure_ascii=False, indent=2))
    if any(result['checks'].get(s) for s in ('invalid_json', 'out_of_period', 'duplicate_id', 'wrong_leader')):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
