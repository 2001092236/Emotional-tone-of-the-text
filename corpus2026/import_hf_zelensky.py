"""One-off non-commercial research audit of a public secondary speech dataset.

Read-only Parquet from Hugging Face. Only metadata, source URLs and topic
statistics leave the GitHub runner. Full source speeches are NEVER committed.
The publisher's card says CC-BY-4.0 but its LICENSE.md says BY-NC-ND-4.0;
we adopt the more restrictive interpretation pending rights clarification.
No login, scraping of president.gov.ua, scheduled polling or GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SOURCE = 'https://huggingface.co/datasets/slava-medvedev/zelensky-speeches'
FILE_URL = SOURCE + '/resolve/main/data/train-00000-of-00001.parquet'
FROM = date(2026, 1, 1)
MAX_DOWNLOAD = 35 * 1024 * 1024
RIGHTS = 'CC BY-NC-ND 4.0 (LICENSE.md и оригинальный сайт; карточка HF противоречит)'


def iso_date(value) -> str | None:
    """HF schema stores UNIX seconds, never a guessed month/day."""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).date().isoformat() if value.tzinfo else value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            return date.fromisoformat(value[:10]).isoformat()
    except (ValueError, OverflowError, OSError, TypeError):
        return None
    return None


def allowed_original_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return (p.scheme == 'https' and p.hostname in {'president.gov.ua', 'www.president.gov.ua'}
                and p.path.startswith(('/news/', '/en/news/')))
    except (TypeError, ValueError):
        return False


def normalize_rows(rows: list[dict], until: date) -> tuple[list[dict], list[dict], Counter]:
    if until.year != 2026 or until < FROM:
        raise ValueError('Only Jan 1—date in 2026 permitted')
    index, texts, excluded, seen = [], [], Counter(), set()
    for row in rows:
        if not isinstance(row, dict):
            excluded['wrong_record'] += 1
            continue
        stamp = iso_date(row.get('date'))
        if not stamp or not FROM.isoformat() <= stamp <= until.isoformat():
            excluded['outside_period_or_undated'] += 1
            continue
        url = (row.get('link') or '').strip()
        if not allowed_original_url(url):
            excluded['invalid_official_url'] += 1
            continue
        lang = str(row.get('lang') or '').strip().lower()
        if lang not in {'uk', 'en'}:
            excluded['unsupported_language'] += 1
            continue
        full = row.get('full_text')
        if not isinstance(full, str) or len(full.strip()) < 100:
            excluded['insufficient_text'] += 1
            continue
        key = (url.split('#')[0], lang)
        if key in seen:
            excluded['duplicate_url_lang'] += 1
            continue
        seen.add(key)
        title = str(row.get('topic') or 'Выступление').strip()[:280]
        document_id = hashlib.sha256((url+'|'+lang).encode()).hexdigest()[:24]
        record = {
            'id': document_id, 'leader': 'zelenskyy',
            'date': stamp, 'url': url, 'title': title,
            'language': lang, 'genre': 'official_speech_or_address',
            'attribution': 'prepared_official_speech_secondary_copy',
            'source': 'hf_zelensky_speeches', 'source_dataset': SOURCE,
            'text_sha256': hashlib.sha256(full.encode('utf-8')).hexdigest(),
            'word_count': len(full.split()),
            'license_note': 'См. общую лицензию и README; полный текст не публикуется здесь',
        }
        index.append(record)
        # The complete original full_text exists in memory ONLY for this job.
        texts.append({**record, 'text': full})
    index.sort(key=lambda x: (x['date'],x['url'],x['language']))
    texts.sort(key=lambda x: (x['date'],x['url'],x['language']))
    return index, texts, excluded


def download_rows(url: str = FILE_URL) -> tuple[list[dict], str]:
    import requests
    import pyarrow.parquet as pq
    with requests.get(url, timeout=(15, 90), stream=True, headers={'User-Agent': 'MGIMO-TextCorpus-Research/0.2 (academic noncommercial metadata audit)'}) as response:
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                raise ValueError('Dataset exceeds configured 35 MB ceiling')
            chunks.append(chunk)
    blob = b''.join(chunks)
    table = pq.read_table(io.BytesIO(blob), columns=['date','link','topic','full_text','lang'])
    return table.to_pylist(), hashlib.sha256(blob).hexdigest()


def topic_summary(rows: list[dict], max_docs: int = 1400, seed: int = 42) -> dict:
    """Research-only ARTM-inspired model of Ukrainian ORIGINAL SPEECHS.

    Never mix official speeches with Telegram posts, translated English texts
    or institutional press releases. Output is non-verbatim topic statistics.
    """
    from .topic_model import stratified_subset, token_matrix, artm_plsa, npmi_top_words, as_topics
    import numpy as np
    original = [r for r in rows if r['language'] == 'uk' and r['word_count'] >= 30]
    if len(original) < 50:
        return {'status':'insufficient_2026_original_speeches','n':len(original),'topics':[]}
    sample = stratified_subset(original, max_docs)
    X, vocabulary = token_matrix(sample, 'uk')
    usable = np.asarray((X > 0).sum(axis=1)).ravel() >= 3
    X = X[usable]
    sample = [d for d, ok in zip(sample, usable) if ok]
    if X.shape[0] < 40 or X.shape[1] < 20:
        return {'status':'insufficient_terms','n':len(sample),'topics':[]}
    theta, phi = artm_plsa(X, topics=min(7,max(2,len(sample)//20)), iterations=30, seed=seed)
    coh = npmi_top_words(X, phi)
    topics, diversity = as_topics(theta,phi,vocabulary,sample,coh,'official_artm')
    return {
        'status': 'experimental', 'method': 'ARTM-inspired regularized PLSA, 30 EM iterations',
        'language': 'uk', 'genre': 'official_speech_or_address',
        'sample_documents': len(sample), 'vocabulary':len(vocabulary),
        'coherence_mean': float(np.mean(coh)), 'diversity_10': diversity,
        'topics': topics,
        'note': 'Full texts processed transiently; this is NOT a personal psychological profile or expert-validated topic set.'
    }


def save_report(out:Path, index_out:Path, model_out:Path, until:date, rows:list[dict], sha:str, viewer_out:Path | None=None) -> dict:
    index, texts, excluded = normalize_rows(rows, until)
    by_month = Counter(d['date'][:7] for d in index)
    by_lang = Counter(d['language'] for d in index)
    model = topic_summary(texts)
    report = {
        'schema_version':1, 'created_at':datetime.now(timezone.utc).isoformat(),
        'dataset':SOURCE, 'parquet_sha256':sha, 'period':['2026-01-01',until.isoformat()],
        'total_2026_speeches':len(index),
        'original_uk':by_lang.get('uk',0), 'official_translation_en':by_lang.get('en',0),
        'earliest':index[0]['date'] if index else None,
        'latest':index[-1]['date'] if index else None,
        'by_month':dict(sorted(by_month.items())), 'exclusions':dict(excluded),
        'rights':RIGHTS,
        'full_text_stored_publicly':False,
        'external_completeness_verified':False,
        'notes':[
            'Secondary HF copy; each record cites the original president.gov.ua URL',
            'Card metadata claims CC BY 4.0 but LICENSE.md and primary site are BY-NC-ND 4.0',
            'Published output contains metadata, hashes and non-verbatim topic statistics, never full text',
            'The dataset may stop earlier than Nov 2026; missing days must not be treated as silence',
            'Prepared speeches are not reliably spontaneous or personally authored text'
        ]
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    index_out.parent.mkdir(parents=True,exist_ok=True)
    model_out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    index_out.write_text(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in index),encoding='utf-8')
    if viewer_out is not None:
        viewer_out.parent.mkdir(parents=True,exist_ok=True)
        viewer_out.write_text(json.dumps(index,ensure_ascii=False,separators=(',', ':'))+'\n',encoding='utf-8')
    model_out.write_text(json.dumps({'year':2026,'source':SOURCE,'rights':RIGHTS, 'original_speeches':model},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main() -> None:
    p=argparse.ArgumentParser(description='One-off 2026 official speeches metadata + research topic model; NO full text republishing')
    p.add_argument('--until',default='2026-11-07')
    p.add_argument('--out',type=Path,default=Path('docs/data/hf_speeches_2026.json'))
    p.add_argument('--index',type=Path,default=Path('data/2026/hf_zelensky_speeches_index.jsonl'))
    p.add_argument('--topics',type=Path,default=Path('docs/data/hf_official_topics.json'))
    p.add_argument('--viewer',type=Path,default=Path('docs/data/hf_speeches_index.json'))
    args=p.parse_args()
    until=date.fromisoformat(args.until)
    rows,sha=download_rows()
    report=save_report(args.out,args.index,args.topics,until,rows,sha,args.viewer)
    print(json.dumps({k:report[k] for k in ('total_2026_speeches','original_uk','official_translation_en','earliest','latest','full_text_stored_publicly')},ensure_ascii=False))

if __name__=='__main__':main()
