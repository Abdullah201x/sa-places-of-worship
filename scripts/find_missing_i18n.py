import re
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('frontend/src/translations_static.js', 'r', encoding='utf-8') as f:
    ts_code = f.read()

keys = set(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)":', ts_code))
print(f'Existing keys in translations_static.js: {len(keys)}')

html_files = [
    'frontend/index.html',
    'frontend/data.html',
    'frontend/tags.html',
    'frontend/tasks.html',
    'frontend/community.html',
]
missing = set()

for path in html_files:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    for m in re.findall(r'placeholder="([^"]+)"', content):
        clean = re.sub(r'\s+', ' ', m).strip()
        if any('\u0600' <= c <= '\u06FF' for c in clean) and clean not in keys:
            missing.add(('placeholder', clean, path))
    for m in re.findall(r'aria-label="([^"]+)"', content):
        clean = re.sub(r'\s+', ' ', m).strip()
        if any('\u0600' <= c <= '\u06FF' for c in clean) and clean not in keys:
            missing.add(('aria-label', clean, path))
    for m in re.findall(r'title="([^"]+)"', content):
        clean = re.sub(r'\s+', ' ', m).strip()
        if any('\u0600' <= c <= '\u06FF' for c in clean) and clean not in keys:
            missing.add(('title', clean, path))

for kind, val, p in sorted(missing):
    print(f'{kind:12} | {os.path.basename(p):15} | {val}')
