/* sources.js —— 两种数据源，接口一致，都只往 EHP.Store 里推网关格式的消息。
 *
 *   LiveSource   连接一个在跑的网关（scripts/run_api_server.py），REST + WebSocket。
 *   ReplaySource 播放 replay/replay-data.js 里录好的消息，无需任何后端。
 *
 * 视图不区分这两者；能力不同的地方（回放里不能改风扇设置、只能问录过的问题）
 * 由 source.capabilities 说明，视图据此把控件置灰并写明原因。 */
(function () {
  "use strict";
  const EHP = window.EHP;
  const Store = EHP.Store;

  async function fetchJson(url, options = {}, timeoutMs = 4000) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    try {
      const res = await fetch(url, Object.assign({ signal: ctl.signal }, options));
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      return body;
    } finally {
      clearTimeout(timer);
    }
  }
  const jsonBody = (method, obj) => ({
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj),
  });

  // ------------------------------------------------------------ 在线网关
  class LiveSource {
    constructor(base) {
      this.base = base.replace(/\/+$/, "");
      this.kind = "live";
      this.capabilities = { control: true, freeQuestions: true };
      this.ws = null;
      this.timers = [];
      this.backoff = 1000;
      this.stopped = false;
      this.onstatus = () => {};
    }

    static async probe(base, timeoutMs = 1500) {
      return fetchJson(base.replace(/\/+$/, "") + "/health", {}, timeoutMs);
    }

    async start(health) {
      Store.reset();
      Store.state.mode = health.mode;
      this.connectSocket();
      await Promise.allSettled([this.refreshVentilation(), this.refreshDevices(), this.refreshLink()]);
      this.timers.push(setInterval(() => this.refreshLink(), 3000));
      this.timers.push(setInterval(() => this.refreshDevices(), 10000));
    }

    stop() {
      this.stopped = true;
      this.timers.forEach(clearInterval);
      this.timers = [];
      if (this.ws) { this.ws.onclose = null; this.ws.close(); }
    }

    connectSocket() {
      if (this.stopped) return;
      const url = this.base.replace(/^http/, "ws") + "/ws";
      const ws = new WebSocket(url);
      this.ws = ws;
      ws.onopen = () => { this.backoff = 1000; this.onstatus("live"); };
      ws.onmessage = (e) => { try { Store.handle(JSON.parse(e.data)); } catch (_) { /* 坏消息丢弃 */ } };
      ws.onclose = () => {
        if (this.stopped) return;
        this.onstatus("reconnecting");
        // 与 Android 客户端相同的指数退避：1 s 起，逐次加倍，上限 32 s。
        setTimeout(() => this.connectSocket(), this.backoff);
        this.backoff = Math.min(this.backoff * 2, 32000);
      };
    }

    async refreshVentilation() {
      const v = await fetchJson(this.base + "/ventilation");
      Store.state.fan.settings = { temperature_max: v.temperature_max, humidity_max: v.humidity_max, mode: v.mode };
      if (v.decision) Store.state.fan.decision = Object.assign({ type: "fan_decision" }, v.decision);
      Store.emit();
    }

    async refreshDevices() {
      const { devices } = await fetchJson(this.base + "/devices");
      const statuses = await Promise.all(devices.map((id) =>
        fetchJson(this.base + "/devices/" + encodeURIComponent(id) + "/status").catch(() => ({ device_id: id }))));
      Store.state.devices = statuses;
      Store.emit();
    }

    async refreshLink() {
      try {
        const stats = await fetchJson(this.base + "/link/statistics");
        Store.state.link.serverStats = stats;
        Store.state.link.active = stats.active;
        Store.emit();
      } catch (_) { /* 旧版网关没有这个接口：当作没有字节流 */ }
    }

    async ask(question) {
      return fetchJson(this.base + "/assistant/ask", jsonBody("POST", { question }), 8000);
    }

    async setMode(mode) {
      const v = await fetchJson(this.base + "/ventilation/mode", jsonBody("PUT", { mode }));
      Store.state.fan.settings = { temperature_max: v.temperature_max, humidity_max: v.humidity_max, mode: v.mode };
      Store.emit();
    }

    async setThresholds(temperature_max, humidity_max) {
      const v = await fetchJson(this.base + "/ventilation/thresholds",
        jsonBody("PUT", { temperature_max, humidity_max }));
      Store.state.fan.settings = { temperature_max: v.temperature_max, humidity_max: v.humidity_max, mode: v.mode };
      Store.emit();
    }

    async history(channel) {
      const device = Store.state.channels[channel].device;
      if (!device) throw new Error("这个通道还没有收到过数据，不知道该查哪台设备");
      const body = await fetchJson(
        `${this.base}/devices/${encodeURIComponent(device)}/channels/${channel}/history?limit=2000`);
      const points = body.points.filter((p) => p.valid !== false && typeof p.value === "number")
        .map((p) => [EHP.parseTime(p.timestamp), p.value]).sort((a, b) => a[0] - b[0]);
      return { points, unit: body.unit, note: `网关历史库 · ${device} · 最近 ${points.length} 条` };
    }
  }

  // ------------------------------------------------------------ 回放
  class ReplaySource {
    constructor(data) {
      this.data = data;
      this.kind = "replay";
      this.capabilities = { control: false, freeQuestions: false };
      this.session = "hour";
      this.speed = 10;
      this.playing = true;
      this.pos = 0;
      this.index = 0;
      this.timer = null;
      this.lastTick = 0;
      this.onprogress = () => {};
    }

    get current() { return this.data[this.session]; }

    start() {
      this.load(this.session);
      this.lastTick = performance.now();
      this.timer = setInterval(() => this.tick(), 100);
    }

    stop() { clearInterval(this.timer); }

    load(session) {
      this.session = session;
      this.pos = 0;
      this.index = 0;
      this.resetState();
      this.onprogress();
    }

    resetState() {
      Store.reset();
      const s = Store.state;
      s.mode = this.session === "hour" ? "回放 · 一小时稳定性实验" : "回放 · 故障注入会话";
      if (this.session === "hour") {
        const v = this.data.hour.ventilation;
        s.fan.settings = { temperature_max: v.temperature_max, humidity_max: v.humidity_max, mode: v.mode };
        s.devices = [{ device_id: "mcu-1", is_connected: true, is_occupied: false }];
      } else {
        s.devices = [{ device_id: "virtual-stm32", is_connected: true, is_occupied: false }];
      }
    }

    tick() {
      const now = performance.now();
      const dt = (now - this.lastTick) / 1000;
      this.lastTick = now;
      if (!this.playing) return;
      this.advanceTo(Math.min(this.pos + dt * this.speed, this.current.duration));
      if (this.pos >= this.current.duration) this.playing = false;
      this.onprogress();
    }

    advanceTo(target) {
      const msgs = this.current.messages;
      while (this.index < msgs.length && msgs[this.index][0] <= target) {
        Store.handle(msgs[this.index][1]);
        this.index++;
      }
      this.pos = target;
    }

    seek(target) {
      this.index = 0;
      this.resetState();
      Store.silent = true;
      this.advanceTo(target);
      Store.silent = false;
      Store.emit();
      this.onprogress();
    }

    async ask(question, index) {
      // 同一句话在两种配置下各录过一次时，按条目索引取，不按文字取。
      const items = this.data.assistant.items;
      const item = index != null ? items[index] : items.find((i) => i.question === question);
      if (!item) throw new Error("回放模式只能查看录制过的问答，请点下方的问题");
      return item;
    }

    async setMode() { throw new Error("回放模式下只读：连接网关后才能控制风扇"); }
    async setThresholds() { throw new Error("回放模式下只读：连接网关后才能改阈值"); }

    async history(channel) {
      if (this.session !== "hour") throw new Error("故障注入会话只录了链路事件，没有读数");
      const points = this.data.hour.messages
        .filter(([, m]) => m.type === "data" && m.channel === channel)
        .map(([, m]) => [EHP.parseTime(m.timestamp), m.value]);
      return { points, unit: EHP.CHANNELS[channel].unit, note: `录制数据 · ${this.data.hour.source} · ${points.length} 条` };
    }
  }

  EHP.LiveSource = LiveSource;
  EHP.ReplaySource = ReplaySource;

  // 回放数据 3 MB，只在需要时加载。动态插入 <script> 在 file:// 下同样可用，fetch 则不行。
  EHP.loadReplayData = () => new Promise((resolve, reject) => {
    if (window.EHP_REPLAY) return resolve(window.EHP_REPLAY);
    const s = document.createElement("script");
    s.src = "replay/replay-data.js";
    s.onload = () => (window.EHP_REPLAY ? resolve(window.EHP_REPLAY) : reject(new Error("回放数据为空")));
    s.onerror = () => reject(new Error("找不到 replay/replay-data.js，请先运行 scripts/build_web_replay.py"));
    document.head.append(s);
  });
})();
