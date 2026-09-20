"""把历史库里尚未导出的整点时段导成 CSV 归档（P3 起在此之后接上传）。

**手动触发**：双击项目根目录的 ``cloud_sync_导出并上传.bat``。系统运行期间只往历史库
写，不含任何定时器、后台线程或上传队列——想上云时才跑这个脚本，它把
"还没导出的时段"一次补齐。这样断网重试、退避、后台失败告警统统不需要，
下次运行自然补上，而"下次"由人决定。设计见
docs/02_Architecture/History_And_Cloud_Design.md 第 5.1 节。

与设计文档 3.3 节的一处偏离：那里写的是新增 ``scripts/archive_export.py``，
分期表里写的是 ``scripts/cloud_sync.py``。这里按后者做成**单一入口**——
P3 的上传要紧接在导出之后，"导出→上传"是一条连贯动作，拆成两个脚本反而
要在它们之间传递台账状态。

三条不容易一眼看出、但都踩过或差点踩到的约定：

1. **只导出已经结束的小时。** 当前这个小时还在写入，导出它会得到半截数据，
   而台账一旦记了就不会再补——那一小时的后半段就永久丢了。
2. **先写文件、再登记台账。** 反过来的话，文件写失败但台账已记，那个时段
   再也不会被补导出。
3. **先写临时文件再改名。** 中途失败（U 盘拔了、磁盘满）不会留下一个半截
   CSV 被当成完整归档。"断开目标目录后重连能补上"这条验收标准针对的就是它。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):  # 双击 .bat 直接跑时，src/ 不在 sys.path 上
    _ROOT = Path(__file__).resolve().parent.parent
    for _entry in (str(_ROOT), str(_ROOT / "src")):
        if _entry not in sys.path:
            sys.path.insert(0, _entry)

from core.channel_display import (  # noqa: E402
    channel_label,
    channel_unit,
    format_value,
)
from core.timestamps import now_utc  # noqa: E402
from service.history import HistoryPoint  # noqa: E402
from storage.export_ledger import ExportRecord, SqliteExportLedger  # noqa: E402
from storage.oss_uploader import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    OssUploader,
    load_config,
)
from storage.sqlite_history import (  # noqa: E402
    DEFAULT_DATABASE_PATH,
    SqliteHistoryStore,
)

SLOT_FORMAT = "%Y%m%d_%H"
"""时段标识：本地时间的整点，如 ``20260917_15``。

用本地时间而不是 UTC，是因为这个名字要出现在文件名上、给人看——
"我昨天下午三点那段数据"应该能直接对上 ``env_20260917_15.csv``。
库里存的仍然是 UTC（见 4.1 节），两者不冲突：CSV 里两列都给。
"""

DEFAULT_EXPORT_DIR = Path("exports")

EXPORT_CHANNELS: tuple[str, ...] = ("temperature", "humidity", "noise")
"""宽表里固定成列的三条通道，顺序即列序。

固定而不是按数据里出现的通道动态生成，是为了**每小时的文件列结构一样**：
一个时段恰好没收到噪声，那一列该是空的，而不是整列消失——否则把两份 CSV
并排看或者前后拼起来时，列会对不齐。不在此列的通道另行处理，见
:func:`_wide_rows`。
"""

ROUND_GAP = timedelta(milliseconds=500)
"""判定"这几条读数属于同一轮采集"的时间间隔上限。

依据是实测而不是估计：2026-09-18 查真实硬件的历史库，同一轮内三个通道的
时间戳相差约 **2 毫秒**（27.44 / 57.35 / 40.7 那一组是 .172288、.173732、
.174122），而轮与轮之间相差约 **3 秒**——差了一千五百倍。500 毫秒落在中间，
离两边都有两个数量级以上的余量。

**为什么这里可以按时间合并，而界面的历史表不可以**：那边只有到达顺序、
没有每条读数的时刻，丢一帧就会把第 N 轮的温度和第 N+1 轮的湿度排进同一行，
而且看不出来。这里每条读数都带微秒级时间戳，丢帧的结果是**那一格空着**，
不会被下一轮的值顶上——差别不在谨慎程度，在有没有可依据的事实。
"""

CSV_COLUMNS = ["时间", "温度(°C)", "湿度(%RH)", "噪声(dB)", "设备", "备注"]
"""宽表表头：一行一个采集时刻。

