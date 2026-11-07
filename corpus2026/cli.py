"""One-off 2026 historical backfill and static-site JSON export (no polling)."""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from .core import LEADERS, START, END, in_range, merge_jsonl, read_jsonl
from .sources import Client, AccessDenied, collect_trump, collect_official, collect_telegram_public

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), indent=2) + '\n', encoding='utf-8')


def build_site(data_dir: Path, site_dir: Path) -> dict:
    all_docs = []
    for leader in LEADERS:
        all_docs.extend(read_jsonl(data_dir / f'{leader}.jsonl', leader).values())
    all_docs.sort(key=lambda d: (d['date'], d['id']), reverse=True)
    by_bucket = defaultdict(list)
    for doc in all_docs:
        by_bucket[(doc['leader'], doc['date'][:7])].append(doc)
    dest = site_dir / 'data'
    dest.mkdir(parents=True, exist_ok=True)
    # Remove old month payloads so the index cannot reference stale years.
    for f in dest.glob('*.json'):
        if f.name != 'summary.json':
            f.unlink()
    files = {}
    for (leader, month), rows in sorted(by_bucket.items()):
        path = f'{leader}_{month}.json'
        write_json(dest / path, rows)
        files[f'{leader}:{month}'] = path
    summary = {
        'year': 2026,
        'description': 'Исторический корпус (без realtime); источники различаются по жанру и атрибуции',
        'leaders': LEADERS,
        'total': len(all_docs),
        'words': sum(d.get('word_count', 0) for d in all_docs),
        'by_leader': {leader: sum(d['leader'] == leader for d in all_docs) for leader in LEADERS},
        'by_month': {leader: dict(sorted(Counter(d['date'][:7] for d in all_docs if d['leader'] == leader).items())) for leader in LEADERS},
        'by_source': dict(sorted(Counter(d['source'] for d in all_docs).items())),
        'files': files,
        'coverage_verified': False,
        'status': 'loaded' if all_docs else 'not_loaded',
    }
    report_path = data_dir / 'run_report.json'
    if report_path.exists():
        summary['last_run'] = json.loads(report_path.read_text(encoding='utf-8'))
    write_json(dest / 'summary.json', summary)
    return summary


def run_backfill(args) -> int:
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    today = datetime.now(timezone.utc).date()
    if since < START or since.year != 2026 or until.year != 2026 or until > today or since > until:
        raise SystemExit(f'Historical backfill must stay in 2026 and cannot extend beyond today UTC ({today})')
    if args.max_pages <= 0 or args.max_pages > 400:
        raise SystemExit('max-pages must be in 1..400')
    names = list(LEADERS) if args.source == 'all' else [args.source]
    client = Client(delay=args.delay)
    data_dir = Path(args.data_dir)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'since': str(since),
              'until': str(until), 'mode': 'historical_2026_only', 'sources': {}}
    failures = 0
    for name in names:
        print(f'Start {name} (2026 only)', flush=True)
        try:
            if name == 'trump':
                docs, warnings = collect_trump(client, since, until, max_items=args.max_items)
            else:
                docs, warnings = [], []
                subsource_reports = {}
                for kind, collector in [('official', collect_official), ('telegram', collect_telegram_public)]:
                    try:
                        found, problems = collector(client, name, since, until,
                                                   max_pages=args.max_pages, max_items=args.max_items)
                        docs.extend(found)
                        warnings.extend(f'{kind}: {w}' for w in problems)
                        subsource_reports[kind] = {'status': 'partial' if problems else ('ok' if found else 'empty'),
                                                   'documents': len(found)}
                    except Exception as subexc:
                        warnings.append(f'{kind}: {type(subexc).__name__}: {subexc}')
                        subsource_reports[kind] = {'status': 'error', 'documents': 0,
                                                   'error': str(subexc)}
            before = len(read_jsonl(data_dir / f'{name}.jsonl', name))
            total, changed = merge_jsonl(data_dir / f'{name}.jsonl', name, docs)
            report['sources'][name] = {
                'status': 'partial' if warnings else ('ok' if docs else 'empty'),
                'observed': len(docs), 'stored': total, 'changed': changed,
                'previously_stored': before, 'warnings': warnings[:60],
                'is_full_year_verified': False,
                'subsources': subsource_reports if name != 'trump' else {'truth_social': {'status': 'ok', 'documents': len(docs)}},
            }
            print(f'  {len(docs)} found; stored={total}; changed={changed}; warnings={len(warnings)}')
            if warnings or not docs:
                failures += 1
        except (AccessDenied, Exception) as exc:
            report['sources'][name] = {'status': 'error', 'observed': 0, 'error': f'{type(exc).__name__}: {exc}',
                                       'is_full_year_verified': False}
            print(f'ERROR {name}: {exc}', file=sys.stderr)
            failures += 1
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    write_json(data_dir / 'run_report.json', report)
    summary = build_site(data_dir, Path(args.site_dir))
    print('Site data:', summary['total'], 'documents')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description='2026 historical corpus only — no daily/real-time ingestion')
    sub = parser.add_subparsers(dest='command', required=True)
    back = sub.add_parser('backfill')
    back.add_argument('--source', choices=['all', *LEADERS], default='all')
    back.add_argument('--since', default='2026-01-01')
    back.add_argument('--until', default=datetime.now(timezone.utc).date().isoformat())
    back.add_argument('--max-pages', type=int, default=110)
    back.add_argument('--max-items', type=int, default=0, help='0 = no limit; finite number is a test, not full backfill')
    back.add_argument('--delay', type=float, default=0.4)
    back.add_argument('--data-dir', default=str(ROOT / 'data' / '2026'))
    back.add_argument('--site-dir', default=str(ROOT / 'docs'))
    build = sub.add_parser('build-site')
    build.add_argument('--data-dir', default=str(ROOT / 'data' / '2026'))
    build.add_argument('--site-dir', default=str(ROOT / 'docs'))
    args = parser.parse_args()
    if args.command == 'backfill':
        raise SystemExit(run_backfill(args))
    info = build_site(Path(args.data_dir), Path(args.site_dir))
    print('Built', info['total'], 'documents')

if __name__ == '__main__':
    main()
