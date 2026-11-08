from datetime import date
import json
from corpus2026.import_hf_zelensky import normalize_rows, allowed_original_url, iso_date, save_report

def test_only_2026_and_trusted_originals():
    sample=[
      {'date':1767225600,'link':'https://www.president.gov.ua/news/speech-11111','topic':'Пряма мова','full_text':'Українська промова. '*30,'lang':'uk'},
      {'date':1767139200,'link':'https://www.president.gov.ua/news/previous-11110','topic':'старе','full_text':'Стара промова '*30,'lang':'uk'},
      {'date':1780344000,'link':'https://www.president.gov.ua/en/news/speech-11112','topic':'English translation','full_text':'English language original site text '*30,'lang':'en'},
      {'date':1767225600,'link':'https://other.example/news/speech-11113','topic':'poison','full_text':'Another speech '*40,'lang':'uk'},
    ]
    index,docs,ex=normalize_rows(sample,date(2026,11,7))
    assert len(index)==2 and len(docs)==2
    assert all(d['date'].startswith('2026-') for d in index)
    assert all('text' not in d and 'full_text' not in d for d in index)
    assert ex['invalid_official_url']==1
    assert ex['outside_period_or_undated']==1
    assert index[0]['text_sha256'] and len(index[0]['text_sha256'])==64
    assert all(d['text'] for d in docs)

def test_url_and_date_rejections():
    assert not allowed_original_url('http://www.president.gov.ua/news/100')
    assert not allowed_original_url('https://president.gov.ua.evil.net/news/100')
    assert iso_date('2026-06-01T12:00:00Z') == '2026-06-01'
    assert iso_date(None) is None

def test_metadata_not_text_saved(tmp_path, monkeypatch):
    import corpus2026.import_hf_zelensky as mod
    monkeypatch.setattr(mod,'topic_summary',lambda rows:{'status':'test_only','n':len(rows),'topics':[]})
    data=[{'date':1767225600,'link':'https://www.president.gov.ua/news/speech-12345','topic':'title','full_text':'SECRET SPEECH '*30,'lang':'uk'}]
    result=save_report(tmp_path/'report.json',tmp_path/'index.jsonl',tmp_path/'topics.json',date(2026,11,7),data,'abc')
    for f in tmp_path.glob('*'):
        assert 'SECRET SPEECH' not in f.read_text()
    assert result['full_text_stored_publicly'] is False
    assert result['total_2026_speeches']==1