2026-09-18 由长表（``ts_local,ts_utc,device_id,channel,value,valid``，
一行一个读数）改成这样，因为那份 CSV 是给人看的——它要被 Excel 打开、
被翻阅、被贴进论文。原来的样子有四处硌人：表头是英文标识符；两列
ISO-8601 带时区的时间戳（``2026-09-17T21:00:00+08:00``）**Excel 根本不认，
会当文本左对齐**，排不了序也画不了图；同一时刻的三个读数分散在三行；
``valid`` 写作 0/1，看的人不知道那是什么。

时间列改用 ``YYYY-MM-DD HH:MM:SS``（空格分隔、不带时区后缀），这是 Excel
认得的日期时间格式。**UTC 那一列去掉了**：它当初是为机器读留的，而这份
文件的用途是给人看；库里存的仍然是 UTC，需要机器口径时从库里取，不必
让每个读表的人都跨过一列自己用不上的东西。
"""


def slot_of(moment: datetime) -> str:
    """该时刻属于哪个时段（按本地时间取整点）。"""
    return moment.astimezone().strftime(SLOT_FORMAT)


def slot_bounds(slot: str) -> tuple[datetime, datetime]:
    """时段的起止时刻，闭区间，带本地时区。

    终点取下一个整点减 1 微秒而不是整点本身：闭区间用整点会让相邻两个
    时段都包含那一瞬间的读数，导出两份文件里各有一条重复记录。
    """
    start = datetime.strptime(slot, SLOT_FORMAT).astimezone()
    end = start + timedelta(hours=1) - timedelta(microseconds=1)
    return start, end


def file_name_for(slot: str) -> str:
    """归档文件名，与 ``scripts/collect_thesis_data.py`` 同一套命名习惯。"""
    return f"env_{slot}.csv"


_SCAN_FLOOR = datetime(2000, 1, 1, tzinfo=timezone.utc)
"""向前扫描的下界。早于任何可能的读数，又不触碰纪元边界。

