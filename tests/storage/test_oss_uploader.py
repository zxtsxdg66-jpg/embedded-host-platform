"""OSS 上传器：配置读取与失败处理。**全部用打桩，不碰网络。**

设计见 `docs/decisions/06-history.md` 第 5.2、5.3 节。
这里守三件事：

- **密钥不外泄**：`OssConfig` 的 repr 里不能出现 secret；
- **绝不抛异常**：断网、缺包、鉴权失败都只让"这次没传上"，不让脚本炸掉；
- **没配 OSS 是正常状态**：读不到配置返回 None，导出照常进行。

真实上传另行单独实跑验证，不放进自动化测试——它有外部副作用（往 Bucket
里写对象），不该每次 `pytest` 都发生。
"""

from __future__ import annotations

import json
from pathlib import Path

from storage.oss_uploader import (
    OssConfig,
    OssUploader,
    describe_failure,
    load_config,
    normalise_endpoint,
)

_FAKE = {
    "endpoint": "oss-cn-hangzhou.aliyuncs.com",
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
    path.write_text(
        json.dumps({**_FAKE, **overrides}, ensure_ascii=False), encoding="utf-8"
    )
    return path


# -- 凭证不外泄 ----------------------------------------------------------------


def test_the_repr_never_shows_the_secret() -> None:
    """一次无心的 print(config) 或异常回溯就足以把密钥写进日志。

    dataclass 默认 repr 会把所有字段打出来，所以这里必须重写——
    这条用例就是防它哪天被改回默认实现。
    """
    text = repr(_config())

    assert "fake-secret-value" not in text
    assert "hidden" in text


def test_the_repr_does_not_show_the_key_id_either() -> None:
    text = repr(_config())

    assert "LTAI-fake-id" not in text
    # 但长度还是给出来，便于确认"配的是不是那一份"
    assert "chars" in text


def test_the_failure_message_carries_no_credentials(tmp_path: Path) -> None:
    uploader = OssUploader(_config())

    uploader.upload(tmp_path / "does-not-exist.csv")

    assert "fake-secret-value" not in uploader.last_error
    assert "LTAI-fake-id" not in uploader.last_error


def test_the_destination_is_printable_without_credentials() -> None:
    assert OssUploader(_config()).destination == "oss://test-bucket/env-monitor/"


# -- 配置读取 ------------------------------------------------------------------


def test_a_complete_config_is_loaded(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path))

    assert config is not None
    assert config.bucket == "test-bucket"
    assert config.prefix == "env-monitor/"


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """还没配 OSS 是正常状态：导出不需要它，脚本该照常把导出做完。"""
    assert load_config(tmp_path / "nope.json") is None


def test_malformed_json_is_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "oss_config.json"
    path.write_text("{ 这不是 JSON", encoding="utf-8")

    assert load_config(path) is None


def test_a_config_missing_a_required_key_is_rejected(tmp_path: Path) -> None:
    """缺键不能当"部分可用"——半份凭证连不上，只会在上传时才暴露。"""
    incomplete = dict(_FAKE)
    del incomplete["access_key_secret"]
    path = tmp_path / "oss_config.json"
    path.write_text(json.dumps(incomplete), encoding="utf-8")

    assert load_config(path) is None


def test_a_blank_value_counts_as_missing(tmp_path: Path) -> None:
    """示例文件里的占位往往是空串，不该被当成有效配置。"""
    assert load_config(_write_config(tmp_path, access_key_id="   ")) is None


def test_the_prefix_is_optional(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path, prefix=""))

    assert config is not None
    assert config.key_for("env_20260917_15.csv") == "env_20260917_15.csv"


# -- 对象名 --------------------------------------------------------------------


def test_the_object_key_is_prefix_plus_file_name() -> None:
    config = _config()

    assert config.key_for("env_20260917_15.csv") == "env-monitor/env_20260917_15.csv"


