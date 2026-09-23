"""归档导出脚本：把历史库按整点切成 CSV，并用台账保证不重复、能补。

设计见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 5.1 节。
第 8 节给 P2 定的两条验收标准，分别由下面两组用例守：

- **导出两次不产生重复文件** → "幂等"一组；
- **断开目标目录后重连能补上** → "目标目录不可写"一组。

还有一条不在验收标准里、但更容易悄悄出错的：**当前这个小时不能导**。
它还在写入，导出会得到半截数据，而台账一旦记了就不会再补——那一小时的
后半段会永久丢失，且没有任何迹象。

`--snapshot`（2026-09-21）是上一条的**受控例外**，见文件末尾那一组。
它的全部安全性系于一件事：**不登记台账**。所以那一组用例里最要紧的不是
"文件写出来了"，而是"台账仍然是空的、那个时段仍然待导出"。
"""

from __future__ import annotations

import codecs
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.cloud_sync import (
    CSV_COLUMNS,
    _wide_rows,
    export_slot,
    export_snapshot,
    file_name_for,
    main,
    pending_slots,
    slot_bounds,
    slot_of,
    snapshot_file_name,
)
from service.history import HistoryPoint
from storage.export_ledger import SqliteExportLedger
from storage.sqlite_history import SqliteHistoryStore

DEVICE = "mcu-1"


def _hour_start(hours_ago: int) -> datetime:
    """若干小时前的整点，本地时区。"""
    local_now = datetime.now().astimezone()
    return (local_now - timedelta(hours=hours_ago)).replace(
        minute=0, second=0, microsecond=0
    )


def _read_csv(path: Path) -> list[list[str]]:
    """读回导出的 CSV。**必须用 utf-8-sig**，否则 BOM 会粘在第一个表头上。"""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def _points_in(hour_start: datetime, count: int = 3) -> list[HistoryPoint]:
    """落在该整点小时内的若干条读数，存的是 UTC（与库一致）。"""
    return [
        HistoryPoint(
            device_id=DEVICE,
            channel="temperature",
            value=25.0 + index,
            timestamp=(hour_start + timedelta(minutes=index)).astimezone(
                timezone.utc
            ),
            valid=True,
        )
        for index in range(count)
    ]


def _prepared(tmp_path: Path, hours_ago: int = 2, count: int = 3):
    """一个装了"若干小时前那一小时"数据的库，外加台账。"""
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    hour_start = _hour_start(hours_ago)
    store.append_many(_points_in(hour_start, count))
    ledger = SqliteExportLedger(database)
    return store, ledger, slot_of(hour_start.astimezone(timezone.utc)), database


# -- 时段切分 ------------------------------------------------------------------


def test_adjacent_slots_do_not_overlap() -> None:
    """闭区间的终点取下一整点减 1 微秒。

    若直接用整点作终点，相邻两个时段都会包含那一瞬间的读数，
    导出的两份文件里各有一条重复记录。
    """
    _, first_end = slot_bounds("20260917_15")
    second_start, _ = slot_bounds("20260917_16")

    assert first_end < second_start
    assert second_start - first_end == timedelta(microseconds=1)


def test_a_slot_covers_exactly_one_hour() -> None:
    start, end = slot_bounds("20260917_15")

    assert end - start == timedelta(hours=1) - timedelta(microseconds=1)


def test_the_file_name_follows_the_documented_pattern() -> None:
    assert file_name_for("20260917_15") == "env_20260917_15.csv"


def test_slot_of_uses_local_time() -> None:
    """时段名要给人看，所以按本地时间取整点；库里仍存 UTC。"""
    moment = datetime(2026, 9, 17, 15, 30, tzinfo=timezone.utc)

    assert slot_of(moment) == moment.astimezone().strftime("%Y%m%d_%H")


# -- 只导已结束的小时 ----------------------------------------------------------


def test_the_current_hour_is_never_pending(tmp_path: Path) -> None:
    """当前小时还在写入，导出它会得到半截数据且再也补不回来。"""
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    store.append_many(_points_in(_hour_start(0)))
    ledger = SqliteExportLedger(database)

    assert pending_slots(store, ledger, datetime.now(timezone.utc)) == []
    store.close()
    ledger.close()


def test_a_finished_hour_is_pending(tmp_path: Path) -> None:
    store, ledger, slot, _ = _prepared(tmp_path)

    assert slot in pending_slots(store, ledger, datetime.now(timezone.utc))
    store.close()
    ledger.close()


