"""看一眼已经传上云的归档：先在终端列清单，再打开控制台页面。

双击项目根目录的 ``cloud_view_查看云端.bat``。它只读，不上传、不删除、不改动任何东西。

**为什么先列清单再开浏览器**，而不是只开浏览器：控制台要登录、页面会改版、
现场网络也可能只够一次 API 调用而撑不起一个前端页面。终端里这份清单是程序
自己用 ListObjects 查出来的，不依赖登录态，也不会因为阿里云改版而失效——
浏览器那一步是锦上添花，清单才是证据。

与 ``cloud_sync.py`` 的关系：那个负责"导出并上传"，这个只负责"看"。分开是
因为看的动作应当**绝对安全**——不会因为手滑多传一份、也不会改台账状态。
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

if __package__ in (None, ""):  # 双击 .bat 直接跑时，src/ 不在 sys.path 上
    _ROOT = Path(__file__).resolve().parent.parent
    for _entry in (str(_ROOT), str(_ROOT / "src")):
        if _entry not in sys.path:
            sys.path.insert(0, _entry)

from storage.oss_uploader import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    OssConfig,
    load_config,
)

CONSOLE_BASE = "https://oss.console.aliyun.com/bucket"


def region_of(endpoint: str) -> str:
    """从 endpoint 取出地域标识，如 ``oss-cn-beijing``。

    控制台的 URL 用的是地域而不是完整域名。endpoint 已由
    ``storage.oss_uploader.normalise_endpoint()`` 规整过，这里只取第一段。
    """
    return endpoint.split(".")[0]


def console_url(config: OssConfig) -> str:
    """Bucket 文件列表页的地址。

    **这个 URL 的形状是按 2026-09 的控制台写的**，阿里云改版就可能失效。
    失效了也不影响这个脚本的主要用途——终端里的清单照样是准的，
    那才是"文件真的在云上"的证据。
    """
    if config.console_login_url:
        # 2026-09-18：本项目用的是 RAM 子账号，而子账号进不去主账号的控制台
        # 页面——直接打开 Bucket 列表只会看到一个要求登录的页。配置里给了
        # 登录入口就走它，登进去之后控制台自己会落到 Bucket 页。
        # 该地址带账号标识，因此只存在于不进版本控制的 oss_config.json 里。
        return config.console_login_url
    path = quote(config.prefix, safe="")
    region = region_of(config.endpoint)
    return f"{CONSOLE_BASE}/{region}/{config.bucket}/object?path={path}"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def list_objects(config: OssConfig) -> list[tuple[str, int, datetime]] | None:
    """列出前缀下的对象。查不了就返回 None，不抛异常。

    返回 (对象名, 字节数, 最后修改时刻)，时刻已转成本地时区。
    """
    try:
        import oss2
    except ImportError as error:
        print(f"[cloud_view] 缺少 oss2：{error}")
        return None
    try:
        auth = oss2.Auth(config.access_key_id, config.access_key_secret)
        bucket = oss2.Bucket(auth, config.endpoint, config.bucket)
        return [
            (
                item.key,
                item.size,
                datetime.fromtimestamp(item.last_modified).astimezone(),
            )
            for item in oss2.ObjectIterator(bucket, prefix=config.prefix)
        ]
    except Exception as error:  # noqa: BLE001 - 断网/无列举权限都算正常状态
        # 只印类型与消息，绝不带上 config——它带着 AccessKey。
        print(f"[cloud_view] 列举失败：{type(error).__name__}: {error}")
        return None


def print_listing(items: list[tuple[str, int, datetime]], prefix: str) -> None:
    if not items:
        print(
            f"[cloud_view] {prefix} 下还没有文件。"
            "先双击 cloud_sync_导出并上传.bat 传一次。"
        )
        return
    print(f"[cloud_view] 共 {len(items)} 个文件：")
    total = 0
    for key, size, moment in items:
        total += size
        name = key[len(prefix):] if key.startswith(prefix) else key
        print(f"  {moment:%Y-%m-%d %H:%M}  {_human_size(size):>9}  {name}")
    print(f"[cloud_view] 合计 {_human_size(total)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="列出已上传的归档，并打开阿里云 OSS 控制台。只读。",
    )
    parser.add_argument(
        "--oss-config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"OSS 凭证文件，默认 {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="只在终端列清单，不打开浏览器",
    )
    args = parser.parse_args(argv)

    config = load_config(Path(args.oss_config))
    if config is None:
        print(f"[cloud_view] 没有可用的 OSS 配置：{args.oss_config}")
        print("[cloud_view] 参照 oss_config.example.json 填好之后再来。")
        return 1

    print(f"[cloud_view] 查看 oss://{config.bucket}/{config.prefix}")
    items = list_objects(config)
    if items is not None:
        print_listing(items, config.prefix)

    url = console_url(config)
    if args.no_browser:
        print(f"[cloud_view] 控制台地址（--no-browser，未自动打开）：{url}")
        return 0

    print(f"[cloud_view] 正在打开控制台：{url}")
    if not webbrowser.open(url):
        # 打不开浏览器不算失败：地址已经印出来了，手动复制即可。
        print("[cloud_view] 没能自动打开浏览器，请复制上面的地址。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