def test_a_prefix_without_a_trailing_slash_still_works() -> None:
    """控制台里填前缀时很容易漏掉末尾斜杠，补上而不是拼出 env-monitorenv_...csv。"""
    config = _config(prefix="env-monitor")

    assert config.key_for("a.csv") == "env-monitor/a.csv"


def test_local_directories_do_not_leak_into_the_object_key(tmp_path: Path) -> None:
    """对象名只取文件名。归档名里已含日期与小时，再叠本地路径只会让云端
    多出几级空目录。"""
    config = _config()

    assert config.key_for(Path("exports/env_20260917_15.csv").name) == (
        "env-monitor/env_20260917_15.csv"
    )


# -- endpoint 的填法容错 -------------------------------------------------------


def test_a_bucket_prefixed_endpoint_is_normalised() -> None:
    """控制台 Bucket 概览页显示的是"外网访问域名"，带桶名前缀。

    照着填进配置很自然，但 `oss2.Bucket(auth, endpoint, bucket_name)` 会**自己**
    再把桶名拼到前面，于是变成 `<桶名>.<桶名>.oss-…`，服务端只回一句
    `InvalidBucketName`，根因完全看不出来。
    """
    assert (
        normalise_endpoint("zxt31.oss-cn-beijing.aliyuncs.com")
        == "oss-cn-beijing.aliyuncs.com"
    )


def test_a_mistyped_prefix_is_dropped_too() -> None:
    """前缀打错字也照样剥掉：桶名以 `bucket` 字段为准，前缀本就是冗余的。

    2026-09-17 实际踩到的就是这一种——endpoint 里是 `zxt3l`（小写 L），
    而桶名是 `zxt31`（数字 1）。只按"前缀等于桶名"去剥是挡不住的。
    """
    assert (
        normalise_endpoint("zxt3l.oss-cn-beijing.aliyuncs.com")
        == "oss-cn-beijing.aliyuncs.com"
    )


def test_a_plain_region_endpoint_is_left_alone() -> None:
    assert (
        normalise_endpoint("oss-cn-beijing.aliyuncs.com")
        == "oss-cn-beijing.aliyuncs.com"
    )


def test_an_internal_endpoint_is_left_alone() -> None:
    """内网地址是另一回事，不能被当成前缀剥掉。"""
    assert (
        normalise_endpoint("oss-cn-beijing-internal.aliyuncs.com")
        == "oss-cn-beijing-internal.aliyuncs.com"
    )


def test_an_unrecognised_endpoint_is_left_alone() -> None:
    """自定义 CNAME 之类认不出来的，原样返回——这个函数只修那一种已经
    被真实踩到的填法错误，不擅自改动其它形态。"""
    assert (
        normalise_endpoint("my.custom.cdn.example.com")
        == "my.custom.cdn.example.com"
    )


def test_load_config_normalises_the_endpoint(tmp_path: Path) -> None:
    """配置里填了带前缀的域名，读出来应当已经是纯地域 endpoint。"""
    config = load_config(
        _write_config(tmp_path, endpoint="test-bucket.oss-cn-beijing.aliyuncs.com")
    )

    assert config is not None
    assert config.endpoint == "oss-cn-beijing.aliyuncs.com"


# -- 绝不抛异常 ----------------------------------------------------------------


def test_uploading_a_missing_file_fails_without_raising(tmp_path: Path) -> None:
    uploader = OssUploader(_config())

    assert uploader.upload(tmp_path / "gone.csv") is False
    assert uploader.failures == 1
    assert uploader.uploaded == 0