**不能用 `datetime.fromtimestamp(0)`**：它本身没问题，但随后的
`.astimezone()` 在 UTC 以东的时区（本机 UTC+8）要把它换算到 1970-01-01
之前的 UTC 时刻，Windows 在这里抛 `OSError: [Errno 22] Invalid argument`。
2026-09-17 实测踩到：整个脚本包括 `--dry-run` 都会直接失败。
"""


def earliest_slot(store: SqliteHistoryStore) -> str | None:
    """库里最早一条读数所在的时段；库空则为 None。"""
    oldest = store.query_range(_SCAN_FLOOR, now_utc(), limit=1)
    return slot_of(oldest[0].timestamp) if oldest else None


def pending_slots(
    store: SqliteHistoryStore, ledger: SqliteExportLedger, now: datetime
) -> list[str]:
    """还没导出、且已经结束的时段，由早到晚。

    从最早一条读数所在的时段扫到上一个整点。中间没有数据的小时会被反复
    扫到（系统关着的时段），这是有意接受的代价：每次只是一条走索引的
    空查询，换来的是"哪个小时有数据"这件事不必额外记一份、也不会与库
    本身失去同步。
    """
    first = earliest_slot(store)
    if first is None:
        return []
    cursor, _ = slot_bounds(first)
    current_start, _ = slot_bounds(slot_of(now))
    slots = []
    while cursor < current_start:
        slot = slot_of(cursor)
        if not ledger.is_exported(slot):
            slots.append(slot)
        cursor += timedelta(hours=1)
    return slots


def _device_label(devices: list[str]) -> str:
    """一行里那些设备的显示写法。

    硬件模式下只有一台（``mcu-1``），直接写出来。模拟器模式下三条通道
    各挂一台设备，逐行写成
    ``sim-env-1-temp、sim-env-1-humi、sim-env-1-noise`` 会在每一行重复
    四十多个字符——而这次改版的目的就是把这种噪声去掉。因此共享前缀时
    折成 ``sim-env-1-*``：谁给的哪条通道从名字上看得出来，不必每行复述。

    不共享前缀就老实全列。宁可长，也不能把两台不相干的设备并成一个名字。
    """
    if not devices:
        return ""
    if len(devices) == 1:
        return devices[0]
    prefix = os.path.commonprefix(devices)
    if len(prefix) >= 3:
        return f"{prefix}*"
    return "、".join(devices)


def _group_rounds(points: list[HistoryPoint]) -> list[list[HistoryPoint]]:
    """把按时间排好的读数切成一轮一组。

    两条切分规则，任一成立就开新的一轮：

    1. 距本轮**第一条**读数超过 :data:`ROUND_GAP`；
    2. 这条通道在本轮里已经有值了——同一轮不会把同一条通道报两次，
       出现重复就说明新的一轮开始了。

    第二条不是多余的：万一某一轮只有噪声上报，而下一轮紧接着也只有噪声，
    只看时间间隔会把它们并成一行、丢掉一条读数。按"通道重复"切就不会。

    与第一条读数比而不是与前一条比，是为了不让间隔累积——链式比较下，
    每条都比前一条晚 400 毫秒的话，十条会被并成一轮跨越 4 秒。
    """
    rounds: list[list[HistoryPoint]] = []
    current: list[HistoryPoint] = []
    seen: set[str] = set()
    for point in points:
        starts_new = bool(current) and (
            point.timestamp - current[0].timestamp > ROUND_GAP
            or point.channel in seen
        )
        if starts_new:
            rounds.append(current)
            current, seen = [], set()
        current.append(point)
        seen.add(str(point.channel))
    if current:
        rounds.append(current)
    return rounds


def _wide_rows(points: list[HistoryPoint]) -> list[list[object]]:
    """把读数渲染成宽表：一行一个采集时刻。

    三件事在这里定下来：

    * **数值按通道取小数位**（``core.channel_display``，与界面、手机端
      共用同一份定义）。取整只在这里发生，库里存的仍是原始浮点。
    * **无效读数不进数值列**，改写进备注并附上原值。固件在 Modbus 读失败
      时压根不报噪声，所以真到了的无效读数是链路质量的证据，不能丢；
      但把一个不可信的数字放进数值列，它会被照样画进曲线里。
    * **缺哪条通道就在备注里点名**。空格本身看得见，但看得见的是"这里没有
      数"，看不出"没有的是哪一条"——尤其当三列里空了两列的时候。
    """
    rows: list[list[object]] = []
    for group in _group_rounds(points):
        values: dict[str, str] = {}
        notes: list[str] = []
        devices: list[str] = []
        arrived: set[str] = set()
        for point in group:
            channel = str(point.channel)
            label = channel_label(channel)
            arrived.add(channel)
            if str(point.device_id) not in devices:
                devices.append(str(point.device_id))
            if not point.valid:
                # 记进 arrived 而不只是跳过：这一帧**到了**，只是数不可信。
                # 不这么做的话备注会同时写"读数无效"和"未上报"，自相矛盾，
                # 而读的人分不出到底是链路断了还是传感器读坏了——这恰好是
                # 这一列最该说清楚的区别。
                notes.append(f"{label}读数无效（原值 {point.value}）")
                continue
            text = format_value(point.value, channel)
            if channel in EXPORT_CHANNELS:
                values[channel] = text
            else:
                # 不在固定三列里的通道仍要留痕，否则它会被悄悄丢掉。
                notes.append(f"{label} {text}{channel_unit(channel)}")
        for channel in EXPORT_CHANNELS:
            if channel not in arrived:
                notes.append(f"{channel_label(channel)}未上报")
        moment = group[0].timestamp.astimezone()
        rows.append(
            [
                moment.strftime("%Y-%m-%d %H:%M:%S"),
                *(values.get(channel, "") for channel in EXPORT_CHANNELS),
                _device_label(devices),
                "；".join(notes),
            ]
        )
    return rows


def export_slot(
    store: SqliteHistoryStore,
    ledger: SqliteExportLedger,
    slot: str,
    export_dir: Path,
    now: datetime,
) -> int | None:
    """导出一个时段。返回写入的行数；该时段没有数据则返回 None。

    没有数据时**不产生空文件、也不登记台账**：登记了的话，将来即使补进
    数据也不会再导出；而一个 0 行的 CSV 传上云只是噪声。
    """
    start, end = slot_bounds(slot)
    points = store.query_range(start, end)
    if not points:
        return None

    target = export_dir / file_name_for(slot)
    temporary = target.with_suffix(".csv.tmp")
    export_dir.mkdir(parents=True, exist_ok=True)
    rows = _wide_rows(points)
    # utf-8-**sig**：带 BOM。中文 Windows 上的 Excel 打开无 BOM 的 UTF-8
    # CSV 会按 GBK 解，中文表头直接是乱码。这一条不是猜的——本项目 2026-09-17
    # 与 09-18 各被 GBK 咬过一次（`✓` 在控制台抛 UnicodeEncodeError，
    # 且崩在保存之前）。表头改成中文的同一刻就必须带上 BOM。
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    temporary.replace(target)

    # 台账记的是**读数条数**而不是表格行数：它是这个时段收到了多少数据的
    # 口径，不该因为换了一种排版方式就变。宽表把三条读数并成一行，
    # 若改记行数，历史台账与新台账就不是一个东西了。
    ledger.record_export(slot, target.name, len(points), now)
    return len(points)


def _upload_pending(
    ledger: SqliteExportLedger,
    pending: list[ExportRecord],
    export_dir: Path,
    config_path: Path,
) -> int:
    """把待发队列里的归档送上云，返回失败个数。

    **没配 OSS 不算失败**：导出本身已经完成，凭证是另一件事；脚本照常
    以 0 退出，队列留着，配好之后再跑一次就补传了。

    失败的那些**不标记上传**——台账里 `uploaded_at` 仍为空，下次运行自然
    重传。这就是设计文档说的"断网时未标记的文件下次继续传"，不需要重试
    循环与退避：重试的时机由人决定。
    """
    config = load_config(config_path)
    if config is None:
        print(
            f"[cloud_sync] 待上传 {len(pending)} 个时段；"
            f"未配置 OSS（{config_path}），本次只导出。"
        )
        return 0

    uploader = OssUploader(config)
    print(f"[cloud_sync] 上传到 {uploader.destination}")
    failures = 0
    for record in pending:
        target = export_dir / record.file_name
        if not target.is_file():
            # 归档被手工删掉了。不标记、也不算失败，但要说清楚：台账仍记着
            # 这一段导出过，所以它**不会**被自动重新导出——想要的话得先把
            # 台账里那一行删掉。宁可说明白，也不替人做删数据的决定。
            print(
                f"[cloud_sync] {record.file_name} 本地已不存在，跳过"
                "（台账仍记为已导出，不会自动重导）"
            )
            continue
        if uploader.upload(target):
            ledger.mark_uploaded(record.slot, now_utc())
            print(f"[cloud_sync] {record.file_name} 已上传")
        else:
            failures += 1
            # 每个文件只印一句人话。原始异常文本留到最后印一次——
            # 四个文件各糊一大块 oss2 异常字典，现场投屏上没人读得下去，
            # 而真正有用的信息（连不上网 / 凭证不对）就那么几个字。
            print(f"[cloud_sync] {record.file_name} 没传上：{uploader.last_reason}")
    if failures:
        print(f"[cloud_sync] {failures} 个时段没传上，下次运行会重试。")
        print(f"[cloud_sync] 原因：{uploader.last_reason}")
        print(f"[cloud_sync] 排查用的原始信息：{uploader.last_error}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把历史库里尚未导出的整点时段导成 CSV 归档。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", default=str(DEFAULT_DATABASE_PATH), help="历史库路径"
    )
    parser.add_argument(
        "--dir", default=str(DEFAULT_EXPORT_DIR), help="归档输出目录"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出会导出哪些时段，不写任何文件",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="只导出到本地，不上传（现场没网时用它）",
    )
    parser.add_argument(
        "--oss-config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"OSS 凭证文件，默认 {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument(
        "--slot",
        action="append",
        metavar="时段",
        help="只处理指定时段（如 20260918_17），可重复给多个；"
        "不给则处理全部。导出与上传都只认这几个时段",
    )
    args = parser.parse_args(argv)

    database = Path(args.db)
    if not database.exists():
        print(f"[cloud_sync] 找不到历史库：{database}")
        print(
            "[cloud_sync] 先用 run_gui_模拟数据界面.bat / "
            "run_all_界面加网关.bat 跑一会儿，让它攒些数据。"
        )
        return 1

    store = SqliteHistoryStore(database)
    ledger = SqliteExportLedger(database)
    try:
        now = now_utc()
        wanted = set(args.slot) if args.slot else None
        slots = pending_slots(store, ledger, now)
        if wanted is not None:
            unknown = wanted - set(slots) - {r.slot for r in ledger.all_records()}
            if unknown:
                # 拼错时段名是最容易犯的错，而它的表现会是"什么都没发生"——
                # 与"这些时段都传过了"看起来一模一样。宁可直接报错退出。
                print(f"[cloud_sync] 没有这些时段：{'、'.join(sorted(unknown))}")
                print("[cloud_sync] 用 --dry-run 看有哪些时段可选。")
                return 1
            slots = [slot for slot in slots if slot in wanted]
        if not slots:
            print("[cloud_sync] 没有待导出的时段——已结束的小时都导过了。")
        elif args.dry_run:
            print(f"[cloud_sync] 待导出 {len(slots)} 个时段（--dry-run，未写文件）：")
            for slot in slots:
                print(f"  {slot} -> {file_name_for(slot)}")
            # 演示前要确认的是"按下去会发生什么"，而待传队列与待导出是
            # 两件事——上一次断网留下的积压不会出现在上面那张表里。
            queued = ledger.pending_uploads()
            if wanted is not None:
                queued = [r for r in queued if r.slot in wanted]
            if queued:
                print(f"[cloud_sync] 另有 {len(queued)} 个时段在待传队列里：")
                for record in queued:
                    print(f"  {record.slot} -> {record.file_name}")
        else:
            export_dir = Path(args.dir)
            exported = 0
            empty = 0
            for slot in slots:
                rows = export_slot(store, ledger, slot, export_dir, now)
                if rows is None:
                    empty += 1
                    continue
                exported += 1
                print(f"[cloud_sync] {file_name_for(slot)}  {rows} 行")
            print(f"[cloud_sync] 导出 {exported} 个时段，跳过 {empty} 个空时段。")

        upload_failures = 0
        pending = ledger.pending_uploads()
        if wanted is not None:
            # 上传侧也要过滤：只导不传会让 --slot 名不副实——用户说的是
            # "只处理这个时段"，不是"只导出这个时段、顺便把别的都传了"。
            pending = [record for record in pending if record.slot in wanted]
        if pending and args.no_upload:
            print(
                f"[cloud_sync] 待上传 {len(pending)} 个时段（--no-upload，本次不传）。"
            )
        elif pending:
            upload_failures = _upload_pending(
                ledger, pending, Path(args.dir), Path(args.oss_config)
            )

        if store.failures or ledger.failures:
            print(f"[cloud_sync] 有失败：{store.last_error or ledger.last_error}")
            return 1
        return 1 if upload_failures else 0
    except OSError as error:
        # 目标目录不可写（U 盘拔了、路径被占、磁盘满）。没登记台账的时段
        # 下次运行会重新导出，所以这里只要如实报错、别登记就够了。
        print(f"[cloud_sync] 写归档失败：{type(error).__name__}: {error}")
        print("[cloud_sync] 未登记的时段会在下次运行时重新导出。")
        return 1
    finally:
        store.close()
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
