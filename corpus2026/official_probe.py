"""One-off, allowed-access check of official sources only.

Does not ingest or publish copyrighted/full speech texts. PublicNow is
excluded: its terms forbid automated access without prior express permission.
Tests whether
robots.txt and HTTP allow a read and records only titles and link metadata.
No circumvention of access restrictions, proxies or login challenges.
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from .sources import AccessDenied, Client

CANDIDATES = [
  {'id':'ukraine_original_speeches', 'type':'official', 'country':'Украина',
   'url':'https://president.gov.ua/news/speeches', 'language':'uk', 'expected':'индекс речей'},
  {'id':'ukraine_english_speeches', 'type':'official_translation', 'country':'Украина',
   'url':'https://president.gov.ua/en/news/speeches', 'language':'en', 'expected':'переводной индекс'},
  {'id':'ukraine_speeches_rss', 'type':'official_feed', 'country':'Украина',
   'url':'https://president.gov.ua/rss/news/speeches.rss', 'language':'uk', 'expected':'RSS'},
  {'id':'kremlin_alternate_index', 'type':'official', 'country':'Россия',
   'url':'https://news.kremlin.ru/events/president/transcripts', 'language':'ru', 'expected':'стенограммы'},
  {'id':'kremlin_english_index', 'type':'official_translation', 'country':'Россия',
   'url':'https://en.kremlin.ru/events/president/transcripts', 'language':'en', 'expected':'переводные стенограммы'},
]


def inspect_one(client, candidate: dict) -> dict:
    result={**candidate,'checked_at':datetime.now(timezone.utc).isoformat(),
            'content_reproduction_permitted':None,
            'text_imported':False,
            'note':'Проверка доступности не является разрешением на полную републикацию.'}
    try:
        response=client.get(candidate['url'])
        raw=response.content[:200000]
        soup=BeautifulSoup(raw,'html.parser')
        title=soup.title.get_text(' ',strip=True) if soup.title else ''
        anchors=[a.get('href','') for a in soup.find_all('a',href=True)]
        result.update(status='ok',http_status=response.status_code,
            final_url=response.url,html_title=title[:180],page_has_h1=bool(soup.find('h1')),
            article_link_candidates=sum(1 for a in anchors if re.search(r'/news/[a-zа-яієґ-]+-\d{3,6}',a,re.I)),
            source_marker_present=('kremlin.ru/d/' in raw.decode('utf-8','ignore') if candidate['country']=='Россия' else 'president.gov.ua' in raw.decode('utf-8','ignore')))
    except AccessDenied as exc:
        result.update(status='denied_or_unavailable',error=str(exc)[:380])
    except Exception as exc:
        result.update(status='error',error=f'{type(exc).__name__}: {str(exc)[:300]}')
    return result


def probe(client=None)->dict:
    c=client or Client(delay=.5)
    findings=[inspect_one(c,entry) for entry in CANDIDATES]
    return {'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),
            'kind':'technical_access_and_provenance_probe', 'year':2026,
            'status':'metadata_only',
            'notice':'Результаты не доказывают полноту 2026 года и не разрешают копирование полных текстов из сторонних источников.',
            'candidates':findings}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,default=Path('data/2026/official_source_probe.json'))
    args=p.parse_args()
    result=probe()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'probed':len(result['candidates']),
          'accessible':[x['id'] for x in result['candidates'] if x['status']=='ok'],
          'blocked':[x['id'] for x in result['candidates'] if x['status']!='ok']},ensure_ascii=False))

if __name__=='__main__':
    main()