def test_a_connection_failure_is_counted_not_raised(
    tmp_path: Path, monkeypatch
) -> None:
    """建连接时抛错（密钥格式非法、endpoint 写错）只算一次失败。

    走**真实的** `_connect()`：往 `sys.modules` 里塞一个假 oss2，让它的
    `Auth` 抛错。这条用例最初把 `_connect` 整个打桩成一个抛异常的函数，
    那是在假设一个违反自身契约的 `_connect`——它真实的实现自己就吞掉异常
    返回 None，那样测等于验了一个不会发生的情形（2026-09-17 发现并改正）。
    """
    import sys
    import types

    target = tmp_path / "env_20260917_15.csv"
    target.write_text("ts_local\n", encoding="utf-8")

    def _auth(*args: object, **kwargs: object) -> object:
        raise ValueError("invalid credentials")

    fake = types.ModuleType("oss2")
    fake.Auth = _auth  # type: ignore[attr-defined]
    fake.Bucket = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "oss2", fake)
    uploader = OssUploader(_config())

    assert uploader.upload(target) is False
    assert uploader.failures == 1
    assert uploader.uploaded == 0
    assert "invalid credentials" in uploader.last_error


def test_a_server_side_failure_is_counted_not_raised(
    tmp_path: Path, monkeypatch
) -> None:
    """断网或鉴权失败：这次没传上，台账不标记，下次自然重传。"""
    target = tmp_path / "env_20260917_15.csv"
    target.write_text("ts_local\n", encoding="utf-8")
    uploader = OssUploader(_config())

    class _Bucket:
        def put_object_from_file(self, key: str, filename: str) -> None:
            raise OSError("network is unreachable")

    monkeypatch.setattr(uploader, "_connect", lambda: _Bucket())

    assert uploader.upload(target) is False
    assert uploader.failures == 1
    assert "network is unreachable" in uploader.last_error


def test_a_successful_upload_uses_the_prefixed_key(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "env_20260917_15.csv"
    target.write_text("ts_local\n", encoding="utf-8")
    uploader = OssUploader(_config())
    seen: list[tuple[str, str]] = []

    class _Bucket:
        def put_object_from_file(self, key: str, filename: str) -> None:
            seen.append((key, filename))

    monkeypatch.setattr(uploader, "_connect", lambda: _Bucket())

    assert uploader.upload(target) is True
    assert seen == [("env-monitor/env_20260917_15.csv", str(target))]
    assert uploader.uploaded == 1
    assert uploader.failures == 0


def test_the_connection_is_built_once_and_reused(
    tmp_path: Path, monkeypatch
) -> None:
    """惰性连接、只建一次：一次运行要传十几个小时片，不该建十几次连接。

    数的是 `oss2.Bucket` 被**构造**了几次，这样才真的验到 `_bucket` 那层缓存。
    最初的写法把 `_connect` 整个打桩掉，缓存那段根本不会被执行，等于没验到
    要验的东西（2026-09-17 发现并改正）。
    """
    import sys
    import types

    built: list[int] = []

    class _Bucket:
        def __init__(self, *args: object, **kwargs: object) -> None:
            built.append(1)

        def put_object_from_file(self, key: str, filename: str) -> None:
            return None

    def _auth(*args: object, **kwargs: object) -> object:
        return object()

    fake = types.ModuleType("oss2")
    fake.Auth = _auth  # type: ignore[attr-defined]
    fake.Bucket = _Bucket  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "oss2", fake)

    uploader = OssUploader(_config())
    for index in range(3):
        target = tmp_path / f"env_2026091{index}_15.csv"
        target.write_text("ts_local\n", encoding="utf-8")
        uploader.upload(target)

    assert built == [1]
    assert uploader.uploaded == 3


# -- 占位凭证必须被挡住 --------------------------------------------------------


def test_the_shipped_example_config_is_not_usable() -> None:
    """随仓库发布的那份示例必须**通不过**校验。

    它的占位是 `LTAI************` 与一串星号，都不是空串——只查空值会把它
    当成有效配置放行，于是照抄示例却忘了填的人撞到的将是一个莫名的鉴权
    错误，而不是"你还没填凭证"。2026-09-17 实测发现并修（校验改为同时拒绝
    含星号的凭证值），这条用例守住它。
    """
    example = Path(__file__).resolve().parents[2] / "oss_config.example.json"

    assert example.is_file(), "示例文件应当随仓库存在"
    assert load_config(example) is None


def test_a_starred_placeholder_is_rejected(tmp_path: Path) -> None:
    """任何含星号的凭证值都当作没填。AccessKey 的真实取值是字母数字。"""
    assert load_config(_write_config(tmp_path, access_key_secret="*" * 32)) is None


