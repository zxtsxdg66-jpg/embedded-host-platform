"""Tests for ui.channel_display -- no api/controller/PyQt6 involved."""

from __future__ import annotations

from ui.channel_display import (
    channel_decimals,
    channel_label,
    channel_unit,
    format_value,
)


def test_known_channels_have_labels() -> None:
    assert channel_label("temperature") == "温度"
    assert channel_label("humidity") == "湿度"
    assert channel_label("noise") == "噪声"


def test_known_channels_have_units() -> None:
    assert channel_unit("temperature") == "°C"
    assert channel_unit("humidity") == "%"
    assert channel_unit("noise") == "dB"


def test_unknown_channel_label_falls_back_to_the_raw_id() -> None:
    assert channel_label("pressure") == "pressure"


def test_unknown_channel_unit_falls_back_to_empty_string() -> None:
    assert channel_unit("pressure") == ""


# -- 按通道定小数位（2026-09-18） ------------------------------------------


def test_temperature_and_noise_get_two_decimals() -> None:
    assert format_value(25.029390713306746, "temperature") == "25.03"
    assert format_value(48.9, "noise") == "48.90"


def test_humidity_is_rounded_to_a_whole_number() -> None:
    """AHT20 的湿度精度是 ±2 %RH，多写一位小数就是虚假精度。"""
    assert format_value(56.27332669523828, "humidity") == "56"


def test_a_string_reading_passes_through_untouched() -> None:
    """数据信号送的是纯字符串，通道完全可以报一个状态词而不是数字；
    表格单元格不是发现"这条通道不是数值"的地方，所以只让格式化器放行。"""
    assert format_value("status-ok", "ch2") == "status-ok"


def test_an_unknown_channel_is_not_reformatted() -> None:
    """上面的取整靠的是知道传感器精度，而这份理由对一个本层没听说过的
    通道并不成立——把 "7" 写成 "7.00" 是反方向的虚假精度。"""
    assert format_value("7", "ch1") == "7"
    assert channel_decimals("ch1") is None


def test_the_desktop_and_the_phone_agree_on_decimals() -> None:
    """android/.../ui/ChannelFormat.kt 用的是同一套口径：湿度取整、
    其余两位（2026-09-18 起，APK 已重打）。同一条读数两端显示不同，
    是最容易让人不再相信这些数字的那种不一致。

    这条断言拦不住 Kotlin 那边被单方面改掉——两端的约定只能靠一起改来保证，
    模块注释里写了这一点。它能拦住的是这一侧被悄悄改掉。"""
    assert channel_decimals("humidity") == 0
    assert channel_decimals("temperature") == 2
    assert channel_decimals("noise") == 2
