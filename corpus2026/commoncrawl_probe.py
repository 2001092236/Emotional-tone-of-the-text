"""Discover available Common Crawl 2026 captures of Kremlin transcripts.

Only indexed URL metadata; does NOT scrape inaccessible Kremlin site,
retrieve protected content or assume crawl date equals speech date.
This discovery is safe for public archive research and uses no credentials.
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

CRAWLS=('CC-MAIN-2026-25','CC-MAIN-2026-34','CC-MAIN-2026-43')
TARGETS=('kremlin.ru/events/president/transcripts/*','www.kremlin.ru/events/president/transcripts/*')
BASE='https://index.commoncrawl.org/'
URL_PATTERN=re.compile(r'^/events/president/transcripts/\d{4,7}/?$')


def valid_capture(item):
    if not isinstance(item,dict):return False
    u=item.get('url','')
    try:
        p=urlparse(u)
    except (TypeError, ValueError):return False
    return p.hostname in {'kremlin.ru','www.kremlin.ru'} and bool(URL_PATTERN.fullmatch(p.path)) and str(item.get('status',''))=='200'


def parse_lines(text):
    out=[]
    for line in text.splitlines():
        try:
            row=json.loads(line)
        except (ValueError,TypeError):
            continue
        if valid_capture(row):
            out.append({'url':row['url'],'timestamp_crawl':row.get('timestamp'),
                        'filename':row.get('filename'),'offset':row.get('offset'),
                        'length':row.get('length'),'status':200})
    return out


def inspect(session=None, crawls=CRAWLS, targets=TARGETS):
    conn=session or requests.Session()
    results=[]
    for crawl in crawls:
        for target in targets:
            url=BASE+crawl+'-index'
            params={'url':target,'output':'json','filter':'status:200','collapse':'urlkey'}
            try:
                resp=conn.get(url,params=params,timeout=(10,22),headers={'User-Agent':'MGIMO-TextCorpus-Research/0.2 (open-archive research)'})
                if resp.status_code in (403,429):
                    result={'crawl':crawl,'target':target,'status':'access_denied','http_status':resp.status_code,'count':0}
                elif resp.status_code in (404,400):
                    result={'crawl':crawl,'target':target,'status':'no_capture','http_status':resp.status_code,'count':0}
                else:
                    resp.raise_for_status()
                    captures=parse_lines(resp.text)
                    result={'crawl':crawl,'target':target,'status':'found' if captures else 'empty',
                            'count':len(captures),'sample':captures[:15],
                            'note':'Timestamp is crawl date. Speech publication date must be separately read from original WARC.'}
            except requests.RequestException as exc:
                result={'crawl':crawl,'target':target,'status':'request_error','count':0,
                        'error':type(exc).__name__+': '+str(exc)[:220]}
            results.append(result)
    return {'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),
            'year':2026,'kind':'archive_url_probe_only',
            'number_of_indexed_matching_captures':sum(x['count'] for x in results),
            'results':results,
            'license':'Original Kremlin texts CC BY 4.0 with source attribution; Common Crawl index is a separate archive',
            'disclaimers':['No full text imported','Crawl date does not imply 2026 publication date',
                            'Number of indexed captures is not total speeches or independent completeness verification']}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,default=Path('data/2026/cc_kremlin_probe.json'))
    args=p.parse_args()
    report=inspect();args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'found':report['number_of_indexed_matching_captures'],
                      'status':[x['status'] for x in report['results']]},ensure_ascii=False))

if __name__=='__main__':main()