def test_an_empty_database_has_nothing_pending(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    ledger = SqliteExportLedger(database)

    assert pending_slots(store, ledger, datetime.now(timezone.utc)) == []
    store.close()
    ledger.close()


def test_an_exported_slot_stops_being_pending(tmp_path: Path) -> None:
    store, ledger, slot, _ = _prepared(tmp_path)
    export_slot(store, ledger, slot, tmp_path / "exports", datetime.now(timezone.utc))

    assert slot not in pending_slots(store, ledger, datetime.now(timezone.utc))
    store.close()
    ledger.close()


# -- 导出的文件内容 ------------------------------------------------------------


def test_the_csv_has_the_documented_columns_and_rows(tmp_path: Path) -> None:
    """2026-09-18 起是宽表：一行一个采集时刻，三通道并列成三列。

    这里的三条读数各隔一分钟、都是温度，所以拆成三轮、每轮只有温度那一格
    有值——正好也验证了缺的通道会在备注里被点名。
    """
    store, ledger, slot, _ = _prepared(tmp_path, count=3)
    export_dir = tmp_path / "exports"

    rows = export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))

    assert rows == 3  # 台账记读数条数，不因换了排版就变
    table = _read_csv(export_dir / file_name_for(slot))
    assert table[0] == CSV_COLUMNS
    assert len(table) == 4  # 表头 + 3 行
    assert table[1][0].startswith("20")  # 时间列
    assert table[1][1] == "25.00"  # 温度，两位小数
    assert table[1][2] == "" and table[1][3] == ""  # 湿度/噪声这一轮没有
    assert table[1][4] == DEVICE
    assert "湿度未上报" in table[1][5] and "噪声未上报" in table[1][5]
    store.close()
    ledger.close()


def test_the_file_starts_with_a_bom_so_excel_reads_chinese(tmp_path: Path) -> None:
    """中文表头必须配 BOM：中文 Windows 上的 Excel 打开无 BOM 的 UTF-8 CSV
    会按 GBK 解，整行表头直接是乱码。本项目两天内已经被 GBK 咬过两次。"""
    store, ledger, slot, _ = _prepared(tmp_path, count=1)
    export_dir = tmp_path / "exports"
    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))

    raw = (export_dir / file_name_for(slot)).read_bytes()

    assert raw.startswith(codecs.BOM_UTF8)
    assert "时间".encode() in raw


def test_the_time_column_is_a_format_excel_understands(tmp_path: Path) -> None:
    """``2026-09-17T21:00:00+08:00`` 这种 ISO 写法 Excel 不认，会当文本
    左对齐，排不了序也画不了图。改成空格分隔、不带时区后缀的本地时间。"""
    store, ledger, slot, _ = _prepared(tmp_path, count=1)
    export_dir = tmp_path / "exports"
    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))

    moment = _read_csv(export_dir / file_name_for(slot))[1][0]

    assert "T" not in moment and "+" not in moment
    # 能被当作本地时刻直接解析回来
    assert datetime.strptime(moment, "%Y-%m-%d %H:%M:%S")
    store.close()
    ledger.close()


def test_an_empty_slot_produces_no_file_and_no_ledger_row(tmp_path: Path) -> None:
    """那个小时没有数据时不写空文件、也不登记。

    登记了的话，将来即使补进数据也不会再导出；而一个 0 行的 CSV
    传上云只是噪声。
    """
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    ledger = SqliteExportLedger(database)
    export_dir = tmp_path / "exports"

    result = export_slot(
        store, ledger, "20260101_00", export_dir, datetime.now(timezone.utc)
    )

    assert result is None
    assert not (export_dir / "env_20260101_00.csv").exists()
    assert ledger.all_records() == []
    store.close()
    ledger.close()


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    """先写 .tmp 再改名，成功后不该留下中间文件。"""
    store, ledger, slot, _ = _prepared(tmp_path)
    export_dir = tmp_path / "exports"

    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))

    assert list(export_dir.glob("*.tmp")) == []
    store.close()
    ledger.close()


# -- 幂等：导出两次不产生重复文件（P2 验收标准之一） ----------------------------


def test_exporting_the_same_slot_twice_keeps_one_ledger_row(tmp_path: Path) -> None:
    store, ledger, slot, _ = _prepared(tmp_path)
    export_dir = tmp_path / "exports"
    now = datetime.now(timezone.utc)

    export_slot(store, ledger, slot, export_dir, now)
    export_slot(store, ledger, slot, export_dir, now)

    assert len(ledger.all_records()) == 1
    assert len(list(export_dir.glob("env_*.csv"))) == 1
    store.close()
    ledger.close()


def test_running_the_whole_script_twice_exports_nothing_the_second_time(
    tmp_path: Path,
) -> None:
    """整脚本跑两遍：第二遍应当无事可做。"""
    _, _, _, database = _prepared(tmp_path)
    export_dir = tmp_path / "exports"
    argv = ["--db", str(database), "--dir", str(export_dir)]

    assert main(argv) == 0
    first = sorted(path.name for path in export_dir.glob("*.csv"))
    assert main(argv) == 0
    second = sorted(path.name for path in export_dir.glob("*.csv"))

    assert first == second
    assert len(first) == 1


