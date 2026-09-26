/* views.js —— 四个视图：监测、串口链路、环境问答、历史。
 * 视图只读 EHP.Store.state，动作经当前数据源（EHP.source）发出。 */
(function () {
  "use strict";
  const EHP = window.EHP;
  const { $, el, esc, fmt, Store } = EHP;

  const INTENTS = {
    CURRENT_VALUE: "当前读数", MINIMUM: "最小值", MAXIMUM: "最大值", AVERAGE: "平均值",
    ALARM_STATE: "报警状态", THRESHOLD_INFO: "阈值", FAN_STATE: "风扇状态", DEVICE_LIST: "设备列表",
    HELP: "帮助", BARE_SWITCH: "未点明对象的开关", ANNOUNCE_REQUEST: "语音播报请求",
    CLOUD_SYNC_HINT: "上云", CLOUD_VIEW_HINT: "查看云端", DELETE_REQUEST: "删除请求",
    FAN_ON: "开风扇", FAN_OFF: "关风扇", FAN_AUTO: "风扇交给自动", SET_VENT_THRESHOLD: "设置通风阈值",
  };
  const FACT_LABELS = {
    kind: "类型", available: "有数据", channel: "通道", channel_label: "通道名", unit: "单位",
    value: "当前值", minimum: "最低", maximum: "最高", average: "平均", sample_count: "采样点数",
    threshold: "阈值", citation: "阈值依据", threshold_is_maximum: "高于即报警",
    threshold_low: "下限", threshold_high: "上限", triggered: "是否越限", margin: "距阈值",
    applied: "已执行", fan_mode: "风扇模式", fan_running: "风扇运行",
  };

  // ============================================================ 监测
  let liveChart = null;

  // 一把尺子上画出：本次记录的最低—最高区间、当前值、报警阈值。
  // 量程取这几个数的并集再各留一点余量，所以阈值总在尺子上，离它多远一眼可见。
  function scaleOf(ch, meta, value) {
    const st = ch.stats, bounds = Object.entries(ch.bounds || {});
    if (value == null || !bounds.length) return null;
    const vals = [value, st && st.minimum, st && st.maximum, ...bounds.map(([, v]) => v)].filter(Number.isFinite);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    const pos = (v) => ((v - lo) / (hi - lo)) * 100;
    const kids = [el("div", { class: "track" })];
    if (st && Number.isFinite(st.minimum) && Number.isFinite(st.maximum)) {
      kids.push(el("div", { class: "band", style: `left:${pos(st.minimum)}%;width:${Math.max(pos(st.maximum) - pos(st.minimum), 0.8)}%` }));
    }
    for (const [kind, v] of bounds) {
      const p = pos(v);
      kids.push(el("div", { class: "limit" + (p > 85 ? " edge-r" : p < 15 ? " edge-l" : ""), style: `left:${p}%` },
        el("span", { text: `${kind === "BELOW_MIN" ? "下限" : "上限"} ${v}` })));
    }
    kids.push(el("div", { class: "now", style: `left:${pos(value)}%`, title: `当前 ${fmt(value, meta.dp)}` }));
    // 离最近的那道阈值还有多远；已越过时说越过了多少
    const gaps = bounds.map(([kind, v]) => ({ kind, gap: kind === "BELOW_MIN" ? value - v : v - value }));
    const near = gaps.reduce((a, b) => (b.gap < a.gap ? b : a));
    const side = near.kind === "BELOW_MIN" ? "下限" : "上限";
    const note = near.gap < 0
      ? `已越过${side} <b>${fmt(-near.gap, meta.dp)}</b> ${esc(ch.unit)}`
      : `距${side}还有 <b>${fmt(near.gap, meta.dp)}</b> ${esc(ch.unit)}`;
    return [el("div", { class: "scale", "aria-hidden": "true" }, ...kids), el("div", { class: "margin-note", html: note })];
  }

  function renderCards(s) {
    const box = $("#cards");
    box.replaceChildren(...EHP.CHANNEL_ORDER.map((c) => {
      const ch = s.channels[c], meta = EHP.CHANNELS[c];
      const last = ch.points[ch.points.length - 1];
      const alarm = EHP.alarmOf(ch);
      const st = ch.stats;
      let pill;
      const side = alarm && alarm.kind === "BELOW_MIN" ? "下限" : "上限";
      if (!alarm) pill = el("span", { class: "pill idle", text: "等待判定" });
      else if (alarm.triggered) {
        pill = el("span", { class: "pill bad", text: `${alarm.kind === "BELOW_MIN" ? "低于" : "高于"}${side} ${alarm.threshold}` });
      } else {
        pill = el("span", { class: "pill ok", text: `正常 · ${side} ${alarm.threshold}` });
      }
      return el("div", { class: "card" + (alarm && alarm.triggered ? " alarm" : "") },
        el("div", { class: "top" }, el("span", { class: "label", text: meta.label }), pill),
        el("div", { class: "value", html: last ? `${fmt(last[1], meta.dp)}<small>${esc(ch.unit)}</small>` : "—" }),
        ...(scaleOf(ch, meta, last ? last[1] : null) || []),
        el("div", { class: "stats" },
          ...[["最低", st && st.minimum], ["平均", st && st.average], ["最高", st && st.maximum], ["点数", st && st.sample_count]]
            .map(([k, v]) => el("span", { html: `${k}<b>${v == null ? "—" : k === "点数" ? v : fmt(v, meta.dp)}</b>` }))));
    }));
  }

  function renderLiveChart(s) {
    if (!liveChart) liveChart = EHP.timeChart($("#c-live"), {});
    let tmax = 0, tmin = Infinity;
    for (const c of EHP.CHANNEL_ORDER) {
      const pts = s.channels[c].points;
      if (pts.length) { tmax = Math.max(tmax, pts[pts.length - 1][0]); tmin = Math.min(tmin, pts[0][0]); }
    }
    // 最近 10 分钟；数据还不满 10 分钟时从第一个点画起，不留大片空白。
    const span = 10 * 60 * 1000;
    const t0 = Math.max(tmax - span, Math.min(tmin, tmax - 60 * 1000));
    liveChart.update({
      window: [t0, tmax],
      emptyText: EHP.source && EHP.source.kind === "replay" && EHP.source.session === "faults"
        ? "故障注入会话只录了链路事件，请到「串口链路」查看" : "还没有收到读数",
      panels: EHP.CHANNEL_ORDER.map((c) => {
        const ch = s.channels[c];
        return {
          name: EHP.CHANNELS[c].label, unit: ch.unit, dp: EHP.CHANNELS[c].dp, series: ch.points,
          refs: Object.entries(ch.bounds).map(([kind, v]) => ({ v, label: `${kind === "BELOW_MIN" ? "下限" : "报警"} ${v}` })),
        };
      }),
    });
  }

  function renderFan(s) {
    const { settings, decision } = s.fan;
    const mode = (decision && decision.mode) || (settings && settings.mode);
    $("#fan-mode").textContent = mode ? EHP.MODES[mode] || mode : "—";
    $("#fan-mode").className = "pill " + (mode === "AUTO" ? "ok" : mode ? "warn" : "idle");
    $("#fan-run").textContent = decision ? (decision.should_run ? "运行中" : "停止") : "等待判定";
    $("#fan-reason").textContent = decision ? decision.reason : "";
    document.querySelectorAll("#fan-modes button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
    const control = EHP.source && EHP.source.capabilities.control;
    document.querySelectorAll("#fan-modes button, #fan-form button, #fan-form input").forEach((n) => { n.disabled = !control; });
    if (settings) {
      const t = $("#th-temp"), h = $("#th-humi");
      if (document.activeElement !== t) t.value = settings.temperature_max;
      if (document.activeElement !== h) h.value = settings.humidity_max;
    }
    if (!control && EHP.source) $("#fan-toast").textContent = "回放模式下只读：连接网关后才能控制风扇。";
  }

  function linkCounts(s) {
    const srv = s.link.serverStats;
    if (srv && EHP.source && EHP.source.kind === "live") {
      return { bytes: srv.bytes_received, frame: srv.frames, resync: srv.resyncs, checksum_error: srv.checksum_errors,
               decode_error: srv.decode_errors, ignored: srv.ignored, payload_error: srv.payload_errors };
    }
    return Object.assign({ bytes: s.link.bytes }, s.link.counts);
  }

  function renderDevices(s) {
    $("#mode-label").textContent = s.mode ? `模式：${s.mode}` : "";
    $("#devices").replaceChildren(...(s.devices.length ? s.devices.map((d) => el("li", {},
      el("span", { class: "mono", text: d.device_id }),
      el("span", { class: "pill " + (d.is_connected === false ? "bad" : "ok"), text: d.is_connected === false ? "未连接" : "已连接" })))
      : [el("li", { class: "hint", text: "暂无设备" })]));
    const c = linkCounts(s);
    const rows = s.link.active
      ? [["收到字节", c.bytes], ["正常帧", c.frame], ["重同步", c.resync], ["CRC 失败", c.checksum_error]]
      : [["串口字节流", "无（仿真模式）"]];
    $("#link-mini").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: String(v) })]));
  }

  async function onFanMode(mode) {
    const toast = $("#fan-toast");
    try { await EHP.source.setMode(mode); toast.className = "toast"; toast.textContent = `已切换为${EHP.MODES[mode]}`; }
    catch (e) { toast.className = "toast err"; toast.textContent = e.message; }
  }
  async function onFanForm(ev) {
    ev.preventDefault();
    const toast = $("#fan-toast");
    const t = parseFloat($("#th-temp").value), h = parseFloat($("#th-humi").value);
    try {
      await EHP.source.setThresholds(Number.isFinite(t) ? t : null, Number.isFinite(h) ? h : null);
      toast.className = "toast"; toast.textContent = "阈值已更新，风扇判定立即按新阈值重算";
    } catch (e) { toast.className = "toast err"; toast.textContent = e.message; }
  }

  // ============================================================ 串口链路
  let selectedEvent = null;

  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xffffffff;
    for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }
  const hex2 = (n) => n.toString(16).toUpperCase().padStart(2, "0");

  function parseFrame(hex) {
    const b = hex ? hex.split(" ").map((x) => parseInt(x, 16)) : [];
    if (b.length < 10) return { bytes: b };
    const len = (b[4] << 8) | b[5];
    const crcAt = 6 + len;
    const declared = b.slice(crcAt, crcAt + 4);
    const computed = crc32(b.slice(2, crcAt));
    const declaredNum = declared.length === 4 ? ((declared[0] << 24) | (declared[1] << 16) | (declared[2] << 8) | declared[3]) >>> 0 : null;
    return { bytes: b, len, crcAt, declared: declaredNum, computed };
  }

  function coloredHex(p) {
    const b = p.bytes;
    if (!b.length) return "";
    return b.map((x, i) => {
      let cls = "";
      if (i < 2) cls = "h"; else if (i < 4) cls = "m"; else if (i < 6) cls = "l";
      else if (p.crcAt != null && i >= p.crcAt) cls = "c";
      return cls ? `<span class="${cls}">${hex2(x)}</span>` : hex2(x);
    }).join(" ");
  }

  function renderLink(s) {
    const src = EHP.source;
    const inactive = $("#link-inactive");
    if (!s.link.active) {
      inactive.hidden = false;
      inactive.innerHTML = src && src.kind === "live"
        ? `当前网关运行在 <code>${esc(s.mode || "simulator")}</code> 模式：仿真数据由软件直接生成，不经过编码与拼帧，没有串口字节流可看。
           想在没有开发板时看到真实的帧，用 <code>python scripts/run_api_server.py --mode virtual --inject-faults</code> 启动网关，
           或者点右上角「回放实测记录」。`
        : "这个会话里没有链路事件。";
    } else inactive.hidden = true;

    const c = linkCounts(s);
    const cells = [
      ["bytes", "收到字节", ""], ["frame", "正常帧", "good"], ["resync", "重同步", c.resync ? "bad" : "good"],
      ["checksum_error", "CRC 失败", c.checksum_error ? "bad" : "good"],
      ["decode_error", "帧格式错", c.decode_error ? "bad" : "good"], ["ignored", "忽略的帧", ""],
    ];
    $("#counters").replaceChildren(...cells.map(([k, label, cls]) =>
      el("div", { class: "counter " + cls }, el("b", { text: String(c[k] || 0) }), el("span", { text: label }))));
    const bad = (c.resync || 0) + (c.checksum_error || 0) + (c.decode_error || 0) + (c.payload_error || 0);
    $("#link-alert").textContent = bad ? String(bad) : "";

    $("#link-scope").textContent = src && src.kind === "live"
      ? "上方计数由网关累计（自网关启动起）；下表只列打开本页以来收到的事件，最多 200 条。"
      : "上方计数与下表都从本次回放开始累计。";
    const onlyBad = $("#only-bad").checked;
    const rows = s.link.events.filter((e) => !onlyBad || e.kind !== "frame").slice(-200).reverse();
    $("#frames").replaceChildren(...rows.map((e) => {
      const kind = EHP.LINK_KINDS[e.kind] || { label: e.kind, cls: "idle" };
      const tr = el("tr", { class: kind.cls === "bad" ? "bad" : kind.cls === "warn" ? "warn" : "",
        "aria-selected": String(e === selectedEvent), tabindex: "0" },
        el("td", { class: "mono", text: EHP.clock(EHP.parseTime(e.timestamp)) }),
        el("td", {}, el("span", { class: "pill " + kind.cls, text: kind.label })),
        el("td", { class: "mono", text: e.length ? `${e.length} B` : "—" }),
        el("td", { class: "hex", text: e.raw || "（被丢弃的字节不成帧）" }));
      const pick = () => { selectedEvent = e; renderFrameDetail(e); renderLink(Store.state); };
      tr.addEventListener("click", pick);
      tr.addEventListener("keydown", (k) => { if (k.key === "Enter") pick(); });
      return tr;
    }));
    if (!rows.length) $("#frames").replaceChildren(el("tr", {}, el("td", { colspan: "4", class: "empty", text: s.link.active ? "等待第一帧…" : "—" })));
  }

  function renderFrameDetail(e) {
    const box = $("#frame-detail");
    const kind = EHP.LINK_KINDS[e.kind] || { label: e.kind, cls: "idle" };
    const kids = [el("div", { class: "panel-head" }, el("h2", { text: "帧解析" }), el("span", { class: "pill " + kind.cls, text: kind.label }))];
    if (e.kind === "resync") {
      kids.push(el("p", { class: "hint", text: "字节流开头不是帧头 AA 55，接收器丢弃了这些字节，直到找到下一个可能的帧头。这正是帧同步机制在处理混入的杂散字节。" }));
    } else {
      const p = parseFrame(e.raw);
      kids.push(el("div", { class: "hex-bytes", html: coloredHex(p) }));
      kids.push(el("div", { class: "legend", html: `<span><i style="background:var(--hex-head)"></i>帧头</span><span><i style="background:var(--hex-meta)"></i>设备 ID · 命令</span><span><i style="background:var(--hex-len)"></i>长度</span><span><i style="background:var(--hex-crc)"></i>CRC-32</span>` }));
      // 没通过校验的帧，接收器不会解码；字段直接从字节里读出来，并注明仅供查看。
      const unverified = e.device_id == null && p.bytes.length > 6;
      const id = e.device_id != null ? e.device_id : p.bytes[2];
      const cmd = e.command_type != null ? e.command_type : p.bytes[3];
      let payload = e.payload;
      if (!payload && p.len != null) {
        try { payload = new TextDecoder().decode(new Uint8Array(p.bytes.slice(6, 6 + p.len))); } catch (_) { payload = null; }
      }
      const tag = unverified ? "（未通过校验，仅供查看）" : "";
      const rows = [
        ["设备 ID", id != null ? `0x${hex2(id)}（${id}）${tag}` : "—"],
        ["命令类型", cmd != null ? `0x${hex2(cmd)}${cmd === 1 ? "（数据上报）" : ""}${tag}` : "—"],
        ["声明长度", p.len != null ? `${p.len} 字节` : "—"],
        ["载荷", payload ? payload + tag : "—"],
      ];
      if (p.declared != null) {
        const ok = p.declared === p.computed;
        rows.push(["帧内 CRC", "0x" + p.declared.toString(16).toUpperCase().padStart(8, "0")]);
        rows.push(["重新计算", "0x" + p.computed.toString(16).toUpperCase().padStart(8, "0") + (ok ? "  ✓ 一致" : "  ✗ 不一致")]);
      }
      if (e.detail) rows.push(["接收器说明", e.detail]);
      kids.push(el("dl", { class: "fields" }, ...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])));
      if (e.kind === "checksum_error") {
        kids.push(el("p", { class: "hint", text: "按收到的字节重新计算的 CRC 与帧里声明的不一致，说明传输中至少有一位出错。这一帧被丢弃并计数，不会变成一个错误的读数。" }));
      }
    }
    if (EHP.source && EHP.source.kind === "replay" && EHP.source.session === "hour") {
      kids.push(el("p", { class: "hint", text: EHP.source.data.hour.note }));
    }
    box.replaceChildren(...kids);
  }

  // ============================================================ 环境问答
  let selectedAnswer = null;
  const LIVE_SAMPLES = ["现在温度多少", "噪声超标了吗", "过去十分钟湿度平均多少", "风扇为什么在转", "温度都40度了吧", "风扇是不是该开了", "今天股市怎么样"];

  function answerOf(m) { return m.late || m.answer; }

  function renderChat(s) {
    const chat = $("#chat");
    chat.replaceChildren(...s.chat.map((m) => {
      if (m.role === "q") return el("div", { class: "msg q", text: m.text });
      const a = answerOf(m);
      const node = el("div", { class: "msg a" + (m.awaiting && a.source === "pending" ? " pending" : ""),
        "aria-selected": String(m === selectedAnswer), tabindex: "0" },
        a.text, el("span", { class: "src", text: (EHP.SOURCES[a.source] || a.source) + (m.awaiting ? " · 等待模型改写…" : "") + " · 点此看来龙去脉" }));
      const pick = () => { selectedAnswer = m; renderTrace(m); renderChat(Store.state); };
      node.addEventListener("click", pick);
      node.addEventListener("keydown", (k) => { if (k.key === "Enter") pick(); });
      return node;
    }));
    chat.scrollTop = chat.scrollHeight;
    if (selectedAnswer) renderTrace(selectedAnswer);
  }

  function factsBlock(facts) {
    if (!facts) return el("p", { class: "hint", text: "这类问题不需要取数。" });
    if (typeof facts === "string") return el("pre", { class: "facts", text: facts });
    const show = (v) => (typeof v === "number" && !Number.isInteger(v) ? v.toFixed(2)
      : typeof v === "boolean" ? (v ? "是" : "否") : Array.isArray(v) ? v.join("、") : v);
    // 有中文标签的字段总是列出；其余字段为假或空列表时省略，免得满屏"否"。
    const lines = Object.entries(facts)
      .filter(([k, v]) => FACT_LABELS[k] || (v !== false && !(Array.isArray(v) && !v.length)))
      .map(([k, v]) => `${FACT_LABELS[k] || k}：${k === "kind" ? INTENTS[v] || v : show(v)}`);
    return el("pre", { class: "facts", text: lines.join("\n") });
  }

  // ------------------------------------------------ 实时流程（6.1 节，2026-09-26）
  // 一句回答的来路，按发生顺序逐步点亮。每一步都是网关推来的 assistant_step，
  // 这里只负责把它说成人话，不做任何判断。
  const JOBS = { rephrase: "改写", explain: "解释", parse: "分类", review: "复核" };
  const CHECK_NAMES = { grounding: "接地校验", alarm: "越限断言", judgement: "凭空判断", advice: "建议措辞", length: "长度上限" };
  const CONTEXT_NOTES = {
    inherited_kind: "沿用上一轮的问法", clarification: "补全了上一轮的反问", fan_topic: "话题还在风扇上，读成风扇指令",
  };
  const CONFIRM_NOTES = {
    affirm: "同意 → 执行挂起的那条指令", deny: "拒绝 → 不执行",
    other: "答非所问 → 挂起的指令作废，这句当新问题处理", expired: "确认已过期 → 挂起的指令作废",
  };
  const REVIEW_NOTES = {
    agree: ["与规则一致 → 执行", "ok"], disagree: ["与规则不一致 → 不执行，改为反问", "warn"],
    silent: ["模型没有回应 → 按规则执行（与未接模型时相同）", "idle"],
  };

  const intentText = (i) => (i ? `${INTENTS[i.kind] || i.kind}${i.channel ? " · " + (EHP.CHANNELS[i.channel] || {}).label : ""}` : "（无）");
  const atText = (ms) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

  function stepView(st) {
    const job = JOBS[st.job] || st.job;
    let title = st.kind, cls = "", body = [];
    switch (st.kind) {
      case "received": title = "收到问题"; body = [el("p", { text: st.text })]; break;
      case "confirmation": title = "对确认问句的回答"; body = [el("p", { text: `${CONFIRM_NOTES[st.note] || st.note}（挂起的指令：${intentText(st.intent)}）` })]; break;
      case "compound": {
        const [q, c] = (st.note || "0+0").split("+");
        title = "一句话里有几件事"; body = [el("p", { text: `拆成 ${q} 个提问${c === "1" ? " + 1 条指令" : ""}；提问只用模板作答，指令单独复核` })]; break;
      }
      case "rules": title = "规则识别";
        body = [el("p", { text: st.intent && st.intent.kind === "HELP" ? "规则没认出这句话（先回帮助提示）"
          : intentText(st.intent) + (st.text ? `　（指令段：${st.text}）` : "") })];
        break;
      case "context": title = "对话记忆"; body = [el("p", { text: `${CONTEXT_NOTES[st.note] || st.note} → ${intentText(st.intent)}` })]; break;
      case "facts": title = "取数层给出事实（回答里的数字只能来自这里）"; body = [factsBlock(st.facts)]; break;
      case "template": title = "模板成句"; body = [el("p", { class: "quote", text: st.text })]; break;
      case "model_submit":
        title = `交给模型${job}`; cls = "model";
        body = [el("p", { class: "hint", text: st.job === "explain" ? "模型收到的只有这张事实清单：" : st.job === "rephrase" ? "模型收到的只有这句模板，看不到读数：" : "模型收到的只有用户原话，只许回一个标签：" }),
          el("pre", { class: "facts", text: st.text })];
        break;
      case "model_unavailable":
        title = `未接模型，跳过${job}`; cls = "idle";
        body = [el("p", { class: "hint", text: st.job === "review" ? "按规则直接执行，与改动前完全一样。" : st.job === "parse" ? "保留即时回复。" : "模板就是最终答案。" })];
        break;
      case "model_reply": title = `模型返回（${job}）`; cls = "model"; body = [el("p", { class: "quote", text: st.text || "（空）" })]; break;
      case "label":
        if (st.job === "review") {
          const [t, c] = REVIEW_NOTES[st.note] || [st.note, ""];
          title = "复核裁决（代码作出）"; cls = c;
          body = [el("p", { text: `模型读成：${intentText(st.intent)}　${t}` })];
        } else {
          title = "模型给出的分类"; cls = st.intent ? "ok" : "warn";
          body = [el("p", { text: st.intent ? `${intentText(st.intent)} → 由代码按这个意图取数、套模板` : "标签无法使用 → 忽略" })];
        }
        break;
      case "checks": {
        const ok = st.verdict === "accepted";
        title = "出口五道检查（代码逐道核对）"; cls = ok ? "ok" : "bad";
        body = st.checks.length
          ? [el("ul", { class: "checks" }, ...st.checks.map((c) => el("li", { class: c.passed ? "pass" : "fail" },
              el("span", { class: "mark", text: c.passed ? "✓" : "✗" }), el("span", { text: CHECK_NAMES[c.name] || c.name }),
              el("span", { class: "detail", text: c.detail })))),
            el("p", { class: "verdict " + (ok ? "ok" : "bad"), text: EHP.VERDICTS[st.verdict] || st.verdict })]
          : [el("p", { class: "verdict bad", text: EHP.VERDICTS[st.verdict] || st.verdict })];
        break;
      }
      case "retry": title = "被拦下 → 按更严格的提示重试一次"; cls = "warn"; break;
      case "executed": {
        const refused = st.facts && st.facts.applied === false;
        title = refused ? "交给执行层 → 被代码拒绝，设置未改" : "执行指令"; cls = refused ? "warn" : "ok";
        body = [el("p", { text: `${intentText(st.intent)}　${st.intent && st.intent.kind === "SET_VENT_THRESHOLD" ? "数值取自用户原话" : "依据用户原话"}：「${st.text}」` })];
        break;
      }
      case "answered":
        if (st.note === "immediate_stands") { title = "模型没有给出可用结果 → 即时回复就是最终答案"; cls = "final"; break; }
        title = st.final ? "最终答案" : "即时回复（先发出，模型结果到了可能替换它）"; cls = st.final ? "final" : "";
        body = [el("p", { class: "quote", text: st.text }), el("p", { class: "hint", text: "来源：" + (EHP.SOURCES[st.source] || st.source) })];
        break;
      case "abandoned": title = "用户已经问了下一句 → 这一问的模型工作被放弃"; cls = "idle"; break;
    }
    return el("li", { class: cls }, el("span", { class: "at", text: atText(st.at_ms) }),
      el("div", {}, el("strong", { text: title }), ...body));
  }

  function timelineView(m, steps) {
    const items = steps.map(stepView);
    if (m.awaiting) {
      const t0 = m.askedAt || performance.now();
      items.push(el("li", { class: "waiting" }, el("span", { class: "at", text: atText(Math.round(performance.now() - t0)) }),
        el("div", {}, el("strong", { text: "等模型…" }), el("p", { class: "hint", text: "纯 CPU 跑 4B 模型，改写约 3 秒、解释约 10 秒" }))));
    }
    const kids = [el("ol", { class: "timeline" }, ...items)];
    if (m.recorded) kids.push(el("p", { class: "hint", text: m.recorded }));
    return kids;
  }

  function renderTrace(m) {
    const box = $("#trace");
    const a = answerOf(m);
    const first = m.answer;
    const trace = a.trace || [];
    const accepted = trace.some((t) => t.verdict === "accepted");
    const flow = el("div", { class: "flow", html: [
      `<span class="on">规则${a.source === "model_intent" ? "落空 → 模型识别意图" : "识别意图"}</span>`,
      `<span class="${a.facts ? "on" : ""}">取数层给出事实</span>`,
      `<span class="on">模板成句</span>`,
      `<span class="${trace.length ? "on" : ""}">模型改写${trace.length ? ` ×${trace.length}` : "（未经过）"}</span>`,
      `<span class="${trace.length ? "on" : ""}">出口检查</span>`,
      `<span class="on">采用：${EHP.SOURCES[a.source] || a.source}</span>`,
    ].join("<i>→</i>") });
    const kids = [];
    if (a.boundary) {
      // 边界题库只记录了回答与设备设置，没有逐次记录改写与出口检查，所以不画流程，免得看起来像走过了什么
      kids.push(boundaryBlock(a.boundary, EHP.source && EHP.source.data && EHP.source.data.assistant.boundary_summary));
      kids.push(el("div", {}, el("h3", { text: "最终识别出的意图" }),
        el("p", { style: "margin:0", text: a.intent ? `${INTENTS[a.intent.kind] || a.intent.kind}${a.intent.channel ? " · " + (EHP.CHANNELS[a.intent.channel] || {}).label : ""}` : "未能识别（回落到帮助提示）" })));
      if (first && first !== a && first.text !== a.text) {
        kids.push(el("div", {}, el("h3", { text: "即时回复（模型结果到达之前）" }), el("p", { style: "margin:0", text: first.text })));
      }
      if (m.recorded) kids.push(el("p", { class: "hint", text: m.recorded }));
      box.replaceChildren(...kids);
      return;
    }
    const steps = m.qid != null ? Store.state.steps[m.qid] : null;
    if (steps && steps.length) {
      box.replaceChildren(...timelineView(m, steps));
      return;
    }
    kids.push(
      el("div", {}, el("h3", { text: "流程" }), flow),
      el("div", {}, el("h3", { text: "识别出的意图" }),
        el("p", { style: "margin:0", text: a.intent ? `${INTENTS[a.intent.kind] || a.intent.kind}${a.intent.channel ? " · " + (EHP.CHANNELS[a.intent.channel] || {}).label : ""}` : "未能识别（回落到帮助提示）" })),
      el("div", {}, el("h3", { text: "取数层给出的事实（回答里的数字只能来自这里）" }), factsBlock(a.facts)),
    );
    if (first && first !== a && first.text !== a.text) {
      kids.push(el("div", {}, el("h3", { text: "即时回复（模型结果到达之前）" }), el("p", { style: "margin:0", text: first.text })));
    }
    if (trace.length) {
      kids.push(el("div", {}, el("h3", { text: "模型改写与出口检查" }),
        ...trace.map((t, i) => {
          const ok = t.verdict === "accepted";
          return el("div", { class: "attempt " + (ok ? "accepted" : "refused") },
            el("div", { class: "row" }, el("span", { text: t.retry ? `第 ${i + 1} 次（重试）` : `第 ${i + 1} 次` }), el("span", { class: "verdict", text: EHP.VERDICTS[t.verdict] || t.verdict })),
            el("div", { class: "row" }, el("span", { text: "模板原句" }), el("span", { text: t.template })),
            el("div", { class: "row" }, el("span", { text: "模型原文" }), el("span", { text: t.reply || "（空）" })));
        })));
      kids.push(el("p", { class: "hint", text: accepted
        ? "改写通过了全部检查才被采用；数字与事实逐个核对过。"
        : "改写没有通过检查，最终采用模板原句——一句生硬的正确答案，好过一句好听的错话。" }));
    } else if (!m.awaiting) {
      kids.push(el("p", { class: "hint", text: "这条回答没有经过模型改写：模板本身就是最终答案。" }));
    }
    if (a.applied === true) kids.push(el("p", { class: "hint", text: "这是一条指令，已执行。数值取自用户原话，不来自模型。" }));
    if (m.recorded) kids.push(el("p", { class: "hint", text: m.recorded }));
    box.replaceChildren(...kids);
  }

  // 回放录制好的实时流程：按录制时的原始节奏逐步推进，走与在线时同一条 Store.handle。
  // 每次播放给一个新编号，同一题点两次不会把两遍的步骤混在一起；切换数据源会清空状态，
  // 还没播完的定时器发现状态换了就不再推。
  let replayPlays = 0;
  function playRecordedSteps(item) {
    const s = Store.state;
    const qid = `replay-${++replayPlays}`;
    const entry = { role: "a", answer: item.first, awaiting: true, qid, askedAt: performance.now(),
      recorded: item.recorded || `录制于 ${item.config}` };
    s.chat.push(entry);
    for (const step of item.steps) {
      setTimeout(() => {
        if (Store.state !== s) return;
        Store.handle(Object.assign({}, step, { type: "assistant_step", question_id: qid }));
        if (step.kind === "answered" && step.final) {
          if (item.text !== item.first.text) entry.late = item;
          entry.awaiting = false;
          Store.emit();
        }
      }, step.at_ms);
    }
  }

  async function onAsk(question, index) {
    question = question.trim();
    if (!question) return;
    const s = Store.state;
    s.chat.push({ role: "q", text: question });
    Store.emit();
    const sentAt = performance.now();
    try {
      const reply = await EHP.source.ask(question, index);
      if (EHP.source.kind === "replay" && reply.steps) {
        playRecordedSteps(reply);
      } else if (EHP.source.kind === "replay") {
        s.chat.push({ role: "a", answer: reply.first && reply.first.text !== reply.text ? Object.assign({}, reply, reply.first, { trace: [] }) : reply,
          late: reply.first && reply.first.text !== reply.text ? reply : null, awaiting: false,
          recorded: reply.recorded || `录制于 ${EHP.source.data.assistant.note}（${reply.config}）` });
      } else {
        const qid = reply.question_id || null;
        const done = qid && (s.steps[qid] || []).some((x) => x.kind === "answered" && x.final);
        // 有编号时以"最终答案"那一步为准；旧版网关没有编号，沿用原先的猜法。
        const awaiting = qid ? !done : reply.source === "pending" || (reply.source === "template" && !(reply.trace || []).length);
        const entry = { role: "a", answer: reply, awaiting, qid, askedAt: sentAt };
        s.chat.push(entry);
        if (awaiting) setTimeout(() => { entry.awaiting = false; Store.emit(); }, 25000);
      }
      selectedAnswer = s.chat[s.chat.length - 1];
    } catch (e) {
      s.chat.push({ role: "a", answer: { text: e.message, source: "fallback", trace: [] }, awaiting: false });
    }
    Store.emit();
  }

  // 回放时按录制批次分组：同一句话在不同配置下的表现本就该分开看。
  const CHIP_GROUPS = [
    ["实时流程", "一句回答是怎么来的：按录制时的节奏逐步重演（每条路径一题）"],
    ["实时流程 · 采样温度 0.8", "同上，采样温度 0.8：出口检查拦下 → 重试"],
    ["现行配置", "录制的问答（现行配置）"],
    ["采样温度 0.8", "对照：采样温度 0.8，看出口检查拦下了什么"],
    ["边界题库", "能力之外的问法：不该照做的，设备设置是否保持不变"],
  ];

  function renderChips() {
    const src = EHP.source;
    const box = $("#chips");
    if (src && src.kind === "replay") {
      const items = src.data.assistant.items;
      box.replaceChildren(...CHIP_GROUPS.map(([config, title]) => {
        const buttons = items.map((it, i) => [it, i]).filter(([it]) => it.config === config)
          .map(([it, i]) => el("button", { type: "button", class: it.boundary ? "boundary" : null,
            title: it.label || null, text: it.question, onclick: () => onAsk(it.question, i) }));
        return buttons.length ? el("div", { class: "chip-group" }, el("span", { text: title }), el("div", { class: "chips" }, ...buttons)) : null;
      }).filter(Boolean));
    } else {
      box.replaceChildren(el("div", { class: "chips" },
        ...LIVE_SAMPLES.map((q) => el("button", { type: "button", text: q, onclick: () => onAsk(q) }))));
    }
    $("#qa-hint").textContent = src && src.kind === "replay" ? "回放模式：点下方录制过的问题" : "可以直接输入，也可以点下方示例";
    $("#ask-input").disabled = !(src && src.capabilities.freeQuestions);
  }

  // 边界题：看的不是措辞，是"设备有没有被动过"
  function boundaryBlock(b, summary) {
    const verdict = { held: ["守住", "ok"], limit: ["已知局限（无副作用）", "warn"], executed: ["合法指令，已执行", "ok"] }[b.verdict];
    const changed = Object.keys(b.changed || {}).length
      ? Object.entries(b.changed).map(([k, v]) => `${{ temperature_max: "温度通风阈值", humidity_max: "湿度通风阈值", mode: "风扇模式" }[k] || k} → ${EHP.MODES[v] || v}`).join("，")
      : "未改变";
    const kids = [
      el("h3", { text: "边界判定" }),
      el("div", { class: "verdict-line" },
        el("span", { class: "pill " + verdict[1], text: verdict[0] }),
        el("span", { text: `类别：${b.category}` })),
      el("dl", { class: "fields" },
        el("dt", { text: "规则判为" }), el("dd", { text: `${INTENTS[(b.rule || "").toUpperCase()] || b.rule}${b.rule_channel ? " · " + (EHP.CHANNELS[b.rule_channel] || {}).label : ""}` }),
        el("dt", { text: "设备设置" }), el("dd", { text: changed })),
    ];
    if (b.note) kids.push(el("p", { class: "hint", text: b.note }));
    if (summary) kids.push(el("p", { class: "boundary-sum", text: summary }));
    return el("div", {}, ...kids);
  }

  // 回放时第一次打开问答页就摆出一条完整的来龙去脉，而不是一块等人点击的空白。
  // 页签与数据源谁先就绪不一定（直接打开 #assistant 时页签先到），所以切页签时调一次，
  // 回放启动完成后 main.js 再调一次——必须在 start() 之后，start() 会清空状态连同对话。
  function showFirstAtRest() {
    const src = EHP.source;
    if ($("#assistant").hidden) return;
    if (src && src.kind === "replay" && !Store.state.chat.length && src.data.assistant.items.length) {
      onAsk(src.data.assistant.items[0].question, 0);
    }
  }

  // ============================================================ 历史
  let histChart = null;
  async function loadHistory() {
    const channel = $("#hist-channel").value;
    const hint = $("#hist-hint");
    if (!histChart) histChart = EHP.timeChart($("#c-hist"), {});
    hint.textContent = "查询中…";
    try {
      const { points, unit, note } = await EHP.source.history(channel);
      hint.textContent = note;
      const t0 = points.length ? points[0][0] : 0, t1 = points.length ? points[points.length - 1][0] : 1;
      histChart.update({ window: [t0, t1], emptyText: "这个时间段没有读数",
        panels: [{ name: EHP.CHANNELS[channel].label, unit, dp: EHP.CHANNELS[channel].dp, series: points }] });
    } catch (e) { hint.textContent = e.message; histChart.update({ panels: [], emptyText: e.message }); }
  }

  // ============================================================ 装配
  EHP.views = {
    init() {
      document.querySelectorAll("#fan-modes button").forEach((b) => b.addEventListener("click", () => onFanMode(b.dataset.mode)));
      $("#fan-form").addEventListener("submit", onFanForm);
      $("#only-bad").addEventListener("change", () => renderLink(Store.state));
      $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#ask-input"); onAsk(i.value); i.value = ""; });
      $("#hist-load").addEventListener("click", loadHistory);
      // 等模型时让"等模型… x.x s"走起来；不在问答页或没有在等的就什么也不做。
      setInterval(() => {
        if (selectedAnswer && selectedAnswer.awaiting && !$("#assistant").hidden) renderTrace(selectedAnswer);
      }, 200);
      Store.subscribe((s) => {
        renderCards(s); renderFan(s); renderDevices(s);
        if (!$("#monitor").hidden) renderLiveChart(s);
        if (!$("#link").hidden) renderLink(s);
        if (!$("#assistant").hidden) renderChat(s);
      });
    },
    onSourceChanged() {
      selectedEvent = null; selectedAnswer = null;
      $("#frame-detail").replaceChildren(el("h2", { text: "帧解析" }), el("p", { class: "empty", text: "点左侧任意一行查看" }));
      $("#trace").replaceChildren(el("p", { class: "empty", text: "点左侧任意一条回答查看" }));
      $("#fan-toast").textContent = "";
      renderChips();
      if (!$("#history").hidden) loadHistory();
    },
    onTab(id) {
      const s = Store.state;
      if (id === "monitor") renderLiveChart(s);
      if (id === "link") renderLink(s);
      if (id === "assistant") { renderChat(s); renderChips(); showFirstAtRest(); }
      if (id === "history") loadHistory();
    },
    showFirstAtRest,
    redraw() { const s = Store.state; renderLiveChart(s); if (histChart) histChart.draw(); },
  };
})();
