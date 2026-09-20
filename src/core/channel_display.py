"""通道的展示约定：中文名、单位、小数位。全项目唯一定义处。

放在 ``core`` 而不是某个呈现端里，是因为**呈现端不止一个**，而在此之前
同一套约定已经散成了两份半：``ui/channel_display.py`` 有名称、单位与小数位，
``gateway/channel_units.py`` 只有单位并在注释里写着"必须与 ui 那份保持一致"，
2026-09-18 归档导出又要第三份。靠注释提醒人手动同步，已经在同一天失败过一次——
手机端 ``ChannelFormat`` 与桌面端的小数位对不上，同一条读数在两端显示成
25.0 与 25.03，返工重打了一次 APK。

为什么 ``gateway`` 不能直接 import ``ui/channel_display.py``：
``import ui.channel_display`` 会执行 ``ui/__init__.py``，后者 import
``MainController``，于是把 PyQt6 整个拉进来。无界面的网关与控制台脚本都
不该依赖 GUI 框架，所以共享的那一份必须落在谁都能安全 import 的地方。

**这仍然只是展示约定，不是协议的一部分。** ``protocol``/``communication``
不得据此做任何判断：线上传的是 channel id，中文名与单位只在给人看的地方
出现。放进 ``core`` 是为了让三个呈现端共用一份定义，不是把它降到传输层。

小数位按各自传感器的精度定，见 :data:`CHANNEL_DECIMALS`。
"""

from __future__ import annotations

CHANNEL_LABELS: dict[str, str] = {
    "temperature": "温度",
    "humidity": "湿度",
    "noise": "噪声",
}

CHANNEL_UNITS: dict[str, str] = {
    "temperature": "°C",
    "humidity": "%",
    "noise": "dB",
}

#: 每条通道的读数显示几位小数。
#:
#: 按通道分别定而不是统一一个格式，依据是各自传感器的精度：AHT20 的湿度
#: 精度约 ±2 %RH，写成 "56.27 %" 是在声称器件给不出的精度，"56 %" 才诚实；
#: 温度（±0.3 ℃）与噪声写两位，那正是读它们的目的。
#:
#: 取整**只发生在显示这一步**。存进数据库的、助手引用的、传上云的都仍是
#: 原始浮点——这套系统从头到尾的规矩是数字来自实测，显示上的方便不能变成
#: 对数据的悄悄编辑。
CHANNEL_DECIMALS: dict[str, int] = {
    "temperature": 2,
    "humidity": 0,
    "noise": 2,
}

#: 未登记通道的小数位：``None``，意思是"不要重新格式化"。
#:
#: 上面的取整靠的是知道传感器精度，而这份理由对一个本层没听说过的通道
#: 并不成立——把 "7" 写成 "7.00" 是反方向的虚假精度。平台本就不在这里
#: 枚举通道，所以只对说得出理由的那几条取整，其余原样输出。
DEFAULT_DECIMALS: int | None = None


def channel_label(channel_id: str) -> str:
    """通道的中文名；未知通道回落为 id 本身，不抛异常。"""
    return CHANNEL_LABELS.get(channel_id, channel_id)


def channel_unit(channel_id: str) -> str:
    """通道的显示单位；未知通道回落为空串。"""
    return CHANNEL_UNITS.get(channel_id, "")


def channel_decimals(channel_id: str) -> int | None:
    """通道的小数位；``None`` 表示原样输出、不重新格式化。"""
    return CHANNEL_DECIMALS.get(channel_id, DEFAULT_DECIMALS)


def format_value(value: object, channel_id: str) -> str:
    """把一条读数渲染成给人看的文本。

    **非数值原样放行。** 数据信号送的是纯字符串，一条通道完全可以报一个
    状态词而不是数字（模拟器的 ``ch2`` 报的就是 "status-ok"），所以这里
    要的是一个"认不出就不管"的格式化器，而不是一个会抛异常的——
    表格单元格不是发现"这条通道不是数值"的地方。
    """
    decimals = channel_decimals(channel_id)
    if decimals is None:
        return str(value)
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    return f"{numeric:.{decimals}f}"
