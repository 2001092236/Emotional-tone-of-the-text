import json
from datetime import date
from corpus2026.audit import audit_files, _month_keys


def test_audit_does_not_fake_completeness(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    rows = [
        {'id':'a','leader':'zelenskyy','source':'telegram_v_zelenskiy_official',
         'date':'2026-06-01','text':'Виступ із промовою',
         'url':'https://t.me/V_Zelenskiy_official/11000','word_count':3,
         'content_hash':'hash-a','attribution':'leader_channel_unverified_author'},
        {'id':'b','leader':'zelenskyy','source':'telegram_v_zelenskiy_official',
         'date':'2026-06-04','text':'Інша промова',
         'url':'https://t.me/V_Zelenskiy_official/11003','word_count':2,
         'content_hash':'hash-b','attribution':'leader_channel_unverified_author'},
    ]
    (data/'zelenskyy.jsonl').write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
    (data/'putin.jsonl').write_text('')
    (data/'trump.jsonl').write_text('')
    result = audit_files(data,end=date(2026,11,7),out=tmp_path/'audit.json')
    s=result['sources']['telegram_v_zelenskiy_official']
    assert result['total_observed']==2
    assert s['first_date']=='2026-06-01'
    assert s['empty_months'][:4]==['2026-01','2026-02','2026-03','2026-04']
    assert s['telegram_ids']['possible_identifier_span']==4
    assert result['completeness_verified'] is False
    assert (tmp_path/'audit.json').exists()


def test_period_window_and_invalid_entries(tmp_path):
    p=tmp_path/'data';p.mkdir()
    (p/'trump.jsonl').write_text(json.dumps({'id':'o','leader':'trump','date':'2025-12-31'})+'\n')
    r=audit_files(p,end=date(2026,11,7))
    assert r['total_observed']==0
    assert r['checks']['out_of_period']==1
    assert _month_keys(date(2026,10,1),date(2026,12,31))==['2026-10','2026-11','2026-12']
