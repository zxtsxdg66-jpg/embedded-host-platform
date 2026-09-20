"""把归档文件送到阿里云对象存储（OSS）。

设计见 docs/02_Architecture/History_And_Cloud_Design.md 第 5.2、5.3 节。
选 OSS 而不是个人网盘的关键一条：走 OSS 时上传是**系统自身的能力**，
而走网盘要么由客户端代劳（系统本身不含上云能力），要么要开发者审核与
令牌刷新。

三条与本包其它类一致的约定：

* **绝不向调用方抛异常。** 断网、密钥错、Bucket 不存在都是这台机器上
  会真实发生的事，而它们只该让"这次没传上去"，不该让导出脚本炸掉——
  没标记上传的时段留在台账里，下次运行自然重传。
* **只在 ``application``/``scripts`` 中被创建**，与 ``SerialChannel``、
  ``OllamaClient``、``SqliteHistoryStore`` 同一条规矩。
* **凭证只从文件读，绝不硬编码**，且本模块任何日志与异常文本里都不回显
  密钥——出错时只说类型与 Bucket，不说 AccessKey。

云端只存文件：不查询、不计算、不接指令。这与"把不可靠的部件放在不承担
正确性责任的位置"是同一条原则的又一处应用——系统的正确性不依赖云端，
断网时本地照常采集、照常显示、照常问答，只是归档暂时留在本机。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("oss_config.json")
"""凭证文件的默认位置：项目根目录。

**不进仓库**（`.gitignore` 已排除）。随附的 `oss_config.example.json`
是占位示例，进仓库的是它，不是这份。
"""

_REQUIRED_KEYS = ("endpoint", "bucket", "access_key_id", "access_key_secret")
_CREDENTIAL_KEYS = ("access_key_id", "access_key_secret")

_REGION_ENDPOINT = re.compile(
    r"^(?:.+\.)?(oss-[a-z0-9-]+\.aliyuncs\.com)$", re.IGNORECASE
)
"""从"Bucket 外网访问域名"里认出纯地域 endpoint。

控制台的 Bucket 概览页显示的是 ``<桶名>.oss-<地域>.aliyuncs.com``，照着填进
配置非常自然——但 ``oss2.Bucket(auth, endpoint, bucket_name)`` 会**自己**把桶名
拼到 endpoint 前面，于是拼成 ``<桶名>.<桶名>.oss-…``，服务端回一个
``InvalidBucketName``，而那条错误信息里完全看不出根因。