# -- 控制台登录入口（2026-09-18） ---------------------------------------------


def test_the_console_login_url_is_optional(tmp_path: Path) -> None:
    """没配也照常工作：缺这一项时 cloud_view 退回 Bucket 页地址。"""
    path = tmp_path / "oss.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "oss-cn-beijing.aliyuncs.com",
                "bucket": "b",
                "access_key_id": "LTAIabc",
                "access_key_secret": "secret",
                "prefix": "p/",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config is not None
    assert config.console_login_url == ""


def test_the_console_login_url_is_read_when_present(tmp_path: Path) -> None:
    """RAM 子账号进不去主账号的控制台页，得走 signin 那条带账号标识的地址。"""
    path = tmp_path / "oss.json"
    path.write_text(
        json.dumps(
            {
                "endpoint": "oss-cn-beijing.aliyuncs.com",
                "bucket": "b",
                "access_key_id": "LTAIabc",
                "access_key_secret": "secret",
                "console_login_url": "https://signin.example/login?u=x",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config is not None
    assert config.console_login_url == "https://signin.example/login?u=x"


def test_the_login_url_is_not_in_the_repr(tmp_path: Path) -> None:
    """它带着账号 ID 与 RAM 用户名，和 AccessKey 同属"一次无心的 print
    就泄出去"的东西，所以与密钥一样不进 __repr__。"""
    config = OssConfig(
        endpoint="oss-cn-beijing.aliyuncs.com",
        bucket="b",
        access_key_id="LTAIabc",
        access_key_secret="secret",
        console_login_url="https://signin.example/login?u=someone%40123456.onaliyun.com",
    )

    text = repr(config)

    assert "signin.example" not in text
    assert "onaliyun" not in text
    assert "123456" not in text


# -- 失败原因的人话翻译（2026-09-19） -----------------------------------------


def test_a_network_failure_reads_as_one_sentence() -> None:
    """上传失败会在演示现场当众发生（上云的验收形态就是现场演示，且备了断网退路）。
    那一刻屏幕上该出现的是"连不上网"，不是一个 oss2 异常字典。"""
    error = RuntimeError(
        "RequestError: {'status': -2, 'details': \"('Connection aborted.', "
        "RemoteDisconnected('Remote end closed connection without response'))\"}"
    )

    assert describe_failure(error) == "连不上网（或 endpoint 填错）"


def test_a_bad_key_is_told_apart_from_a_bad_network() -> None:
    """两者的处置完全不同：一个是插回网线，一个是改配置文件。"""
    error = RuntimeError("ServerError: {'status': 403, 'Code': 'InvalidAccessKeyId'}")

    assert describe_failure(error) == "凭证不对（AccessKey 或 Secret 有误）"


def test_a_permission_problem_is_its_own_case() -> None:
    error = RuntimeError("ServerError: {'status': 403, 'Code': 'AccessDenied'}")

    assert describe_failure(error) == "没有权限或 Bucket 名不对"


def test_an_unrecognised_failure_falls_back_to_the_type_name() -> None:
    """刻意不穷举：认不出的保持原样，比硬套一个可能错的解释好。
    原始文本始终留在 last_error 里供排查。"""
    assert describe_failure(ValueError("something else entirely")) == "ValueError"


def test_the_raw_text_is_still_kept_alongside_the_sentence() -> None:
    """两份并存——一份给人看，一份给排查用。"""
    uploader = OssUploader(
        OssConfig(
            endpoint="oss-cn-beijing.aliyuncs.com",
            bucket="b",
            access_key_id="LTAIabc",
            access_key_secret="secret",
        )
    )
    uploader._note_failure(RuntimeError("ServerError: {'Code': 'AccessDenied'}"))

    assert uploader.last_reason == "没有权限或 Bucket 名不对"
    assert "AccessDenied" in uploader.last_error
    assert uploader.last_error != uploader.last_reason