# -- 目标目录不可写：断开后重连能补上（P2 验收标准之二） ------------------------


def test_an_unwritable_target_is_reported_and_not_recorded(tmp_path: Path) -> None:
    """导出目录被一个同名文件占住，写入必然失败。

    关键不是"报错"，而是**没有登记台账**——否则那个时段就被当成
    导过了，再也不会补。
    """
    _, _, _, database = _prepared(tmp_path)
    blocked = tmp_path / "exports"
    blocked.write_text("我是一个文件，不是目录", encoding="utf-8")

    assert main(["--db", str(database), "--dir", str(blocked)]) == 1

    ledger = SqliteExportLedger(database)
    assert ledger.all_records() == []
    ledger.close()


def test_the_slot_is_exported_once_the_target_comes_back(tmp_path: Path) -> None:
    """把目录恢复之后再跑一次，刚才没导成的时段应当补上。

    这正是 P2 的验收标准"断开目标目录后重连能补上"。
    """
    _, _, slot, database = _prepared(tmp_path)
    blocked = tmp_path / "exports"
    blocked.write_text("占位", encoding="utf-8")
    argv = ["--db", str(database), "--dir", str(blocked)]
    assert main(argv) == 1

    blocked.unlink()  # 目录"恢复"

    assert main(argv) == 0
    assert (blocked / file_name_for(slot)).exists()
    ledger = SqliteExportLedger(database)
    assert [record.slot for record in ledger.all_records()] == [slot]
    ledger.close()


# -- 命令行 --------------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    """--dry-run 只说会导什么，不碰文件，也不登记。"""
    _, _, _, database = _prepared(tmp_path)
    export_dir = tmp_path / "exports"

    assert main(
        ["--db", str(database), "--dir", str(export_dir), "--dry-run"]
    ) == 0

    assert not export_dir.exists()
    ledger = SqliteExportLedger(database)
    assert ledger.all_records() == []
    ledger.close()


def test_a_missing_database_is_a_readable_failure(tmp_path: Path) -> None:
    """库不存在时给出可读的原因并返回 1，而不是抛栈。"""
    assert main(["--db", str(tmp_path / "nope.sqlite")]) == 1


# -- 上传（P3） ----------------------------------------------------------------


class _StubUploader:
    """假上传器。构造参数与真的一致，行为由类属性决定。"""

    succeed = True
    seen: list[str] = []

    def __init__(self, config: object) -> None:
        self._config = config

    @property
    def destination(self) -> str:
        return "oss://stub/prefix/"

    @property
    def last_error(self) -> str:
        return "stubbed failure"

    @property
    def last_reason(self) -> str:
        """2026-09-19 起真上传器多了这一项（给人看的一句话原因）。
        桩要跟着补，否则失败路径一走就 AttributeError——而失败路径正是
        断网演示会走的那一条。"""
        return "打桩的失败原因"

    def upload(self, file_path: Path) -> bool:
        type(self).seen.append(Path(file_path).name)
        return type(self).succeed


def _stub_upload(monkeypatch, *, succeed: bool = True) -> type[_StubUploader]:
    """把 cloud_sync 里的上传器与配置读取换成假的，不碰网络。"""
    import scripts.cloud_sync as module

    _StubUploader.succeed = succeed
    _StubUploader.seen = []
    monkeypatch.setattr(module, "OssUploader", _StubUploader)
    monkeypatch.setattr(module, "load_config", lambda path: object())
    return _StubUploader


def test_no_upload_leaves_the_queue_alone(tmp_path: Path, monkeypatch) -> None:
    """--no-upload 是现场没网时的退路：照常导出，一个字节也不往外发。"""
    _, _, slot, database = _prepared(tmp_path)
    stub = _stub_upload(monkeypatch)

    assert main(
        ["--db", str(database), "--dir", str(tmp_path / "exports"), "--no-upload"]
    ) == 0

    assert stub.seen == []
    ledger = SqliteExportLedger(database)
    assert [record.slot for record in ledger.pending_uploads()] == [slot]
    ledger.close()


def test_a_missing_oss_config_is_not_a_failure(tmp_path: Path) -> None:
    """还没配 OSS 时照常导出、正常退出，队列留着等配好再传。"""
    _, _, slot, database = _prepared(tmp_path)

    assert main([
        "--db", str(database),
        "--dir", str(tmp_path / "exports"),
        "--oss-config", str(tmp_path / "nope.json"),
    ]) == 0

    ledger = SqliteExportLedger(database)
    assert [record.slot for record in ledger.pending_uploads()] == [slot]
    ledger.close()