2026-09-17 连着踩了两次（第二次前缀还打错了一个字符：``zxt3l`` vs ``zxt31``），
所以由代码兜住：桶名以 ``bucket`` 字段为准，endpoint 上多出来的前缀一律丢掉。
"""


def normalise_endpoint(endpoint: str) -> str:
    """去掉 endpoint 上误带的 Bucket 域名前缀；认不出来就原样返回。

    认不出的情形（自定义 CNAME、内网域名等）保持原样，不擅自改动——
    这个函数只负责修那一个已经被实际踩到的填法错误。
    """
    match = _REGION_ENDPOINT.match(endpoint.strip())
    return match.group(1) if match else endpoint.strip()


@dataclass(frozen=True)
class OssConfig:
    """一份 OSS 连接配置。

    ``__repr__`` 被刻意重写：dataclass 默认会把所有字段打出来，而这个对象
    带着 AccessKey Secret——一次无心的 ``print(config)`` 或异常回溯就足以
    把密钥写进日志或贴进聊天。
    """

    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    prefix: str = ""
    console_login_url: str = ""
    """控制台的登录入口，可留空（2026-09-18 新增）。

    起因是 ``cloud_view.py`` 原先直接打开 Bucket 文件列表页，而本项目用的是
    **RAM 子账号**——子账号不能从主账号的登录页进，得走
    ``signin.aliyun.com`` 那条带账号标识的地址，否则点开只会看到一个要求登录
    的页面，看不到文件。

    放在配置里而不是写死在脚本里，是因为这个地址**带着账号 ID 与 RAM 用户名**。
    `oss_config.json` 本来就不进版本控制（与 AccessKey 同一份文件），而脚本和
    文档是要进的——一个能标识账号的地址不该躺在仓库里。留空时退回原来的
    Bucket 页地址，功能不受影响。
    """

    def __repr__(self) -> str:
        return (
            f"OssConfig(endpoint={self.endpoint!r}, bucket={self.bucket!r}, "
            f"prefix={self.prefix!r}, access_key_id=<{len(self.access_key_id)} chars>, "
            f"access_key_secret=<hidden>, console_login_url=<hidden>)"
        )

    def key_for(self, file_name: str) -> str:
        """文件在 Bucket 里的对象名（前缀 + 文件名）。"""
        prefix = self.prefix
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        return f"{prefix}{file_name}"


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> OssConfig | None:
    """读凭证文件。文件不存在、读不动或缺键都返回 None，不抛异常。

    返回 None 而不是抛错，是因为"还没配 OSS"是一个正常状态：导出功能
    本身不需要它，脚本应当照常导出、只是不上传。
    """
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if any(not str(raw.get(key, "")).strip() for key in _REQUIRED_KEYS):
        return None
    # 示例文件里的占位（``LTAI************`` 与一串星号）不是空串，光查空值
    # 会把它当成有效配置放行——照抄示例却忘了填的人，撞到的将是一个莫名的
    # 鉴权错误，而不是"你还没填凭证"。AccessKey 的真实取值是字母数字，
    # 不含星号，据此判定是精确的。
    if any("*" in str(raw.get(key, "")) for key in _CREDENTIAL_KEYS):
        return None
    return OssConfig(
        endpoint=normalise_endpoint(str(raw["endpoint"])),
        bucket=str(raw["bucket"]).strip(),
        access_key_id=str(raw["access_key_id"]).strip(),
        access_key_secret=str(raw["access_key_secret"]).strip(),
        prefix=str(raw.get("prefix", "")).strip(),
        console_login_url=str(raw.get("console_login_url", "")).strip(),
    )


def describe_failure(error: BaseException) -> str:
    """把一个上传异常翻成一句人话。

    只认三类最常见的，其余回落为异常类型名——**刻意不穷举**：认不出的那些
    保持原样比硬套一个可能错的解释好，而 :attr:`OssUploader.last_error`
    里始终留着原始文本供排查。

    判据用的是异常文本里的关键词而不是 `oss2` 的异常类，这样 `oss2`
    改版或换 SDK 时这里最多是回落到类型名，不会连 import 都挂掉。
    """
    text = f"{type(error).__name__}: {error}"
    if "InvalidAccessKeyId" in text or "SignatureDoesNotMatch" in text:
        return "凭证不对（AccessKey 或 Secret 有误）"
    if "AccessDenied" in text or "NoSuchBucket" in text or "InvalidBucketName" in text:
        return "没有权限或 Bucket 名不对"
    if (
        "RequestError" in text
        or "Connection" in text
        or "Timeout" in text
        or "getaddrinfo" in text
    ):
        return "连不上网（或 endpoint 填错）"
    return type(error).__name__


class OssUploader:
    """把本地文件传到 OSS 的一个 Bucket 前缀下。

    连接是**惰性建立**的：构造时不碰网络，第一次真正上传时才建
    ``oss2.Bucket``。这样"没配 OSS"与"配了但断网"两种情况都不会在
    脚本启动时就失败——脚本仍然先把导出做完。
    """

    def __init__(self, config: OssConfig) -> None:
        self._config = config
        self._bucket: object | None = None
        self._failures = 0
        self._last_error = ""
        self._last_reason = ""
        self._uploaded = 0

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def last_error(self) -> str:
        """最近一次失败的原因。**不含任何凭证内容**，可以直接打印给人看。"""
        return self._last_error

    @property
    def uploaded(self) -> int:
        return self._uploaded

    @property
    def destination(self) -> str:
        """人可读的目的地描述，用于打印。不含凭证。"""
        return f"oss://{self._config.bucket}/{self._config.prefix}"

    def _note_failure(self, error: BaseException) -> None:
        self._failures += 1
        # 只记类型与消息。oss2 的异常消息里带的是 request id、状态码与
        # Bucket 名，不含密钥；但仍然不把 config 拼进去。
        self._last_error = f"{type(error).__name__}: {error}"
        self._last_reason = describe_failure(error)

    @property
    def last_reason(self) -> str:
        """最近一次失败的**一句话**原因，给人看的。

        与 :attr:`last_error` 并存而不是取代它：那一份是原始异常文本，
        排查时要用；这一份是打印给人看的。2026-09-19 断网演练时发现，
        原样打印 `oss2` 的异常会在屏幕上糊出一大块
        ``RequestError: {'status': -2, 'x-oss-request-id': '', 'details': …}``，
        而上传失败这件事恰好**会在答辩现场当众发生**（上云的验收形态就是现场演示，
        且已备了断网退路）。那一刻屏幕上该出现的是"连不上网"，不是一个字典。
        """
        return self._last_reason

    def _connect(self) -> object | None:
        if self._bucket is not None:
            return self._bucket
        try:
            import oss2
        except ImportError as error:
            self._note_failure(error)
            return None
        try:
            auth = oss2.Auth(
                self._config.access_key_id, self._config.access_key_secret
            )
            self._bucket = oss2.Bucket(
                auth, self._config.endpoint, self._config.bucket
            )
        except Exception as error:  # noqa: BLE001 - 见模块文档：绝不外抛
            self._note_failure(error)
            return None
        return self._bucket

    def upload(self, file_path: Path | str) -> bool:
        """上传一个文件，成功返回 True。任何失败都只返回 False。

        对象名为 ``prefix + 文件名``，不带本地目录结构：归档文件名里
        已经含有日期与小时，再叠一层本地路径只会让云端多出几级空目录。
        """
        path = Path(file_path)
        if not path.is_file():
            self._note_failure(FileNotFoundError(str(path)))
            return False
        bucket = self._connect()
        if bucket is None:
            return False
        try:
            bucket.put_object_from_file(  # type: ignore[attr-defined]
                self._config.key_for(path.name), str(path)
            )
        except Exception as error:  # noqa: BLE001 - 断网/鉴权失败都算正常状态
            self._note_failure(error)
            return False
        self._uploaded += 1
        return True
