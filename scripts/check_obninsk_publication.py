"""Проверить публикуемые материалы Обнинска без повторного пространственного расчёта."""

import csv
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'school-placement/obninsk/publication'
SCOPES = ['README.md', '.gitignore',
          '.github/workflows/obninsk-check.yml', 'scripts/check_obninsk_publication.py',
          'docs/img/obninsk', 'examples/data/obninsk', 'school-placement/obninsk']


def main():
    """Проверить ссылки, сохранённые результаты, размеры и отсутствие локальных секретов."""
    OUT.mkdir(exist_ok=True)
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', *SCOPES], cwd=ROOT
    ).decode().split('\0')
    paths = sorted({ROOT / n for n in names if n and (ROOT / n).is_file()
                    and n not in {'school-placement/obninsk/publication/files.csv',
                                  'school-placement/obninsk/publication/checks.json'}})
    assert paths
    issues = []
    secret = re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|'
                        r'AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    text_suffixes = {'.md', '.rst', '.txt', '.py', '.js', '.css', '.html', '.json', '.csv',
                     '.ipynb', '.yml', '.yaml', '.xml', '.graphml'}
    for path in paths:
        name = path.relative_to(ROOT).as_posix()
        if path.stat().st_size >= 100 * 2**20:
            issues.append(f'Размер >=100 MiB: {name}')
        if path.suffix in text_suffixes:
            text = path.read_text(encoding='utf-8-sig')
            if re.search(r'/(?:Users|home)/[A-Za-z0-9_.-]+/', text):
                issues.append(f'Абсолютный личный путь: {name}')
            if secret.search(text):
                issues.append(f'Возможный секрет: {name}')
    readme = (ROOT / 'README.md').read_text()
    links = re.findall(r'\]\(([^)]+)\)', readme)
    for link in links:
        if urlsplit(link).scheme:
            continue
        target = ROOT / unquote(link.split('#')[0])
        if not target.exists():
            issues.append(f'Нет файла README: {link}')
    images = []
    for link in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', readme):
        path = ROOT / link
        data = path.read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        width, height = struct.unpack('>II', data[16:24])
        assert width >= 1000 and height >= 600
        images.append({'path': link, 'width': width, 'height': height})
    app = ROOT / 'school-placement/obninsk/results'
    state = json.loads((app / 'scenarios.json').read_text())
    assert {'A', 'B', 'V'} <= {s['role'] for s in state['scenarios']}
    auto = json.loads((app / state['latest_search']).read_text())
    assert auto['complete'] and auto['checked'] == auto['total'] == len(auto['rows']) == 298
    assert auto['errors'] == 0 and len(auto['best_blocks']) == 69
    final = json.loads((app / 'final/verification.json').read_text())
    assert final['status'] == 'passed'
    for name, digest in final['protected_files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    with (app / 'final/scenario_comparison.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert [int(row['Остаточный дефицит']) for row in rows] == [6812, 6212, 6212, 6212]
    assert not issues, issues
    manifest = [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
    with (OUT / 'files.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['path', 'bytes', 'sha256'])
        writer.writeheader()
        writer.writerows(manifest)
    report = {'status': 'passed', 'files_without_derived_manifest': len(paths),
              'total_bytes': sum(p.stat().st_size for p in paths),
              'largest_file': max(manifest, key=lambda row: row['bytes']),
              'readme_links_checked': len(links), 'images': images,
              'protected_results_match': True, 'secret_or_personal_path_findings': issues,
              'pages_enabled': False, 'publication_pending_user_approval': False}
    (OUT / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
