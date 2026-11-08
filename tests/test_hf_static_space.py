import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'publish_hf_space.py'


def module():
    spec = importlib.util.spec_from_file_location('hf_site_deploy', SCRIPT)
    out = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(out)
    return out


def test_static_allowlist_and_space_readme(tmp_path):
    m = module()
    src, dst = tmp_path / 'docs', tmp_path / 'space'
    src.mkdir()
    (src / 'index.html').write_text('<html>КОРПУС</html>', encoding='utf-8')
    (src / 'data').mkdir()
    (src / 'data' / 'summary.json').write_text('{}')
    (src / '.env').write_text('SECRET')
    (src / 'server.key').write_text('SECRET')
    assert m.prepare_site(src, dst) == 2
    assert (dst / 'README.md').exists()
    assert 'sdk: static' in (dst / 'README.md').read_text()
    assert not (dst / '.env').exists()
    assert not (dst / 'server.key').exists()