def test_a_successful_upload_marks_the_ledger(tmp_path: Path, monkeypatch) -> None:
    _, _, slot, database = _prepared(tmp_path)
    stub = _stub_upload(monkeypatch, succeed=True)

    assert main(["--db", str(database), "--dir", str(tmp_path / "exports")]) == 0

    assert stub.seen == [file_name_for(slot)]
    ledger = SqliteExportLedger(database)
    assert ledger.pending_uploads() == []
    assert ledger.all_records()[0].is_uploaded is True
    ledger.close()


def test_a_failed_upload_leaves_it_in_the_queue(tmp_path: Path, monkeypatch) -> None:
    """传失败不标记台账——下次运行自然重传。

    这就是 P3 验收标准"断网后恢复能补传"：不需要重试循环与退避，
    重试的时机由人决定（下次双击）。
    """
    _, _, slot, database = _prepared(tmp_path)
    _stub_upload(monkeypatch, succeed=False)

    assert main(["--db", str(database), "--dir", str(tmp_path / "exports")]) == 1

    ledger = SqliteExportLedger(database)
    assert [record.slot for record in ledger.pending_uploads()] == [slot]
    ledger.close()


def test_the_retry_succeeds_once_the_network_comes_back(
    tmp_path: Path, monkeypatch
) -> None:
    """断网那次失败，恢复后再跑一次就补传上了——整条补传路径的端到端验证。"""
    _, _, slot, database = _prepared(tmp_path)
    argv = ["--db", str(database), "--dir", str(tmp_path / "exports")]

    _stub_upload(monkeypatch, succeed=False)
    assert main(argv) == 1

    stub = _stub_upload(monkeypatch, succeed=True)
    assert main(argv) == 0

    assert stub.seen == [file_name_for(slot)]
    ledger = SqliteExportLedger(database)
    assert ledger.pending_uploads() == []
    ledger.close()


def test_a_deleted_archive_is_skipped_rather_than_marked(
    tmp_path: Path, monkeypatch
) -> None:
    """归档被手工删了：跳过、不标记、也不算失败。

    台账仍记着这一段导出过，所以它不会被自动重导——这一点由脚本明确
    打印出来，而不是替人做删台账的决定。
    """
    _, _, slot, database = _prepared(tmp_path)
    export_dir = tmp_path / "exports"
    main(["--db", str(database), "--dir", str(export_dir), "--no-upload"])
    (export_dir / file_name_for(slot)).unlink()
    stub = _stub_upload(monkeypatch, succeed=True)

    assert main(["--db", str(database), "--dir", str(export_dir)]) == 0

    assert stub.seen == []
    ledger = SqliteExportLedger(database)
    assert [record.slot for record in ledger.pending_uploads()] == [slot]
    ledger.close()


def test_exported_slots_start_out_pending_upload(tmp_path: Path) -> None:
    """导出完不等于上云。台账里 uploaded_at 为空的就是待发队列，
    P3 接上传时直接用它。"""
    _, _, slot, database = _prepared(tmp_path)
    main(["--db", str(database), "--dir", str(tmp_path / "exports")])

    ledger = SqliteExportLedger(database)
    assert [record.slot for record in ledger.pending_uploads()] == [slot]
    ledger.close()


# -- 宽表的分轮与备注（2026-09-18） --------------------------------------------


def _reading(micros: int, channel: str, value: float, *, device: str = DEVICE,
             valid: bool = True) -> HistoryPoint:
    base = datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc)
    return HistoryPoint(
        device_id=device,
        channel=channel,
        value=value,
        timestamp=base + timedelta(microseconds=micros),
        valid=valid,
    )


def test_one_round_becomes_one_row() -> None:
    """依据是实测：同一轮内三个通道相差约 2 毫秒，轮与轮相差约 3 秒，
    差一千五百倍，所以 500 毫秒的阈值离两边都有两个数量级余量。"""
    rows = _wide_rows([
        _reading(0, "temperature", 27.45),
        _reading(1444, "humidity", 57.35),
        _reading(1834, "noise", 44.7),
        _reading(3_000_000, "temperature", 27.44),
        _reading(3_001_444, "humidity", 57.35),
        _reading(3_001_834, "noise", 40.7),
    ])

    assert len(rows) == 2
    assert rows[0][1:4] == ["27.45", "57", "44.70"]
    assert rows[1][1:4] == ["27.44", "57", "40.70"]


