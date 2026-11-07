from datetime import date
from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from corpus2026.core import START, END, in_range, extract_date, merge_jsonl, read_jsonl, document
from corpus2026.sources import listing_urls, parse_official_article, collect_trump
from corpus2026.cli import build_site


def test_strict_2026_window():
    assert in_range('2026-01-01T00:00:00+00:00', START, END)
    assert in_range('2026-11-08T10:00:00+00:00', START, END)
    assert not in_range('2025-12-31T23:59:59+00:00', date(2025,1,1), END)
    assert not in_range('2027-01-01T00:00:00+00:00', START, date(2027,1,1))
    assert not in_range(None, START, END)


def test_ukrainian_date_and_article():
    sample='''<html><h1>Звернення Президента</h1><div class="date">2 листопада 2026 року</div>
    <div class="article_content"><p>Сьогодні ми говорили з нашими партнерами про важливі питання безпеки.</p></div></html>'''
    doc=parse_official_article(sample,'https://www.president.gov.ua/news/test-slug-12345','zelenskyy')
    assert doc['date']=='2026-11-02'
    assert 'важливі питання' in doc['text']
    assert doc['attribution']=='official_speech_text'


def test_putin_mixed_speaker_turns():
    sample='''<html><head><meta property="article:published_time" content="2026-07-05T09:15:00+03:00"></head>
    <body><h1>Встреча</h1><div itemprop="articleBody">
    <p>В.Путин: Добрый день, коллеги, приветствую всех участников.</p>
    <p>Переходим к обсуждению текущих вопросов.</p>
    <p>С.Лавров: Благодарю, Владимир Владимирович.</p>
    <p>В.Путин: Спасибо за подробный доклад.</p></div></body></html>'''
    doc=parse_official_article(sample,'https://kremlin.ru/events/president/transcripts/79942','putin')
    assert doc['date']=='2026-07-05'
    assert 'Переходим' in doc['text']
    assert 'Благодарю' not in doc['text']
    assert 'Спасибо за подробный доклад' in doc['text']
    assert doc['attribution']=='direct_speech_segment'


def test_archive_article_links():
    page='''<a href="/events/president/transcripts/79942">A</a><a href="/events/president/transcripts/2">Next</a>'''
    assert listing_urls(page,'https://kremlin.ru/events/president/transcripts','putin')==['https://kremlin.ru/events/president/transcripts/79942']
    page2='''<a href="/news/speech-slug-12345">Article</a><a href="?page=2">Next</a>'''
    assert listing_urls(page2,'https://www.president.gov.ua/news/speeches','zelenskyy')==['https://www.president.gov.ua/news/speech-slug-12345']


def test_trump_filter_only_2026():
    class FakeResponse:
        def json(self):return [
            {'id':'1','created_at':'2025-12-31T10:00:00Z','content':'previous year'},
            {'id':'2','created_at':'2026-06-01T10:00:00Z','content':'<p>Historical post</p>','url':'https://truthsocial.com/@realDonaldTrump/posts/2'},
            {'id':'3','created_at':'2027-01-01T10:00:00Z','content':'future'}]
    class FakeClient:
        def get(self,url):return FakeResponse()
    docs,errors=collect_trump(FakeClient(),date(2026,1,1),date(2026,12,31))
    assert len(docs)==1 and docs[0]['id'] and docs[0]['date']=='2026-06-01'
    assert docs[0]['text']=='Historical post'
    assert not errors


def test_persist_dedup_and_site_output(tmp_path):
    folder=tmp_path/'data'/'2026'
    d=document(leader='trump',source='cnn_truth_archive',external='42',published='2026-01-05T00:00:00+00:00',
               url='https://example.com/42',title='Test',text='A historical post with data.',genre='social_post',
               attribution='secondary_archive',language='en')
    assert merge_jsonl(folder/'trump.jsonl','trump',[d,d])==(1,1)
    assert len(read_jsonl(folder/'trump.jsonl','trump'))==1
    site=tmp_path/'site'
    summary=build_site(folder,site)
    assert summary['total']==1
    assert 'trump:2026-01' in summary['files']
    assert (site/'data'/'trump_2026-01.json').exists()
    assert merge_jsonl(folder/'trump.jsonl','trump',[d])==(1,0)


def test_rejects_2025_even_on_merge(tmp_path):
    d=document(leader='putin',source='kremlin',external='2',published='2025-12-31T00:00:00+00:00',
               url='https://example.org',title='Old',text='test',genre='speech',attribution='x',language='ru')
    with pytest.raises(ValueError):
        merge_jsonl(tmp_path/'putin.jsonl','putin',[d])


def test_public_telegram_preview_parser_and_2026_filter():
    from corpus2026.sources import parse_telegram_preview, collect_telegram_public
    body='''<div class="tgme_widget_message" data-post="V_Zelenskiy_official/12000">
    <div class="tgme_widget_message_text">Вітаю всіх з важливим рішенням.</div>
    <a class="tgme_widget_message_date"><time datetime="2026-06-09T13:00:00+00:00"></time></a></div>
    <div class="tgme_widget_message" data-post="V_Zelenskiy_official/11999">
    <div class="tgme_widget_message_text">Старий пост 2025 року</div>
    <a class="tgme_widget_message_date"><time datetime="2025-12-30T00:00:00+00:00"></time></a></div>'''
    found = parse_telegram_preview(body, 'zelenskyy')
    assert len(found) == 2
    assert found[0]['date'] == '2026-06-09'
    assert found[0]['attribution'] == 'leader_channel_unverified_author'
    assert all(x['source'].startswith('telegram_') for x in found)
    class Resp:
        text=body
    class Fake:
        def get(self,url):return Resp()
    docs, warnings=collect_telegram_public(Fake(),'zelenskyy',date(2026,1,1),date(2026,11,8),max_pages=2)
    assert len(docs)==1 and docs[0]['date']=='2026-06-09'


def test_kremlin_telegram_press_not_direct_speech():
    from corpus2026.sources import parse_telegram_preview
    body='''<div class="tgme_widget_message" data-post="news_kremlin/5555">
    <div class="tgme_widget_message_text">Президент провёл встречу. Подробнее — на сайте.</div>
    <time datetime="2026-07-10T11:00:00Z"></time></div>'''
    result=parse_telegram_preview(body,'putin')
    assert len(result)==1
    assert result[0]['attribution']=='institutional_press_channel'
