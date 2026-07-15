/* faimar frontend: fetches /api/v1/valuation/{symbol} and renders the
 * price-vs-fair-value chart plus stat tiles. No framework, no build step. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const dashboard = $("dashboard");
  const message = $("message");

  let payload = null; // last successful API response
  let chart = null;
  let rangeYears = 5;

  // ---------- theme ----------

  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function effectiveTheme() {
    const forced = document.documentElement.dataset.theme;
    if (forced) return forced;
    return media.matches ? "dark" : "light";
  }

  $("theme-toggle").addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("faimar-theme", next);
    render();
  });

  const savedTheme = localStorage.getItem("faimar-theme");
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  media.addEventListener("change", render);

  function tokens() {
    const css = getComputedStyle(document.documentElement);
    const get = (name) => css.getPropertyValue(name).trim();
    return {
      surface: get("--surface-1"),
      textSecondary: get("--text-secondary"),
      textMuted: get("--text-muted"),
      gridline: get("--gridline"),
      baseline: get("--baseline"),
      price: get("--series-price"),
      fair: get("--series-fair"),
      washUnder: get("--wash-under"),
      washOver: get("--wash-over"),
    };
  }

  // ---------- formatting ----------

  function money(value, currency, opts = {}) {
    if (value === null || value === undefined) return "—";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
      ...opts,
    }).format(value);
  }

  const compact = (value, currency) =>
    money(value, currency, { notation: "compact", maximumFractionDigits: 1 });

  const pct = (value, digits = 1) =>
    value === null || value === undefined
      ? "—"
      : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;

  function monthLabel(iso) {
    const [y, m] = iso.split("-");
    const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${names[Number(m) - 1]} ’${y.slice(2)}`;
  }

  // ---------- data shaping ----------

  function sliceRange(prices, years) {
    if (!prices.length) return prices;
    const last = new Date(prices[prices.length - 1][0]);
    const cutoff = new Date(last);
    cutoff.setFullYear(cutoff.getFullYear() - years);
    const iso = cutoff.toISOString().slice(0, 10);
    return prices.filter(([d]) => d >= iso);
  }

  /* Linear interpolation of the sparse fair-value points onto the price
   * date axis. Dates before the first known point get null (honest gap). */
  function interpolateFair(dates, points) {
    if (!points.length) return { line: dates.map(() => null), markers: dates.map(() => null) };
    const times = points.map(([d]) => Date.parse(d));
    const values = points.map(([, v]) => v);
    const markerByDate = new Map(points.map(([d, v]) => [d, v]));
    const line = dates.map((d) => {
      const t = Date.parse(d);
      if (t < times[0]) return null;
      if (t >= times[times.length - 1]) return values[values.length - 1];
      let i = 0;
      while (t > times[i + 1]) i++;
      const f = (t - times[i]) / (times[i + 1] - times[i]);
      return values[i] + f * (values[i + 1] - values[i]);
    });
    // Snap each fair-value point to the nearest plotted date so markers land on the axis.
    const markers = dates.map(() => null);
    for (const [d, v] of markerByDate) {
      const t = Date.parse(d);
      let best = -1;
      let bestDist = Infinity;
      dates.forEach((pd, i) => {
        const dist = Math.abs(Date.parse(pd) - t);
        if (dist < bestDist) { bestDist = dist; best = i; }
      });
      if (best >= 0 && bestDist < 45 * 86400e3) markers[best] = v;
    }
    return { line, markers };
  }

  // ---------- chart ----------

  const crosshair = {
    id: "crosshair",
    afterDraw(c) {
      const active = c.tooltip?.getActiveElements?.();
      if (!active || !active.length) return;
      const x = active[0].element.x;
      const { top, bottom } = c.chartArea;
      const ctx = c.ctx;
      ctx.save();
      ctx.strokeStyle = tokens().baseline;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.restore();
    },
  };

  function renderChart() {
    const t = tokens();
    const prices = sliceRange(payload.history.prices, rangeYears);
    const dates = prices.map(([d]) => d);
    const closes = prices.map(([, v]) => v);
    const { line: fairLine, markers } = interpolateFair(dates, payload.history.fair_values);
    const hasFair = fairLine.some((v) => v !== null);
    const currency = payload.currency;

    if (chart) chart.destroy();
    chart = new Chart($("chart"), {
      type: "line",
      data: {
        labels: dates,
        datasets: [
          {
            label: "Share price",
            data: closes,
            borderColor: t.price,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: t.price,
            pointHoverBorderColor: t.surface,
            pointHoverBorderWidth: 2,
            tension: 0,
            fill: hasFair ? { target: 1, above: t.washOver, below: t.washUnder } : false,
          },
          {
            label: "Estimated fair value",
            data: fairLine,
            borderColor: t.fair,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 0,
            spanGaps: false,
            tension: 0,
          },
          {
            label: "fair-value-markers",
            data: markers,
            showLine: false,
            pointRadius: 4.5,
            pointHoverRadius: 5,
            pointBackgroundColor: t.fair,
            pointBorderColor: t.surface,
            pointBorderWidth: 2,
          },
        ],
      },
      plugins: [crosshair],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            grid: { display: false },
            border: { color: t.baseline },
            ticks: {
              color: t.textMuted,
              maxTicksLimit: 8,
              maxRotation: 0,
              callback(value) { return monthLabel(this.getLabelForValue(value)); },
            },
          },
          y: {
            grid: { color: t.gridline, drawTicks: false },
            border: { display: false },
            ticks: {
              color: t.textMuted,
              maxTicksLimit: 6,
              callback: (v) => money(v, currency, { maximumFractionDigits: 0 }),
            },
          },
        },
        plugins: {
          legend: {
            labels: {
              color: t.textSecondary,
              usePointStyle: true,
              pointStyle: "line",
              boxWidth: 24,
              filter: (item) => item.text !== "fair-value-markers",
            },
          },
          tooltip: {
            backgroundColor: t.surface,
            titleColor: t.textMuted,
            bodyColor: t.textSecondary,
            borderColor: t.gridline,
            borderWidth: 1,
            usePointStyle: true,
            boxWidth: 12,
            boxHeight: 2,
            filter: (item) => item.dataset.label !== "fair-value-markers",
            callbacks: {
              title: (items) => items[0]?.label ?? "",
              labelPointStyle: () => ({ pointStyle: "line", rotation: 0 }),
              label(item) {
                return ` ${money(item.parsed.y, currency)}  ${item.dataset.label}`;
              },
              afterBody(items) {
                const price = items.find((i) => i.dataset.label === "Share price");
                const fair = items.find((i) => i.dataset.label === "Estimated fair value");
                if (!price || !fair || fair.parsed.y === null) return "";
                const up = ((fair.parsed.y - price.parsed.y) / price.parsed.y) * 100;
                return `Upside ${pct(up)}`;
              },
            },
          },
        },
      },
    });
  }

  // ---------- tiles / table / assumptions ----------

  function setText(id, text) { $(id).textContent = text; }

  function renderTiles() {
    const c = payload.currency;
    setText("tile-price", money(payload.price, c));
    setText("tile-price-sub", `${payload.symbol} · ${payload.name}`);
    setText("tile-fair", money(payload.fair_value, c));
    setText(
      "tile-fair-sub",
      payload.method === "dcf" ? "2-stage discounted cash flow"
        : payload.method === "analyst_target" ? "mean analyst price target"
        : "insufficient data"
    );

    const upside = $("tile-upside");
    upside.textContent = pct(payload.upside_pct);
    upside.className = "value" + (payload.upside_pct > 0 ? " up" : payload.upside_pct < 0 ? " down" : "");

    const verdicts = {
      undervalued: { label: "Undervalued", color: "var(--status-good)", icon: "▲" },
      overvalued: { label: "Overvalued", color: "var(--status-critical)", icon: "▼" },
      fair: { label: "About fair value", color: "var(--text-muted)", icon: "◆" },
      unknown: { label: "Unknown", color: "var(--text-muted)", icon: "?" },
    };
    const v = verdicts[payload.verdict] ?? verdicts.unknown;
    const badge = $("tile-verdict");
    badge.textContent = "";
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = v.color;
    badge.append(dot, document.createTextNode(`${v.icon} ${v.label}`));
  }

  function renderTable() {
    const c = payload.currency;
    const container = $("table-view");
    container.textContent = "";
    const table = document.createElement("table");
    const head = table.insertRow();
    for (const h of ["Date", "Estimated fair value", "Share price"]) {
      const th = document.createElement("th");
      th.textContent = h;
      head.append(th);
    }
    const prices = payload.history.prices;
    const priceOn = (iso) => {
      let last = null;
      for (const [d, v] of prices) { if (d <= iso) last = v; else break; }
      return last;
    };
    for (const [date, fv] of payload.history.fair_values) {
      const row = table.insertRow();
      row.insertCell().textContent = date;
      row.insertCell().textContent = money(fv, c);
      row.insertCell().textContent = money(priceOn(date), c);
    }
    container.append(table);
  }

  function renderAssumptions() {
    const a = payload.assumptions;
    const c = payload.currency;
    setText(
      "method-note",
      payload.method === "dcf"
        ? `Levered free cash flow grown at ${(a.growth_rate * 100).toFixed(1)}% (${a.growth_source}), fading to ` +
          `${(a.terminal_growth * 100).toFixed(1)}% over ${a.forecast_years} years, discounted at ${(a.discount_rate * 100).toFixed(1)}%.`
        : payload.method === "analyst_target"
          ? "Free cash flow is negative or too small relative to market cap for a trailing-FCF DCF to be informative, so fair value uses the mean analyst price target instead."
          : "Not enough data to estimate a fair value for this symbol."
    );
    const entries = [
      ["Base FCF (TTM)", compact(a.base_fcf_ttm, c)],
      ["FCF yield", a.fcf_yield !== null && a.fcf_yield !== undefined ? `${(a.fcf_yield * 100).toFixed(2)}%` : "—"],
      ["DCF value (secondary)", money(a.dcf_fair_value, c)],
      ["Growth rate", a.growth_rate !== null ? `${(a.growth_rate * 100).toFixed(1)}% (${a.growth_source})` : "—"],
      ["Discount rate", `${(a.discount_rate * 100).toFixed(1)}% (CAPM)`],
      ["Terminal growth", `${(a.terminal_growth * 100).toFixed(1)}%`],
      ["Risk-free rate", `${(a.risk_free * 100).toFixed(1)}% (10Y treasury)`],
      ["Beta", a.beta !== null && a.beta !== undefined ? a.beta.toFixed(2) : "—"],
      ["Shares outstanding", a.shares_outstanding ? Intl.NumberFormat("en-US", { notation: "compact" }).format(a.shares_outstanding) : "—"],
      ["Analyst target (mean)", money(payload.analyst?.target_mean, c)],
      ["Analyst range", payload.analyst?.target_low ? `${money(payload.analyst.target_low, c)} – ${money(payload.analyst.target_high, c)}` : "—"],
    ];
    const dl = $("assumptions-list");
    dl.textContent = "";
    for (const [term, def] of entries) {
      const dt = document.createElement("dt");
      dt.textContent = term;
      const dd = document.createElement("dd");
      dd.textContent = def;
      dl.append(dt, dd);
    }
  }

  function render() {
    if (!payload) return;
    setText("chart-subtitle",
      payload.method === "dcf"
        ? "Green wash: price below estimated fair value (upside). Red wash: price above it."
        : payload.method === "analyst_target"
          ? "Fair value shown for today only — analyst targets have no free history."
          : "No fair value estimate available for this symbol.");
    renderTiles();
    renderChart();
    renderTable();
    renderAssumptions();
  }

  // ---------- lookup flow ----------

  async function lookup(symbol) {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    message.textContent = `Evaluating ${sym}…`;
    message.className = "";
    dashboard.classList.add("loading");
    try {
      const res = await fetch(`/api/v1/valuation/${encodeURIComponent(sym)}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      payload = await res.json();
      dashboard.classList.remove("empty");
      message.textContent = "";
      history.replaceState(null, "", `#${payload.symbol}`);
      render();
    } catch (err) {
      message.textContent = err.message;
      message.className = "error";
    } finally {
      dashboard.classList.remove("loading");
    }
  }

  $("lookup").addEventListener("submit", (e) => {
    e.preventDefault();
    lookup($("symbol").value);
  });

  for (const btn of document.querySelectorAll(".ranges button")) {
    btn.addEventListener("click", () => {
      rangeYears = Number(btn.dataset.range);
      for (const b of document.querySelectorAll(".ranges button")) {
        b.setAttribute("aria-pressed", String(b === btn));
      }
      renderChart();
    });
  }

  const initial = location.hash.replace("#", "");
  if (initial) {
    $("symbol").value = initial;
    lookup(initial);
  }
})();