def test_a_repeated_channel_starts_a_new_round() -> None:
    """只按时间间隔切是不够的：某一轮只有噪声、下一轮紧接着也只有噪声时，
    间隔规则会把两条并成一行，直接丢掉一条读数。"""
    rows = _wide_rows([
        _reading(0, "noise", 44.0),
        _reading(100_000, "noise", 45.0),  # 才隔 100 毫秒，但通道重复了
    ])

    assert len(rows) == 2
    assert rows[0][3] == "44.00" and rows[1][3] == "45.00"


def test_a_dropped_channel_leaves_the_cell_empty_and_says_which() -> None:
    """**这正是宽表敢做的理由**：每条读数都带时间戳，缺的那一格就空着，
    不会被下一轮的值顶上去。空格看得见"这里没数"，备注才说得出"没的是哪条"。"""
    rows = _wide_rows([
        _reading(0, "temperature", 27.4),
        _reading(1444, "humidity", 57.0),
    ])

    assert rows[0][3] == ""
    assert "噪声未上报" in rows[0][5]


def test_an_invalid_reading_is_not_put_in_the_value_column() -> None:
    """固件在 Modbus 读失败时压根不报噪声，所以真到了的无效读数是链路质量的
    证据，不能丢；但把一个不可信的数字放进数值列，它会被照样画进曲线里。

    它也**不算"未上报"**——那一帧到了，只是数不可信。两者在备注里必须分得开，
    否则读的人无法判断是链路断了还是传感器读坏了。"""
    rows = _wide_rows([
        _reading(0, "temperature", 27.4),
        _reading(1444, "noise", 999.9, valid=False),
    ])

    assert rows[0][3] == ""
    assert "噪声读数无效（原值 999.9）" in rows[0][5]
    assert "噪声未上报" not in rows[0][5]


def test_a_channel_outside_the_three_columns_still_leaves_a_trace() -> None:
    """平台不枚举通道。列是固定的三条，但第四条通道不能因此被悄悄丢掉。"""
    rows = _wide_rows([
        _reading(0, "temperature", 27.4),
        _reading(1444, "pressure", 101.3),
    ])

    assert "pressure 101.3" in rows[0][5]


def test_several_devices_in_one_round_collapse_to_a_shared_prefix() -> None:
    """模拟器模式下三条通道各挂一台设备，逐行写全名会在每行重复四十多个
    字符——而这次改版要去掉的正是这种噪声。"""
    rows = _wide_rows([
        _reading(0, "temperature", 24.0, device="sim-env-1-temp"),
        _reading(1444, "humidity", 58.0, device="sim-env-1-humi"),
        _reading(1834, "noise", 47.0, device="sim-env-1-noise"),
    ])

    assert rows[0][4] == "sim-env-1-*"


def test_unrelated_devices_are_listed_in_full_not_merged() -> None:
    """宁可长，也不能把两台不相干的设备并成一个名字。"""
    rows = _wide_rows([
        _reading(0, "temperature", 24.0, device="alpha"),
        _reading(1444, "humidity", 58.0, device="beta"),
    ])

    assert rows[0][4] == "alpha、beta"


def test_decimals_follow_the_shared_channel_convention() -> None:
    """与界面、手机端共用 core.channel_display 的同一份定义：
    温度噪声两位、湿度整数（AHT20 湿度精度 ±2 %RH，写小数是虚假精度）。"""
    rows = _wide_rows([
        _reading(0, "temperature", 27.444444),
        _reading(1444, "humidity", 57.35),
        _reading(1834, "noise", 44.7),
    ])

    assert rows[0][1:4] == ["27.44", "57", "44.70"]


# -- --slot：只处理指定时段（2026-09-19） -------------------------------------


def test_slot_limits_both_export_and_upload(tmp_path: Path, monkeypatch) -> None:
    """--slot 说的是"只处理这个时段"，不是"只导出这个、顺便把别的都传了"。
    导出与上传两侧都要过滤，否则演示时按一下会把积压的全发出去。"""
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    first = _hour_start(3)
    second = _hour_start(2)
    store.append_many(_points_in(first, 2))
    store.append_many(_points_in(second, 2))
    export_dir = tmp_path / "exports"
    slot_two = slot_of(second.astimezone(timezone.utc))

    code = main(
        ["--db", str(database), "--dir", str(export_dir), "--no-upload",
         "--slot", slot_two]
    )

    assert code == 0
    written = sorted(p.name for p in export_dir.glob("*.csv"))
    assert written == [file_name_for(slot_two)]
    store.close()


def test_an_unknown_slot_is_an_error_not_a_silent_no_op(tmp_path: Path) -> None:
    """拼错时段名的表现会是"什么都没发生"——与"这些都传过了"看起来一模一样。
    宁可直接报错退出，否则演示时按下去没反应，没人知道是拼错了还是传完了。"""
    store, _, _, database = _prepared(tmp_path, count=2)
    store.close()

    code = main(
        ["--db", str(database), "--dir", str(tmp_path / "exports"),
         "--no-upload", "--slot", "20260101_99"]
    )

    assert code == 1


