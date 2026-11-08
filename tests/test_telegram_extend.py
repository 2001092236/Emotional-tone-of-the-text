import json
from datetime import date
from pathlib import Path
from corpus2026.core import document, merge_jsonl
from corpus2026.telegram_extend import resume_public_preview


def html_msg(number, when):
    return f'''<div class="tgme_widget_message" data-post="V_Zelenskiy_official/{number}"><div class="tgme_widget_message_text">Публічне звернення українського президента</div><time datetime="{when}T09:00:00Z"></time></div>'''


def test_resume_does_not_duplicate_and_records_boundary(tmp_path):
    data=tmp_path/'data';data.mkdir()
    newest=document(leader='zelenskyy',source='telegram_v_zelenskiy_official',external='12000',published='2026-06-01T09:00:00+00:00',url='https://t.me/V_Zelenskiy_official/12000',title='x',text='x',genre='channel_post',attribution='leader_channel_unverified_author',language='uk')
    merge_jsonl(data/'zelenskyy.jsonl','zelenskyy',[newest])
    class Client:
        def get(self,url):
            class Resp: pass
            z=Resp()
            if url.endswith('before=12000'):z.text=html_msg(11990,'2026-01-03')
            elif url.endswith('before=11990'):z.text=html_msg(11980,'2025-12-25')
            elif url.endswith('before=11980'):z.text=html_msg(11970,'2025-12-24')
            else:raise AssertionError('bad request '+url)
            return z
    result=resume_public_preview(leader='zelenskyy',data_dir=data,since=date(2026,1,1),until=date(2026,11,7),client=Client(),max_pages=10,batch_pages=2)
    assert result['new_text_documents']==1
    assert result['total_text_documents']==2
    assert result['reached_lower_boundary']
    assert result['stop_reason']=='older_than_2026_reached'
    assert json.loads((data/'telegram_extend_report.json').read_text())['pages_fetched']==3


def test_partial_progress_survives_access_failure(tmp_path):
    data=tmp_path/'d';data.mkdir()
    x=document(leader='zelenskyy',source='telegram_v_zelenskiy_official',external='100',published='2026-10-02T09:00:00+00:00',url='https://t.me/V_Zelenskiy_official/100',title='x',text='x',genre='channel_post',attribution='leader_channel_unverified_author',language='uk')
    merge_jsonl(data/'zelenskyy.jsonl','zelenskyy',[x])
    class Client:
        def get(self,url):
            class Resp:pass
            if url.endswith('before=100'):
                z=Resp();z.text=html_msg(99,'2026-09-01');return z
            raise ValueError('429 access error')
    result=resume_public_preview(leader='zelenskyy',data_dir=data,since=date(2026,1,1),until=date(2026,11,7),client=Client(),max_pages=10)
    assert result['stop_reason']=='access_error'
    assert result['new_text_documents']==1
    assert len((data/'zelenskyy.jsonl').read_text().splitlines())==2


def test_builder_preserves_analysis_and_audit(tmp_path):
    from corpus2026.cli import build_site
    target=tmp_path/'docs'/'data';target.mkdir(parents=True)
    for f in ['topics.json','audit.json','trump_2026-01.json']:
        (target/f).write_text('[]')
    d=tmp_path/'data';d.mkdir()
    build_site(d,tmp_path/'docs')
    assert (target/'topics.json').exists() and (target/'audit.json').exists()
    assert not (target/'trump_2026-01.json').exists()
