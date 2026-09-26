/* core.js —— 命名空间、工具函数与状态仓库。
 *
 * 为什么不用 ES 模块：浏览器禁止 file:// 页面加载模块脚本，而本控制台要能
 * 直接双击 index.html 打开（演示现场、U 盘）。所以用普通脚本 + 一个全局命名空间。
 *
 * 数据流只有一条：数据源（在线网关 / 回放）把网关格式的消息交给 Store.handle()，
 * Store 更新状态并通知视图。两种数据源推的是**同一种消息**——回放数据本身
 * 就是用网关的序列化函数离线生成的（scripts/build_web_replay.py）。 */
(function () {
  "use strict";
  const EHP = (window.EHP = window.EHP || {});

  // ---------------------------------------------------------------- 工具
  EHP.$ = (sel, root = document) => root.querySelector(sel);
  EHP.el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const kid of kids) if (kid != null) n.append(kid);
    return n;
  };
  EHP.esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  EHP.css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  EHP.fmt = (v, dp = 2) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(dp));
  EHP.clock = (ms) => {
    const d = new Date(ms);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  };
  EHP.mmss = (sec) => {
    sec = Math.max(0, Math.floor(sec));
    const p = (n) => String(n).padStart(2, "0");
    return sec >= 3600 ? `${Math.floor(sec / 3600)}:${p(Math.floor(sec / 60) % 60)}:${p(sec % 60)}`
                       : `${p(Math.floor(sec / 60))}:${p(sec % 60)}`;
  };
  EHP.parseTime = (iso) => {
    if (!iso) return Date.now();
    // 网关给的时间可能不带时区（回放数据即如此），按本地时间解释。
    const t = Date.parse(iso);
    return Number.isNaN(t) ? Date.now() : t;
  };

  // 通道的展示约定。与 src/core/channel_display.py 同义，但这里只用于显示——
  // 单位以网关消息里的 unit 为准，这张表只在消息缺单位时兜底。
  EHP.CHANNELS = {
    temperature: { label: "温度", unit: "°C", dp: 2 },
    humidity: { label: "湿度", unit: "%RH", dp: 2 },
    noise: { label: "噪声", unit: "dB(A)", dp: 1 },
  };
  EHP.CHANNEL_ORDER = ["temperature", "humidity", "noise"];

  EHP.MODES = { AUTO: "自动", MANUAL_ON: "手动常开", MANUAL_OFF: "手动常关" };

  EHP.VERDICTS = {
    accepted: "采纳",
    no_reply: "模型没有给出改写",
    too_short: "改写为空",
    ungrounded_number: "拦下：出现事实里没有的数字（接地校验）",
    unsupported_alarm: "拦下：事实未越限却称超标",
    unsupported_judgement: "拦下：模板未表态，改写表了态",
    advice: "拦下：添加了建议措辞",
    too_long: "拦下：比原句长出太多（长度上限）",
  };
  EHP.SOURCES = {
    template: "模板",
    model: "模型改写",
    model_intent: "模型识别意图，模板作答",
    fallback: "未能理解",
    pending: "等待模型",
  };
  EHP.LINK_KINDS = {
    frame: { label: "正常帧", cls: "ok" },
    resync: { label: "重同步", cls: "warn" },
    checksum_error: { label: "CRC 失败", cls: "bad" },
    decode_error: { label: "帧格式错", cls: "bad" },
    ignored: { label: "忽略", cls: "idle" },
    payload_error: { label: "载荷错", cls: "bad" },
  };

  // ---------------------------------------------------------------- 状态仓库
  const WINDOW_POINTS = 4000; // 每通道保留的点数，够画一小时（1163 点）
  const MAX_LINK_EVENTS = 400;
  const MAX_STEP_QUESTIONS = 60; // 只留最近这么多个问题的步骤；手机提的问题也会推过来

  function freshState() {
    const channels = {};
    for (const c of EHP.CHANNEL_ORDER) {
      channels[c] = { points: [], stats: null, alarm: null, bounds: {}, unit: EHP.CHANNELS[c].unit, device: null, last: null };
    }
    return {
      channels,
      fan: { settings: null, decision: null },
      link: {
        active: false, events: [], bytes: 0,
        counts: { frame: 0, resync: 0, checksum_error: 0, decode_error: 0, ignored: 0, payload_error: 0 },
        serverStats: null,
      },
      chat: [],
      steps: {}, // question_id → 按 seq 排好的步骤（docs/decisions/08-web.md 6.1）
      devices: [],
      mode: "",
    };
  }

  const listeners = new Set();
  let scheduled = false;
  const Store = {
    state: freshState(),
    silent: false, // 回放快进时关掉通知，结束后统一刷新一次
    reset() { this.state = freshState(); this.emit(); },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    emit() {
      if (this.silent || scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => { scheduled = false; for (const fn of listeners) fn(this.state); });
    },
    handle(msg) {
      const s = this.state;
      switch (msg.type) {
        case "data": {
          const ch = s.channels[msg.channel];
          if (!ch || typeof msg.value !== "number") break;
          const t = EHP.parseTime(msg.timestamp);
          ch.points.push([t, msg.value]);
          if (ch.points.length > WINDOW_POINTS) ch.points.splice(0, ch.points.length - WINDOW_POINTS);
          ch.last = t;
          if (msg.unit) ch.unit = msg.unit;
          ch.device = msg.device_id;
          break;
        }
        case "statistics": {
          const ch = s.channels[msg.channel];
          if (ch) ch.stats = msg;
          break;
        }
        case "alarm_status": {
          const ch = s.channels[msg.channel];
          if (!ch) break;
          // 双向阈值（湿度）未越限时只报告离读数更近的那一侧
          // （service/sensor_data_processor.py 的有意设计），所以卡片看最新一条，
          // 曲线上的阈值线则把见过的上下限都记下来。
          ch.alarm = msg;
          ch.bounds[msg.kind] = msg.threshold;
          break;
        }
        case "fan_decision":
          s.fan.decision = msg;
          if (s.fan.settings) s.fan.settings.mode = msg.mode;
          break;
        case "link_event": {
          s.link.active = true;
          s.link.counts[msg.kind] = (s.link.counts[msg.kind] || 0) + 1;
          s.link.bytes += msg.length || 0;
          s.link.events.push(msg);
          if (s.link.events.length > MAX_LINK_EVENTS) s.link.events.splice(0, s.link.events.length - MAX_LINK_EVENTS);
          break;
        }
        case "assistant_detail": {
          // 迟到的模型结果：有 question_id 就按编号接到那一问上；
          // 旧版网关没有编号，退回原来的做法——接到最近一个还在等的回答上。
          const owner = msg.question_id
            ? s.chat.find((m) => m.role === "a" && m.qid === msg.question_id)
            : [...s.chat].reverse().find((m) => m.role === "a" && m.awaiting);
          if (owner) Object.assign(owner, { awaiting: false, late: msg });
          else if (!msg.question_id) s.chat.push({ role: "a", answer: msg, awaiting: false });
          break;
        }
        case "assistant_step": {
          const key = msg.question_id;
          const list = s.steps[key] || (s.steps[key] = []);
          if (list.some((x) => x.seq === msg.seq)) return; // 重复推送（REST 与 WS 各来一份时）
          list.push(msg);
          list.sort((a, b) => a.seq - b.seq);
          const keys = Object.keys(s.steps);
          if (keys.length > MAX_STEP_QUESTIONS) delete s.steps[keys[0]];
          if (msg.kind === "answered" && msg.final) {
            // 最终答案已定：不必再等（模型没给出可用结果时不会有 assistant_detail）。
            const owner = s.chat.find((m) => m.role === "a" && m.qid === key);
            if (owner) owner.awaiting = false;
          }
          break;
        }
        default:
          return; // assistant（纯文本版）等：详细版已覆盖，忽略
      }
      this.emit();
    },
  };
  EHP.Store = Store;

  EHP.alarmOf = (ch) => ch.alarm;
})();
