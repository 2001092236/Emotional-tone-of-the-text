from corpus2026.probe_hf_putin import index_files, canonical_date, as_record, report

def test_russia_config_only():
    f=lambda c,u: {'config':c,'split':'train','url':u,'size':200}
    entries=[f('all','https://huggingface.co/datasets/all'),f('Russia','https://huggingface.co/datasets/rus'),f('Ukraine','https://huggingface.co/datasets/ua'),f('Russia','http://unsafe.example/x')]
    assert len(index_files({'parquet_files':entries}))==1

def test_date_strictly_2026():
    assert canonical_date('2026-02-11')=='2026-02-11'
    assert canonical_date('2025-12-31') is None
    assert canonical_date('2026-11-08') is None
    assert canonical_date('bad') is None

def test_original_russian_speech_only_and_no_text_leak():
    item={'speaker_name':'Vladimir Putin','speech_date':'2026-04-11',
          'language_iso':'ru','speech_title':'Речь','speech_id':'x','speech_text':'речь '*60,
          'source_url':'https://kremlin.ru/events/president/transcripts/12345'}
    y=as_record(item)
    assert y['date']=='2026-04-11' and y['word_count']==60
    assert 'speech_text' not in y and 'text' not in y
    assert y['attribution']=='secondary_academic_copy'
    assert as_record({**item,'speaker_name':'Other speaker'}) is None
    assert as_record({**item,'speech_date':'2025-04-11'}) is None
    assert as_record({**item,'language_iso':'en'}) is None
    assert as_record({**item,'source_url':'https://example.org'}) is None

def test_empty_report_not_misrepresented():
    p=report([],[],manifest_sha='x')
    assert p['status']=='no_eligible_2026_records_confirmed'
    assert not p['public_full_text']
