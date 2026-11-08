import hashlib
from datetime import date
from corpus2026.publish_licensed_speeches import build_release, LICENSE_URL


def test_verbatim_preserved_only_2026():
    exact='\n  Виступ Президента — незмінений текст.  \nАбзац із пробілами.\n'*8
    rows=[
      {'date':1767225600,'link':'https://www.president.gov.ua/news/test-102421','topic':'Виступ', 'lang':'uk','full_text':exact},
      {'date':1735689600,'link':'https://www.president.gov.ua/news/old-90000','topic':'2025', 'lang':'uk','full_text':exact},
      {'date':1767225600,'link':'https://evil.com/news/false','topic':'Other', 'lang':'en','full_text':exact},
    ]
    d=build_release(rows,date(2026,11,7),'a'*64)
    assert d['total_documents']==1
    assert d['counts_by_language']=={'uk':1,'en':0}
    row=d['documents'][0]
    assert row['text'] == exact
    assert hashlib.sha256(exact.encode()).hexdigest() == row['text_sha256']
    assert row['unmodified_source_text'] is True
    assert row['direct_original_comparison_verified'] is False
    assert row['original_material_license_url'] == LICENSE_URL
    assert row['url'].startswith('https://www.president.gov.ua/news/')
    assert d['excluded']['outside_period_or_undated'] == 1
    assert d['excluded']['invalid_official_url'] == 1
