"""One-shot deployment of the static public research interface to HF Spaces.

Requires HF_TOKEN and HF_SPACE_ID only in the GitHub Actions environment.
No secrets are copied into the Space; only audited static docs/ assets.
"""
from __future__ import annotations
import os
import re
import shutil
import tempfile
from pathlib import Path

ALLOWED = {'.html', '.css', '.js', '.svg', '.json', '.txt', '.webp', '.png', '.jpg', '.jpeg'}
SPACE_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}/[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$')


def prepare_site(src: Path, dest: Path) -> int:
    if not (src / 'index.html').exists():
        raise ValueError('docs/index.html не найден')
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in src.rglob('*'):
        if not f.is_file() or f.is_symlink() or f.suffix.lower() not in ALLOWED:
            continue
        if any(part.startswith('.') for part in f.relative_to(src).parts):
            continue
        target = dest / f.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        count += 1
    (dest / 'README.md').write_text('''---
title: Корпус публичных высказываний 2026
emoji: 📊
colorFrom: blue
colorTo: gray
sdk: static
app_file: index.html
license: other
license_name: mixed-sources
license_link: https://github.com/2001092236/Emotional-tone-of-the-text/blob/main/DATA_RIGHTS.md
---

Независимая образовательная исследовательская публикация.
Код и аналитика — некоммерческая лицензия; исходные тексты — лицензии первоисточников.
''', encoding='utf-8')
    return count


def main() -> None:
    from huggingface_hub import HfApi
    token = os.environ.get('HF_TOKEN', '').strip()
    repo = os.environ.get('HF_SPACE_ID', '').strip()
    if not token or not SPACE_PATTERN.fullmatch(repo):
        raise SystemExit('Укажите GitHub Secret HF_TOKEN и переменную HF_SPACE_ID (username/space-name)')
    src = Path('docs').resolve()
    with tempfile.TemporaryDirectory(prefix='mgimo_hf_space_') as tmp:
        path = Path(tmp)
        count = prepare_site(src, path)
        api = HfApi(token=token)
        visibility = os.environ.get('HF_SPACE_VISIBILITY','private').strip().lower()
        if visibility not in {'private','public'}:
            raise ValueError('HF_SPACE_VISIBILITY должно быть private или public')
        api.create_repo(repo_id=repo, repo_type='space', space_sdk='static', private=visibility == 'private', exist_ok=True)
        api.upload_folder(repo_id=repo, repo_type='space', folder_path=str(path), commit_message='Обновить статический исследовательский сайт 2026')
        print(f'Загружено файлов: {count}; Space: https://huggingface.co/spaces/{repo}')


if __name__ == '__main__':
    main()