def test_several_slots_can_be_given(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    hours = [_hour_start(n) for n in (4, 3, 2)]
    for h in hours:
        store.append_many(_points_in(h, 2))
    export_dir = tmp_path / "exports"
    picked = [slot_of(h.astimezone(timezone.utc)) for h in hours[:2]]

    main(["--db", str(database), "--dir", str(export_dir), "--no-upload",
          *sum([["--slot", s] for s in picked], [])])

    assert sorted(p.name for p in export_dir.glob("*.csv")) == sorted(
        file_name_for(s) for s in picked
    )
    store.close()


def test_dry_run_also_lists_what_is_queued_for_upload(tmp_path: Path) -> None:
    """演示前要确认的是"按下去会发生什么"，而待传队列与待导出是两件事——
    上一次断网留下的积压不会出现在"待导出"那张表里。"""
    store, ledger, slot, database = _prepared(tmp_path, count=2)
    export_dir = tmp_path / "exports"
    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))
    store.close()
    ledger.close()

    code = main(["--db", str(database), "--dir", str(export_dir), "--dry-run"])

    assert code == 0


# -- 当前时段快照（2026-09-21） ------------------------------------------------


def _with_current_hour(tmp_path: Path, count: int = 4):
    """一个只有"当前这一小时"数据的库，外加**截取时刻**。

    刻意不放已结束时段的数据：快照那一组要验的是"当前小时"这条路，
    混进待导出的时段会让"台账为空"这个断言失去意义。

    **为什么要把截取时刻一起返回，而不是让用例各自取 `datetime.now()`。**
    第一版就是那么写的，写的时候是 09:42，四条读数按"整点 + 0/1/2/3 分钟"
    摆在 09:00–09:03，`now` 是 09:42，全落在区间里，绿。**而它在每小时的
    前几分钟必然失败**——09:53 改完代码再跑，时间已是 10:0x，`now` 只到
    10:01，四条里只覆盖得到一条，`assert count == 4` 当场变成 `1 == 4`。
    快照的区间是"这一小时开头到此刻"，所以**用例不能同时让读数位置和此刻
    都跟着挂钟走**。现在读数按秒摆在整点之后，截取时刻取 `整点 + count 秒`，
    与挂钟无关。

    残留的一处竞态无法消除也不必消除：若恰在整点前一秒开跑，跑的过程中
    小时翻页，这一小时就成了"已结束"。既有用例用 `_hour_start(2)` 绕开它，
    而"当前小时"这条路按定义绕不开。
    """
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    hour_start = _hour_start(0)
    points = [
        HistoryPoint(
            device_id=DEVICE,
            channel="temperature",
            value=25.0 + index,
            timestamp=(hour_start + timedelta(seconds=index)).astimezone(
                timezone.utc
            ),
            valid=True,
        )
        for index in range(count)
    ]
    store.append_many(points)
    ledger = SqliteExportLedger(database)
    moment = hour_start + timedelta(seconds=count)
    return store, ledger, database, moment


def test_a_snapshot_covers_the_unfinished_current_hour(tmp_path: Path) -> None:
    """常规导出永远碰不到这一小时，快照必须能碰到——这就是它存在的理由。"""
    store, ledger, _, now = _with_current_hour(tmp_path, count=4)

    assert pending_slots(store, ledger, datetime.now(timezone.utc)) == []

    result = export_snapshot(store, tmp_path / "exports", now)

    assert result is not None
    target, count = result
    assert count == 4
    assert target.is_file()
    store.close()
    ledger.close()


def test_a_snapshot_leaves_the_ledger_untouched(tmp_path: Path) -> None:
    """**这一条是快照整套设计的地基。**

    台账是"这个时段已经归档、不必再导"的唯一依据，而快照按定义是半截的。
    记进去就等于宣布那一小时处理完了，后半段的读数会永久留在库里不再导出，
    而且没有任何提示——正是文件开头那条"当前小时不能导"要防的事。
    所以整点过后，这一小时仍然必须是"待导出"。
    """
    store, ledger, _, now = _with_current_hour(tmp_path)

    export_snapshot(store, tmp_path / "exports", now)

    assert ledger.all_records() == []
    # 把"现在"推到下一个整点之后：那一小时结束了，它必须重新出现在待导出里。
    later = (now + timedelta(hours=1)).astimezone(timezone.utc)
    assert slot_of(now.astimezone(timezone.utc)) in pending_slots(store, ledger, later)
    store.close()
    ledger.close()


