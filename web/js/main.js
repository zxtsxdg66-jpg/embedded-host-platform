/* main.js —— 启动与数据源切换。
 *
 * 启动顺序：先试网关，连得上就进入实时模式；连不上（双击打开、GitHub Pages、
 * 网关没开）就进入回放模式——回放的是真实实测数据，不是演示用的假数据。 */
(function () {
  "use strict";
  const EHP = window.EHP;
  const { $ } = EHP;

  const STORAGE_KEY = "ehp.gateway";
  const load = () => { try { return localStorage.getItem(STORAGE_KEY); } catch (_) { return null; } };
  const save = (v) => { try { localStorage.setItem(STORAGE_KEY, v); } catch (_) { /* 无痕模式等：不记也能用 */ } };

  function defaultGateway() {
    // 由网关自己托管在 /web/ 下时，网关就是当前页面的来源。
    if (/^https?:$/.test(location.protocol) && location.pathname.startsWith("/web")) return location.origin;
    return load() || "http://127.0.0.1:8000";
  }

  function setBadge(kind, text) {
    const b = $("#badge");
    b.className = "badge " + kind;
    b.textContent = text;
  }

  // ------------------------------------------------------------ 标签页
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function showTab(id) {
    for (const t of tabs) {
      const on = t.getAttribute("aria-controls") === id;
      t.setAttribute("aria-selected", String(on));
      $("#" + t.getAttribute("aria-controls")).hidden = !on;
    }
    try { history.replaceState(null, "", "#" + id); } catch (_) { /* 某些嵌入环境不允许 */ }
    EHP.views.onTab(id);
  }
  tabs.forEach((t) => t.addEventListener("click", () => showTab(t.getAttribute("aria-controls"))));
  window.addEventListener("hashchange", () => {
    const id = location.hash.slice(1);
    if (tabs.some((t) => t.getAttribute("aria-controls") === id)) showTab(id);
  });

  // ------------------------------------------------------------ 数据源
  function useSource(source) {
    if (EHP.source) EHP.source.stop();
    EHP.source = source;
    $("#replay-bar").hidden = source.kind !== "replay";
    EHP.views.onSourceChanged();
  }

  async function connectLive(base) {
    setBadge("", "正在连接…");
    try {
      const health = await EHP.LiveSource.probe(base);
      const live = new EHP.LiveSource(base);
      live.onstatus = (st) => (st === "live"
        ? setBadge("live", `实时 · ${health.mode}`)
        : setBadge("down", "连接中断，正在重连…"));
      useSource(live);
      await live.start(health);
      setBadge("live", `实时 · ${health.mode}`);
      save(base);
      $("#foot-note").textContent = `网关：${base}`;
      return true;
    } catch (_) {
      return false;
    }
  }

  async function startReplay(reason) {
    setBadge("replay", "回放 · 加载中…");
    let data;
    try { data = await EHP.loadReplayData(); }
    catch (e) { setBadge("down", "离线"); $("#foot-note").textContent = e.message; return; }
    const replay = new EHP.ReplaySource(data);
    replay.onprogress = () => renderReplayBar(replay);
    useSource(replay);
    replay.start();
    EHP.views.showFirstAtRest();
    setBadge("replay", "回放 · 真实实测数据");
    $("#foot-note").textContent = (reason ? reason + " " : "") + `回放数据生成于 ${data.generated}，由 scripts/build_web_replay.py 从原始记录生成。`;
  }

  // ------------------------------------------------------------ 回放控制条
  function renderReplayBar(r) {
    const cur = r.current;
    $("#replay-play").textContent = r.playing ? "暂停" : r.pos >= cur.duration ? "重播" : "播放";
    const seek = $("#replay-seek");
    if (document.activeElement !== seek) seek.value = String(Math.round((r.pos / cur.duration) * 1000));
    $("#replay-clock").textContent = `${EHP.mmss(r.pos)} / ${EHP.mmss(cur.duration)}`;
    $("#replay-note").textContent = `${cur.title} · ${cur.note}` + (r.session === "faults"
      ? ` 注入：拆帧 ${cur.injected.split}、并帧 ${cur.injected.merge}、杂散字节 ${cur.injected.garbage}、翻转 CRC ${cur.injected.bitflip}；判出：重同步 ${cur.caught.resyncs}、CRC 失败 ${cur.caught.checksum_errors}。`
      : "");
    document.querySelectorAll("#replay-session button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.session === r.session)));
    document.querySelectorAll("#replay-speed button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.speed === r.speed)));
  }

  $("#replay-play").addEventListener("click", () => {
    const r = EHP.source;
    if (r.kind !== "replay") return;
    if (!r.playing && r.pos >= r.current.duration) r.seek(0);
    r.playing = !r.playing;
    renderReplayBar(r);
  });
  $("#replay-seek").addEventListener("change", (e) => {
    const r = EHP.source;
    if (r.kind === "replay") r.seek((+e.target.value / 1000) * r.current.duration);
  });
  document.querySelectorAll("#replay-speed button").forEach((b) => b.addEventListener("click", () => {
    if (EHP.source.kind !== "replay") return;
    EHP.source.speed = +b.dataset.speed;
    renderReplayBar(EHP.source);
  }));
  document.querySelectorAll("#replay-session button").forEach((b) => b.addEventListener("click", () => {
    const r = EHP.source;
    if (r.kind !== "replay" || r.session === b.dataset.session) return;
    r.load(b.dataset.session);
    r.playing = true;
    EHP.views.onSourceChanged();
    if (b.dataset.session === "faults") showTab("link");
  }));

  // ------------------------------------------------------------ 顶栏
  $("#btn-connect").addEventListener("click", async () => {
    const base = $("#gateway-url").value.trim() || defaultGateway();
    if (!(await connectLive(base))) {
      setBadge("down", "连不上网关");
      $("#foot-note").textContent = `连不上 ${base}：确认网关已启动（python scripts/run_api_server.py），且地址与端口正确。`;
    }
  });
  $("#btn-replay").addEventListener("click", () => startReplay());

  // ------------------------------------------------------------ 重绘
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => EHP.views.redraw(), 120); });
  if (window.matchMedia) {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", () => EHP.views.redraw());
  }
  new MutationObserver(() => EHP.views.redraw()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ------------------------------------------------------------ 启动
  EHP.views.init();
  const base = defaultGateway();
  $("#gateway-url").value = base;
  const initialTab = (location.hash || "").slice(1);
  showTab(tabs.some((t) => t.getAttribute("aria-controls") === initialTab) ? initialTab : "monitor");
  (async () => {
    const onPages = /github\.io$/.test(location.hostname);
    if (!onPages && (await connectLive(base))) return;
    await startReplay(onPages ? "这是公开演示页，没有网关可连。" : `没有连上 ${base} 的网关，已切换到回放。`);
  })();
})();
