"""Однократная проверка корпуса официальных речей Путина за 2026 год.

Проверяются только общедоступные выгрузки Hugging Face Dataset Server.
Все тексты анализируются только внутри процесса; в публичный GitHub
записываются метаданные, хеши и сведения о покрытии, но не полные тексты.
Нет обхода ограничений, real-time загрузки или постоянного хранилища.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import requests

DATASET = 'laylaylo/global-leaders-discourses'
MANIFEST = f'https://datasets-server.huggingface.co/parquet?dataset={DATASET}'
START, END = date(2026, 1, 1), date(2026, 11, 7)
MAX_BYTES = 100_000_000


def index_files(manifest: dict) -> list[dict]:
    """Выбираем только отдельный российский конфиг, никогда all=66k строк."""
    entries = manifest.get('parquet_files', [])
    if not isinstance(entries, list):
        return []
    matches = []
    for f in entries:
        config = str(f.get('config','')).casefold().replace('_','-')
        if config not in ('russia','russian-federation','rus','ru'):
            continue
        if f.get('split') not in ('train',None):
            continue
        url=f.get('url','')
        if not (isinstance(url,str) and url.startswith('https://huggingface.co/')):
            continue
        matches.append(f)
    return matches


def canonical_date(value: object) -> str | None:
    m = re.match(r'^(20\d\d-\d\d-\d\d)', str(value or ''))
    if not m:
        return None
    try:
        d = date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return d.isoformat() if START <= d <= END else None


def as_record(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    speaker = str(raw.get('speaker_name') or '').casefold().strip()
    if not any(s in speaker for s in ('vladimir putin', 'владимир путин')):
        return None
    when=canonical_date(raw.get('speech_date'))
    if when is None:
        return None
    lang=str(raw.get('language_iso') or '').casefold().strip()
    if lang not in ('ru','rus'):
        return None
    url=str(raw.get('source_url') or '').strip()
    host=urlparse(url).hostname or ''
    if host != 'kremlin.ru' and not host.endswith('.kremlin.ru'):
        return None
    speech=str(raw.get('speech_text') or '').strip()
    if len(speech.split()) < 40:
        return None
    title=str(raw.get('speech_title') or '')[:320]
    identifier=str(raw.get('speech_id') or '')
    text_hash=hashlib.sha256(speech.encode('utf-8')).hexdigest()
    return {'id':hashlib.sha256((identifier+url+lang).encode()).hexdigest()[:24],
            'date':when,'title':title,'speaker':'Владимир Путин','language':'ru',
            'source_url':url,'source_dataset':DATASET,'word_count':len(speech.split()),
            'text_sha256':text_hash,'attribution':'secondary_academic_copy',
            'full_text_in_public_index':False}


def report(records: list[dict], files: list[dict], *, manifest_sha: str,
           errors: list[str] | None=None) -> dict:
    records=sorted(records,key=lambda x:(x['date'],x['id']))
    dates=[r['date'] for r in records]
    unique={r['id']:r for r in records}
    return {'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),
            'dataset':DATASET,'year':2026,'period':[str(START),str(END)],
            'source_type':'third_party_research_aggregation',
            'public_full_text':False,'source_license_claim':'CC BY 4.0 (dataset card); verify original material rights independently',
            'manifest_sha256':manifest_sha,'russia_parquet_parts':[{'filename':x.get('filename'),'size':x.get('size')} for x in files],
            'matching_russian_putin_speeches':len(unique),
            'earliest':min(dates) if dates else None,'latest':max(dates) if dates else None,
            'months':dict(sorted(Counter(d[:7] for d in dates).items())),
            'status':('candidate_2026_records_found' if unique else 'probe_incomplete_or_failed' if errors else 'no_eligible_2026_records_confirmed'),
            'errors':errors or [],
            'limitations':[
               'Первоначальный год выхода датасета не гарантирует наличия выступлений за 2026 год',
               'Это вторичный архив: требуется сверка даты, первичного URL и атрибуции с оригиналом',
               'Неполные и смешанные стенограммы не должны приниматься за личную речь без проверки',
               'Число записей не является числом всех существующих речей 2026 года',
               'Полные тексты не копируются в открытый GitHub'
            ]}


def run(out: Path, index: Path, *, texts_out: Path | None = None, request: requests.Session | None = None) -> dict:
    import pyarrow.parquet as pq
    session=request or requests.Session()
    response=session.get(MANIFEST,timeout=(12,35))
    response.raise_for_status()
    manifest=response.json()
    files=index_files(manifest)
    errors=[]; rows=[]; original_by_id={}
    if not files:
        errors.append('Отдельный российский Parquet-конфиг не обнаружен; большой общий корпус не скачивался')
    with TemporaryDirectory() as temp:
        for i,part in enumerate(files):
            size=int(part.get('size') or 0)
            if size and size>MAX_BYTES:
                errors.append(f'Parquet {i}: превышает лимит размера {MAX_BYTES}')
                continue
            location=Path(temp)/f'{i}.parquet'
            try:
                stream=session.get(part['url'],timeout=(15,90),stream=True)
                stream.raise_for_status()
                total=0
                with location.open('wb') as handle:
                    for chunk in stream.iter_content(1024*1024):
                        total+=len(chunk)
                        if total>MAX_BYTES:
                            raise ValueError('Ограничение размера выгрузки')
                        handle.write(chunk)
                # Only requested fields, no full unneeded dataset columns.
                table=pq.read_table(location,columns=['speaker_name','speech_date','language_iso','speech_title','speech_text','source_url','speech_id'])
                for row in table.to_pylist():
                    item=as_record(row)
                    if item is not None:
                        rows.append(item)
                        original_by_id[item['id']]=str(row.get('speech_text') or '').strip()
            except (requests.RequestException,ValueError,KeyError,OSError,Exception) as exc:
                errors.append(f'Parquet {i}: {type(exc).__name__}: {str(exc)[:230]}')
    canonical={r['id']:r for r in rows}
    items=sorted(canonical.values(),key=lambda r:(r['date'],r['id']),reverse=True)
    m=report(items,files,manifest_sha=hashlib.sha256(response.content).hexdigest(),errors=errors)
    if texts_out is not None and items:
        # Original Kremlin material expressly permits reproduction with attribution:
        # https://kremlin.ru/about/copyrights
        # The research HF dataset is labelled CC BY 4.0; source URLs retained.
        material=[{**item,'text':original_by_id[item['id']],
             'provenance_warning':'Вторичная научная копия: сверка с оригиналом не выполнена',
             'original_rights':'https://kremlin.ru/about/copyrights'} for item in items]
        texts_out.parent.mkdir(parents=True,exist_ok=True)
        texts_out.write_text(json.dumps(material,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        m['public_full_text']=True
        m['public_text_records']=len(material)
        m['reproduction_basis']='Первичный kremlin.ru/about/copyrights разрешает перепечатку с обязательной ссылкой на источник; HF cc-by-4.0, атрибуция обязательна'
    else:
        m['public_text_records']=0
    out.parent.mkdir(parents=True,exist_ok=True)
    index.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    index.write_text(json.dumps(items,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return m


def main() -> None:
    p=argparse.ArgumentParser(description='2026 Путин, только метаданные исследований Hugging Face')
    p.add_argument('--out',type=Path,default=Path('docs/data/hf_putin_probe.json'))
    p.add_argument('--index',type=Path,default=Path('docs/data/hf_putin_speeches_index.json'))
    p.add_argument('--public-texts',type=Path,default=None,help='Сохранять тексты только при подтверждённых правах на перепечатку; с URL оригинала')
    args=p.parse_args()
    try:
        r=run(args.out,args.index,texts_out=args.public_texts)
        print(json.dumps({k:r[k] for k in ['matching_russian_putin_speeches','status','errors']},ensure_ascii=False))
    except requests.RequestException as exc:
        # Fail explicitly, don't save fabricated zeros.
        raise SystemExit(f'Cannot check Hugging Face Parquet metadata: {exc}') from exc

if __name__=='__main__':main()
