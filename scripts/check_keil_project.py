"""校验 Keil 工程文件（.uvprojx）是否包含本项目需要的全部文件与编译选项。

**为什么需要这个脚本**：Keil 把工程模型读进内存，退出或保存时整体写回。
如果在 Keil 打开着的时候用编辑器改 `.uvprojx`，改动会被静默覆盖——本项目
已经因此被坑过两次（2026-09-07 漏掉 `stm32f4xx_hal_i2s.c`，2026-09-08 漏掉
`stm32f4xx_hal_tim.c`），两次都是编译报错之后才发现。

而这些缺失的表现都不直观：
- 缺 HAL 源文件 → 链接期报 undefined symbol，指向的是 HAL 内部符号
- 多列了 `lcd_ex.c` → 链接期报 multiply defined（它被 `lcd.c` 用 #include 引入）
- 缺 `--no_multibyte_chars` → 编译期报 "missing closing quote"，指向中文字符串行，
  但真正原因是 armcc 按 GBK 解析 UTF-8、把结束引号当成了多字节字符的尾字节

所以这里把"工程该长什么样"写成可执行的断言，改完 `.uvprojx` 或从 Keil 退出后
跑一次即可：

    python scripts/check_keil_project.py

只读，不修改任何文件。返回码 0 = 一致，1 = 有问题。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT = (
    Path(__file__).resolve().parent.parent
    / "firmware/stm32f407/Projects/MDK-ARM/atk_f407.uvprojx"
)

REQUIRED_FILES = (
    # —— HAL：每一个都是被某个模块间接依赖、且漏掉时只在链接期才报错的 ——
    "stm32f4xx_hal_i2s.c",      # ES8388 音频
    "stm32f4xx_hal_i2s_ex.c",   # 被 hal_i2s.c 内部引用（IrqHandlerISR）
    "stm32f4xx_hal_sram.c",     # LCD 走 FSMC
    "stm32f4xx_ll_fsmc.c",      # 被 hal_sram.c 内部引用
    "stm32f4xx_hal_tim.c",      # 风扇 PWM（TIM9）
    "stm32f4xx_hal_tim_ex.c",   # 与 hal_tim.c 成对
    # —— 厂商驱动 ——
    "lcd.c",
    "touch.c",
    "ctiic.c",
    "gt9xxx.c",
    "ft5206.c",
    "24cxx.c",
    "myiic.c",
    "es8388.c",
    "i2s.c",
    # —— 本项目自研 ——
    "fan.c",
    "audio_alert.c",
    "alert_pcm.c",
    "ui_screen.c",
    "hzfont.c",
)

FORBIDDEN_FILES = {
    # lcd.c 第 39 行 #include 了它。同时列进工程会让七个 lcd_ex_*_reginit
    # 各存在两份，链接期报 multiply defined。厂商自己的工程也没有列它。
    "lcd_ex.c": "被 lcd.c 用 #include 引入，再列进工程会重复定义",
}

REQUIRED_GROUPS = (
    "Drivers/BSP/LCD",
    "Drivers/BSP/TOUCH",
    "Drivers/BSP/24CXX",
    "Drivers/BSP/UI_SCREEN",
    "Drivers/BSP/FAN",
    "Drivers/BSP/IIC",
    "Drivers/BSP/ES8388",
    "Drivers/BSP/I2S",
    "Drivers/BSP/AUDIO_ALERT",
)

REQUIRED_C_OPTIONS = {
    "--no_multibyte_chars": (
        "缺了它，armcc 会按系统 GBK 解析 UTF-8 中文字符串，"
        "把结束引号当成多字节字符的尾字节吃掉，报 missing closing quote"
    ),
}


def check(path: Path = PROJECT) -> list[str]:
    """返回问题列表；空列表表示工程文件与预期一致。"""
    if not path.is_file():
        return [f"找不到工程文件：{path}"]

    text = path.read_text(encoding="utf-8")
    files = set(re.findall(r"<FileName>(.*?)</FileName>", text))
    groups = set(re.findall(r"<GroupName>(.*?)</GroupName>", text))

    problems: list[str] = []
    for name in REQUIRED_FILES:
        if name not in files:
            problems.append(f"缺少源文件：{name}")
    for name, why in FORBIDDEN_FILES.items():
        if name in files:
            problems.append(f"不该列入的源文件：{name}（{why}）")
    for group in REQUIRED_GROUPS:
        if group not in groups:
            problems.append(f"缺少分组：{group}")

    # 只看 C 编译器那一段，汇编器的 MiscControls 与此无关
    cads = re.search(r"<Cads>.*?</Cads>", text, re.S)
    if cads is None:
        problems.append("工程文件里找不到 <Cads> 段（C 编译器设置）")
    else:
        for option, why in REQUIRED_C_OPTIONS.items():
            if option not in cads.group(0):
                problems.append(f"缺少 C 编译选项：{option}（{why}）")

    return problems


def main() -> int:
    problems = check()
    if not problems:
        print(f"[OK] Keil 工程文件一致：{PROJECT.name}")
        return 0
    print(f"[NG] Keil 工程文件有 {len(problems)} 处问题：")
    for item in problems:
        print(f"   - {item}")
    print(
        "\n提示：若刚在 Keil 里操作过，很可能是 Keil 退出时把内存中的工程模型"
        "写回、覆盖了外部修改。修复前请先关闭 Keil。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
