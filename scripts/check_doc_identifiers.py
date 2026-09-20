"""把文档里反引号包着的"代码标识符"逐个拿去源码里找，找不到的列出来。

覆盖：类名（PascalCase）、常量（UPPER_SNAKE）、函数/方法（snake_case 带括号）。

**这是一份需要人过目的清单，不是通过/失败的检查**，因此不设退出码。
框架名（`TextView`、`QLayout`）、环境变量（`PATH`）、板子丝印（`GBC_RX`）、
以及文档明写"未实现"的名字（`get_history()`、`TcpChannel`）都会被列出来，它们是正常的。
真正要找的是第三类：**文档写了某个名字、代码里其实已经改名或删掉了**。

2026-09-09 首次运行捞出两条真问题：`HEARTBEAT_INTERVAL_TICKS`（固件早已用数据上报
取代心跳帧，联调手册却还让人去找心跳）、`_extract_buffered_frame`/`_resync_buffer`
（拼帧逻辑后来抽成了 `FrameStreamBuffer`，旧方法名不复存在）。

用法::

    python scripts/check_doc_identifiers.py
"""

from __future__ import annotations

import io
import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DOC = ('.venv', 'node_modules', '.claude', 'build', '.pytest_cache',
            '08_YINGJIAN', '归档', '实验数据')

# 全部源码文本，作为"存在性"的判据
corpus = []
for pattern in ('src/**/*.py', 'scripts/**/*.py', 'tests/**/*.py',
                'firmware/stm32f407/Drivers/BSP/**/*.[ch]',
                'firmware/stm32f407/User/*.[ch]',
                'android/app/src/main/**/*.kt', '*.toml'):
    for f in ROOT.glob(pattern):
        if '__pycache__' in f.as_posix():
            continue
        corpus.append(f.read_text(encoding='utf-8', errors='replace'))
CODE = '\n'.join(corpus)

klass = re.compile(r'`([A-Z][A-Za-z0-9]{3,})`')
const = re.compile(r'`([A-Z][A-Z0-9_]{5,})`')
func = re.compile(r'`([a-z_][a-z0-9_]{3,})\(\)`')

missing: dict[str, list[str]] = {}
for doc in sorted(ROOT.rglob('*.md')):
    rel = doc.relative_to(ROOT).as_posix()
    if any(s in rel for s in SKIP_DOC):
        continue
    text = doc.read_text(encoding='utf-8', errors='replace')
    names: set[str] = set()
    names |= set(klass.findall(text))
    names |= set(const.findall(text))
    names |= set(func.findall(text))
    gone = sorted(n for n in names if n not in CODE)
    if gone:
        missing[rel] = gone

total = sum(len(v) for v in missing.values())
print(f'共 {total} 个标识符在源码中找不到\n')
for rel, names in missing.items():
    print(f'{rel}')
    print('   ', '、'.join(names))
