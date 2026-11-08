"""Noncommercial redistribution of unchanged 2026 speech texts (secondary copy).

Maintains original license and explicit primary source attribution. The 'text'
string is copied exactly from HF dataset's full_text, not paraphrased,
truncated, translated or altered. This does not certify that the secondary
copy itself matches the live original site. Data stays separate from the
main social-media corpus.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from .import_hf_zelensky import download_rows, normalize_rows, SOURCE, RIGHTS

LICENSE_URL = 'https://creativecommons.org/licenses/by-nc-nd/4.0/'
SOURCE_CREDIT = 'Офіційне інтернет-представництво Президента України'


def build_release(rows: list[dict], until: date, parquet_sha256: str) -> dict:
    index, docs, exclusions = normalize_rows(rows, until)
    assert len(index) == len(docs)
    public = []
    for row in docs:
        text = row['text']  # Preserve exact string from full_text in HF parquet.
        assert hashlib.sha256(text.encode('utf-8')).hexdigest() == row['text_sha256']
        public.append({
            **row,
            'rights_holder_credit': SOURCE_CREDIT,
            'original_material_license': 'CC BY-NC-ND 4.0',
            'original_material_license_url': LICENSE_URL,
            'unmodified_source_text': True,
            'direct_original_comparison_verified': False,
            'license_notice': (
                'Некоммерческое воспроизведение без редакторских изменений строки full_text из ' + SOURCE
                + '; права сохраняются за правообладателями первоисточника. ' + RIGHTS
            ),
        })
    return {
        'schema_version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'period': ['2026-01-01',until.isoformat()],
        'source': SOURCE,
        'parquet_sha256': parquet_sha256,
        'rights_notice': ('Эти тексты не распространяются под общей лицензией репозитория. '
                         'Использовать неизменённо в некоммерческих целях с атрибуцией и ссылкой. '
                         'Вторичная копия не сверена побуквенно с официальным веб-архивом.'),
        'license_url': LICENSE_URL,
        'total_documents': len(public),
        'counts_by_language': {lang:sum(d['language']==lang for d in public) for lang in ('uk','en')},
        'excluded': dict(exclusions),
        'documents': public,
    }


def main() -> None:
    p = argparse.ArgumentParser(description='Опубликовать только неизменённые CC BY-NC-ND речи за 2026 год')
    p.add_argument('--until',default='2026-11-07')
    p.add_argument('--out',type=Path,default=Path('docs/data/hf_speeches_full_2026.json'))
    args=p.parse_args()
    rows,sha=download_rows()
    out=build_release(rows,date.fromisoformat(args.until),sha)
    if out['total_documents'] == 0:
        raise SystemExit('Нет подходящих текстов за 2026 год; публикация прервана')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(out,ensure_ascii=False,separators=(',', ':'))+'\n',encoding='utf-8')
    print(json.dumps({'published_full_texts':out['total_documents'],
                      'languages':out['counts_by_language'],
                      'license':LICENSE_URL,
                      'not_checked_against_primary':True},ensure_ascii=False))

if __name__=='__main__':
    main()
