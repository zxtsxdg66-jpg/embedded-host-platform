/* chart.js —— 时间轴多面板折线图（原生 Canvas，无依赖）。
 *
 * 用法：
 *   const c = EHP.timeChart(canvas, { panels: [...] });
 *   c.update({ panels: [{ name, unit, dp, series: [[ms, v]...], refs: [{ v, label }] }],
 *              window: [t0, t1] });
 * 颜色一律在绘制时从 CSS 变量读，切换深浅色主题后下一次绘制即生效。 */
(function () {
  "use strict";
  const EHP = window.EHP;

  function niceTicks(lo, hi, n) {
    if (!(hi > lo)) return [lo];
    const step0 = (hi - lo) / n;
    const mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
    return out;
  }

  function timeTicks(t0, t1, n) {
    const span = t1 - t0;
    const steps = [5e3, 10e3, 15e3, 30e3, 60e3, 120e3, 300e3, 600e3, 900e3, 1800e3, 3600e3];
    const step = steps.find((s) => span / s <= n) || 3600e3;
    const out = [];
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push(t);
    return out;
  }

  function range(series, refs) {
    let lo = Infinity, hi = -Infinity;
    for (const [, v] of series) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!Number.isFinite(lo)) return [0, 1];
    // 阈值线只在离读数不远时才纳入纵轴：22 ℃ 的读数配 35 ℃ 的阈值，
    // 硬塞进同一个纵轴会把曲线压成一条直线（第一版即如此）。远的阈值卡片上有写。
    const span = Math.max(hi - lo, 1);
    for (const r of refs || []) {
      if (r.v > hi && r.v - hi <= span) hi = r.v;
      if (r.v < lo && lo - r.v <= span) lo = r.v;
    }
    if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.12;
    return [lo - pad, hi + pad];
  }

  EHP.timeChart = function (canvas, initial) {
    let cfg = Object.assign({ panels: [], window: null }, initial);
    let hover = null;
    const tip = EHP.el("div", { class: "tip", hidden: "" });
    canvas.parentElement.append(tip);
    const P = { l: 54, r: 12, t: 22, b: 30, gap: 30 };
    let geo = null;

    function draw() {
      const w = canvas.clientWidth;
      if (!w) return;
      const h = +canvas.getAttribute("height");
      const dpr = window.devicePixelRatio || 1;
      canvas.style.height = h + "px";
      if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      const g = canvas.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const ink = EHP.css("--ink"), muted = EHP.css("--muted"), grid = EHP.css("--faint");
      const acc = EHP.css("--accent"), alert = EHP.css("--alert");
      const mono = EHP.css("--mono"), sans = EHP.css("--sans");
      const n = Math.max(1, cfg.panels.length);
      const ph = (h - P.t - P.b - P.gap * (n - 1)) / n, pw = w - P.l - P.r;
      let [t0, t1] = cfg.window || [0, 1];
      if (!(t1 > t0)) t1 = t0 + 1;
      const X = (t) => P.l + ((t - t0) / (t1 - t0)) * pw;
      geo = { X, t0, t1, pw };

      if (!cfg.panels.some((p) => p.series.length)) {
        g.fillStyle = muted; g.font = `13px ${sans}`; g.textAlign = "center";
        g.fillText(cfg.emptyText || "还没有数据", w / 2, h / 2);
        return;
      }
      const tticks = timeTicks(t0, t1, Math.max(3, Math.floor(pw / 110)));
      cfg.panels.forEach((p, i) => {
        const top = P.t + i * (ph + P.gap);
        const visible = p.series.filter(([t]) => t >= t0 && t <= t1);
        const [lo, hi] = p.fixed || range(visible.length ? visible : p.series, p.refs);
        const Y = (v) => top + ph - ((v - lo) / (hi - lo)) * ph;
        p._Y = Y;
        g.lineWidth = 1; g.strokeStyle = grid; g.fillStyle = muted; g.font = `11px ${mono}`;
        g.textAlign = "right"; g.textBaseline = "middle";
        for (const v of niceTicks(lo, hi, 3)) {
          g.beginPath(); g.moveTo(P.l, Y(v)); g.lineTo(P.l + pw, Y(v)); g.stroke();
          g.fillText(+v.toFixed(2), P.l - 6, Y(v));
        }
        for (const t of tticks) { g.beginPath(); g.moveTo(X(t), top); g.lineTo(X(t), top + ph); g.stroke(); }
        g.textAlign = "left"; g.textBaseline = "alphabetic"; g.fillStyle = ink; g.font = `600 12px ${sans}`;
        g.fillText(`${p.name}${p.unit ? " / " + p.unit : ""}`, P.l, top - 7);
        for (const r of p.refs || []) {
          if (r.v < lo || r.v > hi) continue;
          g.strokeStyle = alert; g.setLineDash([5, 4]);
          g.beginPath(); g.moveTo(P.l, Y(r.v)); g.lineTo(P.l + pw, Y(r.v)); g.stroke(); g.setLineDash([]);
          g.fillStyle = alert; g.font = `11px ${sans}`; g.textAlign = "right";
          g.fillText(r.label, P.l + pw - 2, Y(r.v) - 4); g.textAlign = "left";
        }
        g.save(); g.beginPath(); g.rect(P.l, top - 2, pw, ph + 4); g.clip();
        g.strokeStyle = acc; g.lineWidth = 1.4; g.beginPath();
        let started = false;
        for (const [t, v] of visible) {
          const x = X(t), y = Y(v);
          if (started) g.lineTo(x, y); else { g.moveTo(x, y); started = true; }
        }
        g.stroke();
        const last = visible[visible.length - 1];
        if (last) { g.fillStyle = acc; g.beginPath(); g.arc(X(last[0]), Y(last[1]), 3, 0, 7); g.fill(); }
        g.restore();
        g.strokeStyle = muted; g.beginPath(); g.moveTo(P.l, top); g.lineTo(P.l, top + ph); g.lineTo(P.l + pw, top + ph); g.stroke();
      });
      const bottom = P.t + (n - 1) * (ph + P.gap) + ph;
      g.fillStyle = muted; g.font = `11px ${mono}`; g.textAlign = "center"; g.textBaseline = "top";
      for (const t of tticks) {
        const x = X(t);
        if (x < P.l + 24 || x > P.l + pw - 24) continue; // 贴边的标签会被裁掉一半，不画
        g.fillText(EHP.clock(t), x, bottom + 6);
      }
      if (hover != null && hover >= t0 && hover <= t1) {
        g.strokeStyle = ink; g.globalAlpha = 0.4;
        g.beginPath(); g.moveTo(X(hover), P.t); g.lineTo(X(hover), bottom); g.stroke(); g.globalAlpha = 1;
      }
    }

    function nearest(series, t) {
      if (!series.length) return null;
      let lo = 0, hi = series.length - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (series[m][0] < t) lo = m; else hi = m; }
      return Math.abs(series[lo][0] - t) < Math.abs(series[hi][0] - t) ? series[lo] : series[hi];
    }

    function onMove(e) {
      if (!geo) return;
      const r = canvas.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      if (x < P.l || x > P.l + geo.pw) { hover = null; tip.hidden = true; draw(); return; }
      hover = geo.t0 + ((x - P.l) / geo.pw) * (geo.t1 - geo.t0);
      const lines = [EHP.clock(hover)];
      for (const p of cfg.panels) {
        const pt = nearest(p.series, hover);
        if (pt) lines.push(`${p.name}  ${EHP.fmt(pt[1], p.dp ?? 2)} ${p.unit || ""}`);
      }
      tip.textContent = lines.join("\n");
      tip.hidden = false;
      const pr = canvas.parentElement.getBoundingClientRect();
      let left = x + (r.left - pr.left);
      if (left > pr.width - 190) left -= 200;
      tip.style.left = left + "px";
      tip.style.top = y + (r.top - pr.top) + "px";
      draw();
    }
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", () => { hover = null; tip.hidden = true; draw(); });

    return {
      update(next) { cfg = Object.assign(cfg, next); draw(); },
      draw,
    };
  };
})();
