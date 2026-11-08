from unittest.mock import Mock
import pytest
from corpus2026.sources import Client, AccessDenied
from corpus2026.official_probe import inspect_one, CANDIDATES


def test_check_robots_for_every_redirect():
    c=Client(delay=0)
    allowed=[]
    c.allowed=lambda url:(allowed.append(url) or url=='https://source.example/article')
    resp=Mock(status_code=302,headers={'Location':'https://blocked.example/article'})
    c.session=Mock()
    c.session.get.return_value=resp
    with pytest.raises(AccessDenied,match='robots.txt disallows'):
        c.get('https://source.example/article')
    assert allowed==['https://source.example/article','https://blocked.example/article']
    c.session.get.assert_called_once()


def test_no_downgrade_redirects():
    c=Client(delay=0);c.allowed=lambda url:True
    c.session=Mock()
    c.session.get.return_value=Mock(status_code=301,headers={'Location':'http://insecure.example/x'})
    with pytest.raises(AccessDenied,match='Unsafe redirect'):
        c.get('https://secure.example/a')


def test_probe_records_metadata_without_text():
    c=Mock()
    c.get.return_value=Mock(content=b'<html><head><title>Speech record</title></head><body><h1>Speech</h1><a href="/news/speech-12345">read</a></body></html>', status_code=200,url='https://president.gov.ua/en/news/speeches')
    x=inspect_one(c,CANDIDATES[1])
    assert x['status']=='ok' and x['page_has_h1']
    assert x['article_link_candidates']==1
    assert x['text_imported'] is False
    assert x['content_reproduction_permitted'] is None


def test_restricted_mirror_not_probed():
    assert all('publicnow.com' not in x['url'] for x in CANDIDATES)
