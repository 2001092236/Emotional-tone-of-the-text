import json
from unittest.mock import Mock
from corpus2026.commoncrawl_probe import parse_lines,valid_capture,inspect

def test_keep_only_trusted_transcripts():
    good={'url':'https://www.kremlin.ru/events/president/transcripts/123456','status':'200',
          'timestamp':'20261010000000','filename':'crawl-data/x.gz','offset':'100','length':'300'}
    bad={'url':'https://evil.example/events/president/transcripts/123456','status':'200'}
    body='\n'.join([json.dumps(good),json.dumps(bad),'junk'])
    assert len(parse_lines(body))==1
    assert valid_capture(good) and not valid_capture(bad)

def test_http_404_not_considered_evidence_of_silence():
    conn=Mock();conn.get.return_value=Mock(status_code=404)
    d=inspect(conn,('CC-MAIN-2026-43',),('kremlin.ru/events/president/transcripts/*',))
    assert d['number_of_indexed_matching_captures']==0
    assert d['results'][0]['status']=='no_capture'
    assert 'not total' in d['disclaimers'][-1]