def test_a_snapshot_file_name_says_it_is_a_snapshot(tmp_path: Path) -> None:
    """清单里它会与同一小时的整点归档并排显示，而看清单的人不会逐个打开。
    "这是半截数据"必须在名字上看得见。"""
    moment = _hour_start(0) + timedelta(minutes=35)
    name = snapshot_file_name(slot_of(moment.astimezone(timezone.utc)), moment)

    assert name.endswith("_快照.csv")
    assert f"{moment:%H%M}" in name
    assert name != file_name_for(slot_of(moment.astimezone(timezone.utc)))


def test_two_snapshots_in_the_same_minute_overwrite_rather_than_pile_up(
    tmp_path: Path,
) -> None:
    """同一分钟内的两份快照没有区别，留两份只是清单噪声。
    跨分钟就该各留一份——所以这里验的是"同一分钟"这个条件本身。"""
    moment = _hour_start(0) + timedelta(minutes=12)
    slot = slot_of(moment.astimezone(timezone.utc))

    same = snapshot_file_name(slot, moment)
    later = snapshot_file_name(slot, moment + timedelta(seconds=30))
    next_minute = snapshot_file_name(slot, moment + timedelta(minutes=1))

    assert same == later
    assert same != next_minute


def test_a_current_hour_with_no_readings_yields_no_snapshot(tmp_path: Path) -> None:
    """库里可能有大量昨天的数据而这一小时一条都没有。不产生空文件。"""
    database = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(database)
    store.append_many(_points_in(_hour_start(5), 3))

    now = datetime.now().astimezone()
    assert export_snapshot(store, tmp_path / "exports", now) is None
    assert not (tmp_path / "exports").exists()
    store.close()


def test_the_snapshot_csv_has_the_same_columns_as_an_archive(tmp_path: Path) -> None:
    """同一份表头、同一套小数位。两种文件会被并排看、被前后拼起来，
    列对不齐就白做了——这也是抽出 `_write_csv` 的目的。"""
    store, ledger, _, now = _with_current_hour(tmp_path, count=2)

    result = export_snapshot(store, tmp_path / "exports", now)

    assert result is not None
    rows = _read_csv(result[0])
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 1 + 2
    store.close()
    ledger.close()


def test_the_snapshot_file_starts_with_a_bom_too(tmp_path: Path) -> None:
    """快照与归档一样要被 Excel 打开。少了 BOM 中文表头就是乱码。"""
    store, ledger, _, now = _with_current_hour(tmp_path, count=1)

    result = export_snapshot(store, tmp_path / "exports", now)

    assert result is not None
    assert result[0].read_bytes().startswith(codecs.BOM_UTF8)
    store.close()
    ledger.close()


def test_snapshot_via_main_writes_a_file_and_exits_zero(tmp_path: Path) -> None:
    """走 `main` 这一路，因为按钮与 .bat 都是从这里进来的。"""
    store, ledger, database, _ = _with_current_hour(tmp_path, count=3)
    store.close()
    ledger.close()
    export_dir = tmp_path / "exports"

    code = main(
        ["--db", str(database), "--dir", str(export_dir), "--snapshot", "--no-upload"]
    )

    assert code == 0
    snapshots = list(export_dir.glob("*_快照.csv"))
    assert len(snapshots) == 1


def test_snapshot_dry_run_writes_nothing(tmp_path: Path) -> None:
    """演示前要能先看一眼会发生什么，而不是先产生一个文件。"""
    store, ledger, database, _ = _with_current_hour(tmp_path, count=3)
    store.close()
    ledger.close()
    export_dir = tmp_path / "exports"

    code = main(
        ["--db", str(database), "--dir", str(export_dir), "--snapshot", "--dry-run"]
    )

    assert code == 0
    assert not export_dir.exists()


def test_without_the_flag_nothing_touches_the_current_hour(tmp_path: Path) -> None:
    """默认行为必须一字不变：无人值守跑这个脚本的仍然只该拿到整点归档。"""
    store, ledger, database, _ = _with_current_hour(tmp_path, count=3)
    store.close()
    ledger.close()
    export_dir = tmp_path / "exports"

    code = main(["--db", str(database), "--dir", str(export_dir), "--no-upload"])

    assert code == 0
    written = list(export_dir.glob("*.csv")) if export_dir.exists() else []
    assert written == []


# -- --dry-run 必须真的什么都不做（2026-09-21 修的真实缺陷） -------------------


