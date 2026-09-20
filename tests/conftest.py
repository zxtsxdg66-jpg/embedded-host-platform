"""全局测试夹具。

目前只有一件事，但这件事很要紧：**不让任何用例碰到真实的云端凭证。**

2026-09-17 踩到：`scripts/cloud_sync.py` 接上传之后，几条没有打桩的用例
走了 `--oss-config` 的默认值 `oss_config.json`——那是项目根目录下真实的
AccessKey。于是一次普通的 `pytest` 真的连上了公网 OSS，拿回一个带
RequestId 的 403。测试碰真实外部服务，性质比普通缺陷重：它会产生真实的
网络请求与可能的计费，也会让"测试通过与否"取决于当天有没有网。

修法不是"每条用例记得传 `--oss-config`"——靠记性迟早会漏，而漏一次就是
拿真密钥连公网。所以在这里把默认值整个换掉：`autouse` 夹具让每个用例看到
的默认凭证路径都是一个**不存在的**临时文件，于是 `load_config()` 返回
None，上传被跳过。要测上传逻辑的用例自己打桩（见
`tests/scripts/test_cloud_sync.py` 的 `_stub_upload`），不依赖这个默认值。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CONFIG_HOLDERS = (
    "storage.oss_uploader",
    "scripts.cloud_sync",
    "scripts.cloud_view",
)
"""所有持有 `DEFAULT_CONFIG_PATH` 副本的模块。

第一个是源头，其余都是 `from ... import DEFAULT_CONFIG_PATH` 拿走的副本——
**只改源头挡不住它们**。写成列表而不是逐个 `monkeypatch`，是因为将来再加
一个碰凭证的脚本时，只需往这里补一行；靠记性去补三处 `monkeypatch`，
迟早会漏一处，而漏一处就是拿真密钥连公网。
"""


@pytest.fixture(autouse=True)
def _never_read_real_cloud_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """把凭证文件的默认路径指到一个不存在的文件上。"""
    absent = tmp_path_factory.mktemp("no-credentials") / "absent_oss_config.json"

    import importlib

    for name in _CONFIG_HOLDERS:
        try:
            module = importlib.import_module(name)
        except ImportError:  # pragma: no cover - 该模块不存在时无需设防
            continue
        if hasattr(module, "DEFAULT_CONFIG_PATH"):
            monkeypatch.setattr(module, "DEFAULT_CONFIG_PATH", absent)


@pytest.fixture
def absent_oss_config(tmp_path: Path) -> Path:
    """一个明确不存在的凭证路径，给需要显式传 `--oss-config` 的用例用。"""
    return tmp_path / "absent_oss_config.json"
