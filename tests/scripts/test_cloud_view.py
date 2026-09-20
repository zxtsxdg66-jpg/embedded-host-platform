"""云端归档查看脚本：只读地列清单并打开控制台。

设计见 `scripts/cloud_view.py` 的模块文档。这里守三件事：

- **只读**：这个脚本不该有任何上传、删除或改台账的路径；
- **清单优先**：控制台页面要登录、会改版，终端里那份清单才是证据，
  所以浏览器打不开也不算失败；
- **凭证不外泄**：失败信息里不能出现密钥。

与上传器的测试一样**全部打桩，不碰网络**。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.cloud_view import (
    console_url,
    list_objects,
    main,
    print_listing,
    region_of,
)
from storage.oss_uploader import OssConfig

_FAKE = {
    "endpoint": "oss-cn-beijing.aliyuncs.com",
    "bucket": "test-bucket",
    "access_key_id": "LTAI-fake-id",
    "access_key_secret": "fake-secret-value",
    "prefix": "env-monitor/",
}


def _config(**overrides: object) -> OssConfig:
    data = {**_FAKE, **overrides}
    return OssConfig(
        endpoint=str(data["endpoint"]),
        bucket=str(data["bucket"]),
        access_key_id=str(data["access_key_id"]),
        access_key_secret=str(data["access_key_secret"]),
        prefix=str(data["prefix"]),
    )


def _write_config(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "oss_config.json"
    path.write_text(json.dumps({**_FAKE, **overrides}), encoding="utf-8")
    return path


# -- 控制台地址 ----------------------------------------------------------------


def test_the_region_comes_from_the_endpoint() -> None:
    assert region_of("oss-cn-beijing.aliyuncs.com") == "oss-cn-beijing"


def test_the_console_url_points_at_the_bucket_and_prefix() -> None:
    url = console_url(_config())

    assert "oss-cn-beijing" in url
    assert "test-bucket" in url
    # 前缀里的斜杠要转义，否则会被当成路径的一部分
    assert "env-monitor%2F" in url


def test_the_console_url_carries_no_credentials() -> None:
    """这个地址会被打印出来、也可能被贴进聊天，不能带密钥。"""
    url = console_url(_config())

    assert "fake-secret-value" not in url
    assert "LTAI-fake-id" not in url


# -- 清单 ----------------------------------------------------------------------


def test_listing_failure_is_reported_not_raised(capsys) -> None:
    """没装 oss2、断网、没有列举权限——都只印一句，不抛异常。"""
    import sys
    import types

    fake = types.ModuleType("oss2")

    def _auth(*args: object, **kwargs: object) -> object:
        raise RuntimeError("network unreachable")

    fake.Auth = _auth  # type: ignore[attr-defined]
    original = sys.modules.get("oss2")
    sys.modules["oss2"] = fake
    try:
        result = list_objects(_config())
    finally:
        if original is None:
            del sys.modules["oss2"]
        else:
            sys.modules["oss2"] = original

    assert result is None
    printed = capsys.readouterr().out
    assert "network unreachable" in printed
    assert "fake-secret-value" not in printed


def test_an_empty_prefix_says_what_to_do_next(capsys) -> None:
    """空不是错误，但要告诉人下一步该干什么。"""
    print_listing([], "env-monitor/")

    printed = capsys.readouterr().out
    assert "还没有文件" in printed
    assert "cloud_sync" in printed


def test_the_listing_strips_the_prefix_and_totals_the_size(capsys) -> None:
    moment = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc).astimezone()
    print_listing(
        [
            ("env-monitor/env_20260917_15.csv", 272, moment),
            ("env-monitor/env_20260917_16.csv", 1024, moment),
        ],
        "env-monitor/",
    )

    printed = capsys.readouterr().out
    # 前缀是每一行都一样的噪声，列出来只会挤掉文件名
    assert "env_20260917_15.csv" in printed
    assert "env-monitor/env_20260917_15.csv" not in printed
    assert "共 2 个文件" in printed
    assert "合计" in printed


# -- 命令行 --------------------------------------------------------------------


def test_a_missing_config_is_a_readable_failure(tmp_path: Path, capsys) -> None:
    assert main(["--oss-config", str(tmp_path / "nope.json")]) == 1

    printed = capsys.readouterr().out
    assert "没有可用的 OSS 配置" in printed
    assert "oss_config.example.json" in printed


def test_no_browser_prints_the_url_instead_of_opening_it(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import scripts.cloud_view as module

    opened: list[str] = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(module, "list_objects", lambda config: [])

    assert main(
        ["--oss-config", str(_write_config(tmp_path)), "--no-browser"]
    ) == 0

    assert opened == []
    assert "oss.console.aliyun.com" in capsys.readouterr().out


def test_the_browser_is_opened_by_default(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import scripts.cloud_view as module

    opened: list[str] = []
    monkeypatch.setattr(
        module.webbrowser, "open", lambda url: opened.append(url) or True
    )
    monkeypatch.setattr(module, "list_objects", lambda config: [])

    assert main(["--oss-config", str(_write_config(tmp_path))]) == 0

    assert len(opened) == 1
    assert "test-bucket" in opened[0]


def test_a_browser_that_will_not_open_is_not_a_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """地址已经印出来了，手动复制即可——不该因此让脚本报错退出。"""
    import scripts.cloud_view as module

    monkeypatch.setattr(module.webbrowser, "open", lambda url: False)
    monkeypatch.setattr(module, "list_objects", lambda config: [])

    assert main(["--oss-config", str(_write_config(tmp_path))]) == 0
    assert "没能自动打开浏览器" in capsys.readouterr().out


def test_the_listing_is_printed_before_the_browser_opens(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """先有清单再开浏览器：控制台要登录、会改版，清单才是证据。"""
    import scripts.cloud_view as module

    moment = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc).astimezone()
    monkeypatch.setattr(
        module,
        "list_objects",
        lambda config: [("env-monitor/env_20260917_15.csv", 272, moment)],
    )
    monkeypatch.setattr(module.webbrowser, "open", lambda url: True)

    main(["--oss-config", str(_write_config(tmp_path))])

    printed = capsys.readouterr().out
    assert printed.index("env_20260917_15.csv") < printed.index("正在打开控制台")