def test_dry_run_does_not_upload_a_queued_archive(tmp_path, monkeypatch) -> None:
    """**实测撞到过的真缺陷。**

    `--dry-run` 原先只管"不写文件"，它下面的上传块是无条件执行的。于是
    演示前"先看一眼会发生什么"，把上一次留在待发队列里的归档真的传上了
    OSS——桶里凭空多一个文件，全程无报错，输出里那句"已上传"看着还像好事。

    这里不靠"有没有凭证"来蒙对：凭证存在时才会走到上传，所以必须把
    `_upload_pending` 换成哨兵，断言它压根没被调用。
    """
    from scripts import cloud_sync as module

    store, ledger, slot, database = _prepared(tmp_path, count=2)
    export_dir = tmp_path / "exports"
    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))
    store.close()
    ledger.close()

    calls: list[object] = []
    monkeypatch.setattr(
        module, "_upload_pending", lambda *a, **k: calls.append(a) or 0
    )

    code = main(["--db", str(database), "--dir", str(export_dir), "--dry-run"])

    assert code == 0
    assert calls == []


def test_dry_run_lists_the_queue_even_when_nothing_is_left_to_export(
    tmp_path, capsys
) -> None:
    """都导过了的时候，队列里可能正积压着没传上去的——那恰好是最需要
    先看一眼的处境，而原先这一支只说一句"没有待导出的时段"就完事。"""
    store, ledger, slot, database = _prepared(tmp_path, count=2)
    export_dir = tmp_path / "exports"
    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))
    store.close()
    ledger.close()

    main(["--db", str(database), "--dir", str(export_dir), "--dry-run"])

    printed = capsys.readouterr().out
    assert "待传队列" in printed
    assert slot in printed


def test_dry_run_with_snapshot_uploads_nothing_either(tmp_path, monkeypatch) -> None:
    """快照那一路也不能例外。"""
    from scripts import cloud_sync as module

    store, ledger, database, _ = _with_current_hour(tmp_path, count=3)
    store.close()
    ledger.close()
    calls: list[object] = []
    monkeypatch.setattr(
        module, "_upload_snapshot", lambda *a, **k: calls.append(a) or 0
    )

    code = main(
        ["--db", str(database), "--dir", str(tmp_path / "exports"), "--snapshot",
         "--dry-run"]
    )

    assert code == 0
    assert calls == []


def test_no_dry_run_path_can_even_construct_an_uploader(
    tmp_path, monkeypatch
) -> None:
    """**把"`--dry-run` 不具备上传能力"钉成结构性事实，而不是逐条堵。**

    前面三条守的是"没走上传函数"。这一条更狠：把 `OssUploader` 换成一个
    造出来就炸的东西，然后把 `--dry-run` 的各种组合都跑一遍。只要哪条路
    还能摸到上传器，用例就当场抛异常。

    为什么值得多加这一条：2026-09-21 那个缺陷的形态不是"上传逻辑写错了"，
    而是**上传块压根没被 dry-run 管住**——它在 dry-run 分支的下面，无条件执行。
    逐条堵的写法挡不住下一次在 `main()` 末尾再加一段带副作用的代码；
    这一条能，因为它不关心副作用长什么样，只钉住"这条路上不存在上传器"。
    """
    from scripts import cloud_sync as module

    class _Explodes:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("--dry-run 竟然造出了上传器")

    monkeypatch.setattr(module, "OssUploader", _Explodes)

    # **必须给一份能读通的凭证文件。** conftest 的 autouse fixture 把
    # `DEFAULT_CONFIG_PATH` 指到一个不存在的文件上（对的，那是防止拿真密钥
    # 连公网），于是 `load_config()` 返回 None，脚本在造上传器**之前**就说
    # "未配置 OSS"退回去了——第一版这条用例因此在把修复整段删掉之后**照样通过**，
    # 等于什么都没守。踩到的经过记在这里，因为"哨兵没被触发"与"代码是对的"
    # 在输出上一模一样，正是本项目反复栽的那一类。
    config = tmp_path / "oss_config.json"
    config.write_text(
        json.dumps(
            {
                "endpoint": "oss-cn-hangzhou.aliyuncs.com",
                "bucket": "not-a-real-bucket",
                "access_key_id": "not-a-real-key",
                "access_key_secret": "not-a-real-secret",
                "prefix": "env-monitor/",
            }
        ),
        encoding="utf-8",
    )
    base = ["--db", "", "--dir", "", "--oss-config", str(config)]

    # 三种处境：有待导出的、都导过但队列非空的、以及快照那一路。
    store, ledger, slot, database = _prepared(tmp_path, count=2)
    export_dir = tmp_path / "exports"
    base[1], base[3] = str(database), str(export_dir)
    assert main([*base, "--dry-run"]) == 0
    export_slot(store, ledger, slot, export_dir, datetime.now(timezone.utc))
    store.close()
    ledger.close()
    assert main([*base, "--dry-run"]) == 0
    assert main([*base, "--dry-run", "--snapshot"]) == 0
