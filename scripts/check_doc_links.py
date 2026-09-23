"""检查文档里的链接与路径引用是否指向真实存在的东西。

markdown 坏链不会有任何提示，只有点的人才发现。
文档一移动目录，所有 `../` 相对链接就可能一起失效。

两类检查：

1. **markdown 链接** `[文字](路径)` —— 必须能解析到真实文件。这是硬错误。
2. **反引号里的路径** —— 只查带目录分隔符的（`src/service/xxx.py`），
   裸文件名（`manager.py`）是行文里的简称、不是引用，不查。
   章节内确立基准目录后的简写（`data/GatewayClient.kt`）会在几个常见基准下尝试解析。

用法::

    python scripts/check_doc_links.py

退出码 1 表示存在失效的 markdown 链接；反引号路径只列出、不判失败——
其中 `xxx.c/.h` 这类"两个文件合写"的行文约定必然解析不到，属正常。
"""

from __future__ import annotations

import io
import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = pathlib.Path(__file__).resolve().parent.parent

SKIP = ('.venv', 'node_modules', 'build', '.pytest_cache', '.git')

docs = [p for p in ROOT.rglob('*.md')
        if not any(s in p.as_posix() for s in SKIP)]

link_re = re.compile(r'\[([^\]]*)\]\(([^)\s]+)\)')
path_re = re.compile(r'`([A-Za-z0-9_./\-]+\.(?:py|md|c|h|kt|xml|toml|bat|uvprojx))`')

bad_links: list[str] = []
bad_paths: list[str] = []

for doc in docs:
    text = doc.read_text(encoding='utf-8', errors='replace')
    rel = doc.relative_to(ROOT).as_posix()

    for label, target in link_re.findall(text):
        if target.startswith(('http', '#', 'mailto:')):
            continue
        clean = target.split('#')[0]
        if not clean:
            continue
        resolved = (doc.parent / clean).resolve()
        if not resolved.exists():
            bad_links.append(f'{rel}  ->  {target}   [{label[:30]}]')

    for candidate in set(path_re.findall(text)):
        if candidate.startswith(('http', 'www')):
            continue
        # 只查"看起来像完整路径"的（带目录分隔符）。裸文件名在行文里是简称，
        # 例如"见 `manager.py`"，不是可点击的引用。
        if '/' not in candidate:
            continue
        # 反引号路径一律按仓库根解释；也允许它是相对当前文件的
        hits = [(ROOT / candidate), (doc.parent / candidate)]
        if any(h.exists() for h in hits):
            continue
        # 允许 src/ 下省略 src 前缀的写法（文档里常写 service/xxx.py）
        # 章节内确立了基准目录后的简写（"data/GatewayClient.kt"、"widgets/xxx.py"）
        # 也算有效：在这些常见基准下能找到就不报。
        bases = ('src', 'docs', 'tests', 'scripts', 'android',
                 'firmware/stm32f407', 'src/ui', 'src/service', 'src/application',
                 'firmware/stm32f407/Drivers', 'firmware/stm32f407/Drivers/BSP',
                 'android/app/src/main',
                 'android/app/src/main/java/com/example/envmonitor',
                 'android/app/src/main/res')
        if any((ROOT / base / candidate).exists() for base in bases):
            continue
        bad_paths.append(f'{rel}  ->  {candidate}')

print(f'扫描 {len(docs)} 份文档\n')
print(f'== 失效的 markdown 链接（{len(bad_links)}）==')
for b in sorted(bad_links):
    print(' ', b)
print(f'\n== 反引号里指不到的路径（{len(bad_paths)}）==')
for b in sorted(set(bad_paths)):
    print(' ', b)

sys.exit(1 if bad_links else 0)
