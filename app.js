// =========================================================================
// NASCAR Momentum — app.js
// Loads data/points_<year>.json + data/colors.json, renders 5 views,
// handles routing, series/season switching, filters, sorts.
// =========================================================================

const STATE = {
  series: "NCS",
  season: 2026,
  view: "form",
  data: null,              // current season's series (races array)
  colors: null,            // full colors.json
  seasonsAvailable: [],
  // form-view settings
  form: { window: "5", search: "" },
  // season-arc view settings
  arc: { selected: new Set() },
  // breakdown view settings
  breakdown: { driver: null },
};

const SERIES_TO_KEY = { NCS: "W", NOS: "B", NTS: "C" };
const FALLBACK_COLOR = "#9ca3af";

// ============================================================
// BOOT
// ============================================================
async function boot() {
  wireUIControls();
  await loadColors();
  await discoverSeasons();
  parseHash();
  // season-picker defaults to latest found
  if (!STATE.seasonsAvailable.includes(STATE.season)) {
    STATE.season = STATE.seasonsAvailable[0] || 2026;
  }
  populateSeasonPicker();
  await loadCurrentData();
  render();
  window.addEventListener("hashchange", () => {
    parseHash();
    render();
  });
}

function parseHash() {
  const h = location.hash.replace("#/", "").split("/");
  const view = h[0];
  if (["form", "arc", "breakdown", "heatmap", "standings"].includes(view)) {
    STATE.view = view;
  } else {
    STATE.view = "form";
  }
}

// ============================================================
// DATA LOADING
// ============================================================
async function loadColors() {
  try {
    const r = await fetch("data/colors.json");
    STATE.colors = await r.json();
  } catch (e) {
    console.warn("Colors file unavailable, using fallbacks", e);
    STATE.colors = { W: {}, B: {}, C: {} };
  }
}

async function discoverSeasons() {
  // Try each year; collect the ones that respond 200
  const years = [];
  for (let y = 2016; y <= 2028; y++) {
    const r = await fetch(`data/points_${y}.json`, { method: "HEAD" })
      .catch(() => null);
    if (r && r.ok) years.push(y);
  }
  // Also fall back to data/points.json (legacy)
  if (years.length === 0) {
    const r = await fetch("data/points.json", { method: "HEAD" }).catch(() => null);
    if (r && r.ok) years.push(2026);
  }
  STATE.seasonsAvailable = years.sort((a, b) => b - a);
}

async function loadCurrentData() {
  const year = STATE.season;
  const urls = [
    `data/points_${year}.json`,
    `data/points.json`,
  ];
  let payload = null;
  let lastErr = null;
  for (const u of urls) {
    try {
      const r = await fetch(u);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      payload = await r.json();
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (!payload) {
    return showError(`Failed to load data: ${lastErr && lastErr.message || "unknown"}`);
  }
  const sCode = STATE.series;
  const seriesBlock = payload.series && payload.series[sCode];
  if (!seriesBlock) {
    return showError(`No data for series ${sCode} in season ${year}`);
  }
  STATE.data = seriesBlock;
  // Update top-bar info
  const races = seriesBlock.races || [];
  const totalRaces = scheduleLengthForSeries(sCode);
  document.getElementById("season-pill").textContent =
    `${year} · R${races.length} / ${totalRaces}`;
  document.getElementById("footer-updated").textContent =
    `Updated ${(payload.generated_at || "").slice(0,10)}`;
  hideError();
}

function scheduleLengthForSeries(series) {
  // Per 2026 regular-season lengths. Good enough for the pill; not critical.
  return { NCS: 36, NOS: 33, NTS: 25 }[series] || "—";
}

function showError(msg) {
  document.querySelectorAll(".view").forEach(v => v.hidden = true);
  const ev = document.getElementById("view-error");
  ev.hidden = false;
  document.getElementById("error-msg").textContent = msg;
}
function hideError() {
  const ev = document.getElementById("view-error");
  if (ev) ev.hidden = true;
}

// ============================================================
// UI CONTROLS
// ============================================================
function wireUIControls() {
  // Series switcher
  document.querySelectorAll("#series-sw button").forEach(b => {
    b.addEventListener("click", async () => {
      document.querySelectorAll("#series-sw button")
        .forEach(x => x.classList.toggle("on", x === b));
      STATE.series = b.dataset.series;
      STATE.arc.selected.clear();
      STATE.breakdown.driver = null;
      await loadCurrentData();
      render();
    });
  });

  // Form-view toggles
  document.querySelectorAll("#view-form .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "window") STATE.form.window = b.dataset.val;
        renderFormTable();
      });
    });
  });
  document.getElementById("form-search")?.addEventListener("input", (e) => {
    STATE.form.search = e.target.value.toLowerCase();
    renderFormTable();
  });

  // Nav links
  document.querySelectorAll(".navlink").forEach(a => {
    a.addEventListener("click", () => {
      // close mobile sidebar if open
      document.getElementById("sidebar")?.classList.remove("open");
    });
  });
  document.getElementById("nav-toggle")?.addEventListener("click", () => {
    document.getElementById("sidebar")?.classList.toggle("open");
  });

  // Arc view buttons
  document.getElementById("arc-clear")?.addEventListener("click", () => {
    STATE.arc.selected.clear();
    renderArc();
  });
  document.getElementById("arc-top10")?.addEventListener("click", () => {
    STATE.arc.selected.clear();
    const totals = computeSeasonTotals();
    totals.slice(0, 10).forEach(t => STATE.arc.selected.add(t.driver));
    renderArc();
  });

  // Breakdown driver picker
  document.getElementById("breakdown-driver")?.addEventListener("change", (e) => {
    STATE.breakdown.driver = e.target.value;
    renderBreakdown();
  });
}

function populateSeasonPicker() {
  const sel = document.getElementById("season-picker");
  if (!sel) return;
  sel.innerHTML = STATE.seasonsAvailable
    .map(y => `<option value="${y}" ${y === STATE.season ? "selected" : ""}>${y}</option>`)
    .join("");
  sel.addEventListener("change", async () => {
    STATE.season = parseInt(sel.value);
    await loadCurrentData();
    render();
  });
}

// ============================================================
// RENDER
// ============================================================
function render() {
  // toggle views
  ["form", "arc", "breakdown", "heatmap", "standings"].forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.hidden = (v !== STATE.view);
  });
  document.querySelectorAll(".navlink").forEach(a => {
    a.classList.toggle("active", a.dataset.view === STATE.view);
  });

  renderMetricBar();

  switch (STATE.view) {
    case "form":       renderFormTable(); break;
    case "arc":        renderArc(); break;
    case "breakdown":  renderBreakdown(); break;
    case "heatmap":    renderHeatmap(); break;
    case "standings":  renderStandings(); break;
  }
}

// ============================================================
// DERIVED METRICS
// ============================================================
function racesSorted() {
  return (STATE.data?.races || [])
    .slice()
    .sort((a, b) => (a.round || 0) - (b.round || 0));
}

function allDrivers() {
  const map = new Map();
  racesSorted().forEach(r => {
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      if (!map.has(d.driver)) {
        map.set(d.driver, {
          driver: d.driver,
          car_number: d.car_number,
          team: d.team,
          manufacturer: d.manufacturer,
          races: [],
        });
      }
      map.get(d.driver).races.push({
        round: r.round,
        finish: d.finish_pos,
        start: d.start_pos,
        s1: d.stage_1_pts || 0,
        s2: d.stage_2_pts || 0,
        fin: d.finish_pts || 0,
        fl: d.fastest_lap_pt || 0,
        total: d.race_pts || 0,
        status: d.status,
      });
    });
  });
  return Array.from(map.values());
}

function computeSeasonTotals() {
  const drivers = allDrivers();
  return drivers.map(d => {
    const total = d.races.reduce((s, r) => s + r.total, 0);
    const avgFinish = mean(d.races.map(r => r.finish).filter(x => x != null));
    return { ...d, total, avgFinish };
  }).sort((a, b) => b.total - a.total);
}

function mean(xs) {
  const a = xs.filter(x => Number.isFinite(x));
  if (a.length === 0) return null;
  return a.reduce((s, x) => s + x, 0) / a.length;
}

// Placeholder Form Rating: 100 - avgFinish*2 over the window.
// Bigger = better. Scaled so ~1st place finishes trend around 95, ~20th around 55.
function formRatingFor(driverRaces, windowType) {
  let slice;
  if (windowType === "5") slice = driverRaces.slice(-5);
  else if (windowType === "10") slice = driverRaces.slice(-10);
  else slice = driverRaces;
  const finishes = slice.map(r => r.finish).filter(x => x != null);
  if (finishes.length === 0) return null;
  const avg = finishes.reduce((s, x) => s + x, 0) / finishes.length;
  // Map: avg finish 1 → 98, 10 → 80, 20 → 60, 30 → 40, 40 → 20
  const rating = Math.max(0, Math.min(100, 100 - (avg - 1) * 2));
  return rating;
}

function seasonTotalRating(driverRaces) {
  return formRatingFor(driverRaces, "season");
}

// ============================================================
// COLORS
// ============================================================
function colorFor(series, carNumber) {
  const k = SERIES_TO_KEY[series];
  const pal = STATE.colors && STATE.colors[k];
  if (pal && pal[carNumber] && pal[carNumber].car) return pal[carNumber].car;
  // deterministic-hash fallback
  return hashColor(`${series}:${carNumber}`);
}
function orgColorFor(series, carNumber) {
  const k = SERIES_TO_KEY[series];
  const pal = STATE.colors && STATE.colors[k];
  if (pal && pal[carNumber] && pal[carNumber].org) return pal[carNumber].org;
  return FALLBACK_COLOR;
}
function hashColor(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i); h = Math.imul(h, 16777619);
  }
  const hue = Math.abs(h) % 360;
  return `hsl(${hue}, 62%, 60%)`;
}
function contrastTextFor(hex) {
  if (!hex || !hex.startsWith("#") || hex.length < 7) return "#000";
  const r = parseInt(hex.substr(1,2), 16);
  const g = parseInt(hex.substr(3,2), 16);
  const b = parseInt(hex.substr(5,2), 16);
  const lum = (0.299*r + 0.587*g + 0.114*b) / 255;
  return lum > 0.6 ? "#000" : "#fff";
}

// ============================================================
// METRIC BAR
// ============================================================
function renderMetricBar() {
  const bar = document.getElementById("metricbar");
  if (!bar || !STATE.data) { bar.innerHTML = ""; return; }
  const races = racesSorted();
  const totals = computeSeasonTotals();
  const lastRace = races[races.length - 1];
  const leader = totals[0];

  // Hottest / coldest = biggest delta between form L5 rating and season rating
  const deltas = allDrivers().map(d => {
    const f = formRatingFor(d.races, "5");
    const s = formRatingFor(d.races, "season");
    return { driver: d.driver, delta: (f != null && s != null) ? f - s : null };
  }).filter(d => d.delta != null);
  const hottest = deltas.slice().sort((a,b) => b.delta - a.delta)[0];
  const coldest = deltas.slice().sort((a,b) => a.delta - b.delta)[0];

  bar.innerHTML = `
    <div class="metric"><span class="k">Leader</span>
      <span class="v">${leader ? `${leader.driver} · ${leader.total}` : "—"}</span></div>
    <div class="metric"><span class="k">Hottest</span>
      <span class="v hot">${hottest ? `${hottest.driver} ${signed(hottest.delta.toFixed(1))}` : "—"}</span></div>
    <div class="metric"><span class="k">Coldest</span>
      <span class="v cold">${coldest ? `${coldest.driver} ${signed(coldest.delta.toFixed(1))}` : "—"}</span></div>
    <div class="metric"><span class="k">Last Race</span>
      <span class="v">${lastRace ? `R${lastRace.round} · ${lastRace.track_code || lastRace.track || ""}` : "—"}</span></div>
  `;
}

function signed(n) {
  const v = parseFloat(n);
  return v > 0 ? `+${n}` : `${n}`;
}

// ============================================================
// VIEW: FORM TABLE
// ============================================================
function renderFormTable() {
  const card = document.getElementById("form-card");
  if (!STATE.data) return;

  const drivers = allDrivers();
  const races = racesSorted();
  // Show last 5 race columns (or fewer if season is short)
  const shownRaces = races.slice(-5);

  // Decorate each driver with ratings
  const decorated = drivers.map(d => ({
    ...d,
    formRating: formRatingFor(d.races, STATE.form.window),
    seasonRating: seasonTotalRating(d.races),
    lastFinishes: d.races.slice(-5).map(r => r.finish),
    totalPts: d.races.reduce((s, r) => s + r.total, 0),
  }));

  const q = STATE.form.search.trim().toLowerCase();
  const filtered = q
    ? decorated.filter(d => d.driver.toLowerCase().includes(q) || d.car_number?.includes(q))
    : decorated;

  filtered.sort((a, b) => (b.formRating ?? -1) - (a.formRating ?? -1));

  const headerCols = shownRaces.map(r =>
    `<th class="num" title="${r.name || ''}">R${r.round}</th>`
  ).join("");

  const rows = filtered.map((d, i) => {
    const delta = (d.formRating != null && d.seasonRating != null)
      ? d.formRating - d.seasonRating : null;
    const carHex = colorFor(STATE.series, d.car_number);
    const txtCol = contrastTextFor(carHex);
    const raceCells = shownRaces.map(r => {
      const mine = d.races.find(x => x.round === r.round);
      if (!mine || mine.finish == null) return `<td class="num"><span class="heat heat-none">·</span></td>`;
      return `<td class="num">${heatCell(mine.finish)}</td>`;
    }).join("");
    const spark = sparkSVG(d.lastFinishes, carHex, 58, 18);
    const trend = trendArrow(delta);
    const ratingCls = delta == null ? "" : delta > 6 ? "hot" : delta < -6 ? "cold" : "";
    return `<tr data-driver="${escapeHTML(d.driver)}">
      <td class="num" style="color: var(--dim)">${i + 1}</td>
      <td><span class="driver-cell">
        <span class="car-tag" style="background:${carHex};color:${txtCol}">${d.car_number}</span>
        <span>${escapeHTML(d.driver)}</span>
      </span></td>
      <td><span class="team-code">${d.team ? teamCodeFromName(d.team) : ""}</span></td>
      ${raceCells}
      <td><span class="form-wrap">${spark}<span class="trend ${trend.cls}">${trend.a}</span></span></td>
      <td class="num">
        <span class="rating-stack">
          <span class="rating-big ${ratingCls}">${d.formRating != null ? d.formRating.toFixed(1) : "—"}</span>
          <span class="rating-small">season ${d.seasonRating != null ? d.seasonRating.toFixed(1) : "—"}</span>
        </span>
      </td>
      <td class="num">${deltaPill(delta)}</td>
      <td class="num" style="color: var(--muted)">${d.totalPts}</td>
    </tr>`;
  }).join("");

  card.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th class="num">#</th>
          <th>Driver</th>
          <th>Team</th>
          ${headerCols}
          <th>Form (L5)</th>
          <th class="num">Rating</th>
          <th class="num">vs Season</th>
          <th class="num">Pts</th>
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="99" class="muted" style="padding:40px;text-align:center">No drivers match.</td></tr>`}</tbody>
    </table>
  `;

  const sub = document.getElementById("form-sub");
  sub.textContent = `${filtered.length} drivers · window: ${STATE.form.window === "season" ? "full season" : `last ${STATE.form.window} races`}`;
}

function heatCell(finish) {
  let cls = "heat-mid";
  if (finish <= 5)  cls = "heat-top";
  else if (finish <= 10) cls = "heat-up";
  else if (finish > 30)  cls = "heat-bot";
  else if (finish > 20)  cls = "heat-down";
  return `<span class="heat ${cls}">${finish}</span>`;
}

function trendArrow(delta) {
  if (delta == null || isNaN(delta)) return { a: "·", cls: "" };
  if (delta >= 6)  return { a: "↑↑", cls: "up" };
  if (delta >= 2)  return { a: "↑",  cls: "up" };
  if (delta <= -6) return { a: "↓↓", cls: "down" };
  if (delta <= -2) return { a: "↓",  cls: "down" };
  return { a: "·", cls: "" };
}

function deltaPill(d) {
  if (d == null) return `<span class="delta-pill zero">—</span>`;
  const cls = d > 0.5 ? "up" : d < -0.5 ? "down" : "zero";
  const s = d > 0 ? "+" : "";
  return `<span class="delta-pill ${cls}">${s}${d.toFixed(1)}</span>`;
}

function sparkSVG(finishes, color, w, h) {
  const valid = finishes.filter(f => f != null);
  if (valid.length < 2) {
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"></svg>`;
  }
  const max = 40, min = 1;
  const pts = finishes.map((f, i) => {
    if (f == null) return null;
    const x = (i / (finishes.length - 1 || 1)) * (w - 2) + 1;
    const y = ((Math.min(f, max) - min) / (max - min)) * (h - 2) + 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).filter(Boolean).join(" ");
  const dots = finishes.map((f, i) => {
    if (f == null) return "";
    const x = (i / (finishes.length - 1 || 1)) * (w - 2) + 1;
    const y = ((Math.min(f, max) - min) / (max - min)) * (h - 2) + 1;
    return `<circle cx="${x}" cy="${y}" r="1.6" fill="${color}"/>`;
  }).join("");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.4" stroke-linejoin="round"/>
    ${dots}
  </svg>`;
}

function teamCodeFromName(team) {
  if (!team) return "";
  // Try to extract a 2-4 letter code in parentheses first
  const m = team.match(/\(([^)]+)\)\s*$/);
  if (m) {
    const name = m[1];
    // Abbreviate common team names
    if (/joe gibbs/i.test(name)) return "JGR";
    if (/hendrick/i.test(name)) return "HMS";
    if (/childress/i.test(name)) return "RCR";
    if (/23xi/i.test(name)) return "23XI";
    if (/penske/i.test(name)) return "PEN";
    if (/rfk|roush/i.test(name)) return "RFK";
    if (/front row/i.test(name)) return "FRM";
    if (/trackhouse/i.test(name)) return "TMS";
    if (/legacy/i.test(name)) return "LMC";
    if (/kaulig/i.test(name)) return "KR";
    if (/spire/i.test(name)) return "SPI";
    return name.split(/\s+/).map(w => w[0]).join("").slice(0, 4).toUpperCase();
  }
  return team.split(/\s+/).map(w => w[0]).join("").slice(0, 4).toUpperCase();
}

// ============================================================
// VIEW: SEASON ARC (cumulative points line chart)
// ============================================================
function renderArc() {
  const svg = document.getElementById("arc-svg");
  if (!STATE.data) return;

  const races = racesSorted();
  if (races.length === 0) {
    svg.innerHTML = `<text x="20" y="40" fill="var(--muted)">No races loaded.</text>`;
    return;
  }

  // Build driver → cumulative points array across races
  const drivers = allDrivers();
  const roundsPresent = races.map(r => r.round);
  const seriesData = drivers.map(d => {
    const byRound = {};
    d.races.forEach(r => { byRound[r.round] = r.total || 0; });
    let cum = 0;
    const pts = roundsPresent.map(rd => {
      if (byRound[rd] != null) cum += byRound[rd];
      return cum;
    });
    return { driver: d.driver, car_number: d.car_number, pts, color: colorFor(STATE.series, d.car_number) };
  });

  // if no selection yet, pick top 5
  if (STATE.arc.selected.size === 0) {
    const totals = computeSeasonTotals();
    totals.slice(0, 5).forEach(t => STATE.arc.selected.add(t.driver));
  }

  const W = 920, H = 420, pad = { top: 16, right: 14, bottom: 26, left: 44 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  const maxPts = Math.max(1, ...seriesData.map(s => s.pts[s.pts.length - 1] || 0));
  const nRaces = roundsPresent.length;

  const xScale = (i) => pad.left + (i / Math.max(1, nRaces - 1)) * innerW;
  const yScale = (v) => pad.top + (1 - v / maxPts) * innerH;

  // gridlines
  const gridlines = [];
  const gridSteps = 5;
  for (let i = 0; i <= gridSteps; i++) {
    const y = pad.top + (i / gridSteps) * innerH;
    const val = Math.round(maxPts * (1 - i / gridSteps));
    gridlines.push(`<line class="gridline" x1="${pad.left}" x2="${W - pad.right}" y1="${y}" y2="${y}"/>`);
    gridlines.push(`<text x="${pad.left - 6}" y="${y + 3}" text-anchor="end" fill="var(--muted)" font-family="var(--mono)" font-size="10">${val}</text>`);
  }
  const xLabels = roundsPresent.map((r, i) =>
    `<text x="${xScale(i)}" y="${H - 8}" text-anchor="middle" fill="var(--muted)" font-family="var(--mono)" font-size="10">R${r}</text>`
  ).join("");

  const lines = seriesData.filter(s => STATE.arc.selected.has(s.driver))
    .map(s => {
      const d = s.pts.map((v, i) => `${xScale(i)},${yScale(v)}`).join(" ");
      return `<g>
        <polyline points="${d}" fill="none" stroke="${s.color}" stroke-width="1.8" stroke-linejoin="round"/>
        <text x="${xScale(nRaces - 1) + 6}" y="${yScale(s.pts[s.pts.length - 1]) + 3}" fill="${s.color}" font-family="var(--mono)" font-size="10">${escapeHTML(s.driver)}</text>
      </g>`;
    }).join("");

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.innerHTML = `${gridlines.join("")}${xLabels}${lines}`;

  renderArcChips(seriesData);
}

function renderArcChips(seriesData) {
  const host = document.getElementById("arc-chips");
  if (!host) return;
  const chips = seriesData
    .filter(s => STATE.arc.selected.has(s.driver))
    .map(s => {
      const txt = contrastTextFor(s.color);
      return `<span class="chip" style="background:${s.color};color:${txt}">
        ${escapeHTML(s.driver)}
        <span class="x" data-driver="${escapeHTML(s.driver)}">×</span>
      </span>`;
    }).join("");
  host.innerHTML = chips;
  host.querySelectorAll(".x").forEach(x => {
    x.addEventListener("click", () => {
      STATE.arc.selected.delete(x.dataset.driver);
      renderArc();
    });
  });
}

// ============================================================
// VIEW: PER-RACE BREAKDOWN (stacked bars)
// ============================================================
function renderBreakdown() {
  const svg = document.getElementById("breakdown-svg");
  if (!STATE.data) return;

  // populate driver picker on first render
  const picker = document.getElementById("breakdown-driver");
  const drivers = allDrivers().sort((a, b) => a.driver.localeCompare(b.driver));
  if (!STATE.breakdown.driver && drivers.length) STATE.breakdown.driver = drivers[0].driver;
  picker.innerHTML = drivers.map(d =>
    `<option value="${escapeHTML(d.driver)}" ${d.driver === STATE.breakdown.driver ? "selected" : ""}>${escapeHTML(d.driver)} (#${d.car_number})</option>`
  ).join("");

  const d = drivers.find(x => x.driver === STATE.breakdown.driver);
  if (!d) { svg.innerHTML = ""; return; }

  const races = racesSorted();
  const rounds = races.map(r => r.round);
  const byRound = {};
  d.races.forEach(r => { byRound[r.round] = r; });
  const data = rounds.map(rd => {
    const r = byRound[rd] || { s1: 0, s2: 0, fin: 0, fl: 0, total: 0 };
    return { round: rd, s1: r.s1 || 0, s2: r.s2 || 0, fin: r.fin || 0, fl: r.fl || 0 };
  });

  const W = 920, H = 340, pad = { top: 16, right: 14, bottom: 28, left: 40 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;
  const maxTot = Math.max(1, ...data.map(r => r.s1 + r.s2 + r.fin + r.fl));
  const barW = innerW / data.length * 0.75;
  const xStep = innerW / data.length;
  const yScale = v => pad.top + (1 - v / maxTot) * innerH;

  const COL_S1 = "#60a5fa";
  const COL_S2 = "#3b82f6";
  const COL_FN = "#7280a0";
  const COL_FL = "#fbbf24";

  const bars = data.map((r, i) => {
    const cx = pad.left + i * xStep + xStep / 2;
    const x = cx - barW / 2;
    let y0 = pad.top + innerH;
    const segs = [
      { v: r.fin, c: COL_FN, label: "Finish" },
      { v: r.s1,  c: COL_S1, label: "Stage 1" },
      { v: r.s2,  c: COL_S2, label: "Stage 2" },
      { v: r.fl,  c: COL_FL, label: "FL" },
    ];
    const segHTML = segs.filter(s => s.v > 0).map(s => {
      const h = (s.v / maxTot) * innerH;
      const y = y0 - h;
      y0 = y;
      return `<rect x="${x}" y="${y}" width="${barW}" height="${h}" fill="${s.c}"><title>${s.label}: ${s.v}</title></rect>`;
    }).join("");
    return `<g>${segHTML}
      <text x="${cx}" y="${H - 10}" text-anchor="middle" fill="var(--muted)" font-family="var(--mono)" font-size="10">R${r.round}</text>
    </g>`;
  }).join("");

  // y grid
  const grids = [];
  for (let i = 0; i <= 5; i++) {
    const y = pad.top + (i / 5) * innerH;
    const v = Math.round(maxTot * (1 - i / 5));
    grids.push(`<line class="gridline" x1="${pad.left}" x2="${W - pad.right}" y1="${y}" y2="${y}"/>`);
    grids.push(`<text x="${pad.left - 6}" y="${y + 3}" text-anchor="end" fill="var(--muted)" font-family="var(--mono)" font-size="10">${v}</text>`);
  }

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.innerHTML = `${grids.join("")}${bars}`;

  // legend
  document.getElementById("breakdown-legend").innerHTML = `
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_FN}"></span>Finish points</span>
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_S1}"></span>Stage 1</span>
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_S2}"></span>Stage 2</span>
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_FL}"></span>Fastest lap</span>
  `;
}

// ============================================================
// VIEW: HEATMAP
// ============================================================
function renderHeatmap() {
  const host = document.getElementById("heatmap-wrap");
  if (!STATE.data) return;
  const races = racesSorted();
  const drivers = computeSeasonTotals(); // sorted by total desc
  if (drivers.length === 0 || races.length === 0) {
    host.innerHTML = `<div class="loading">No data yet.</div>`;
    return;
  }

  const cols = races.length + 1; // +1 for driver label column
  const grid = document.createElement("div");
  grid.className = "heatmap-grid";
  grid.style.gridTemplateColumns = `180px repeat(${races.length}, 28px) 40px`;

  // header row
  const corner = document.createElement("div");
  corner.className = "hm-header hm-header-corner";
  corner.textContent = "Driver";
  grid.appendChild(corner);
  races.forEach(r => {
    const h = document.createElement("div");
    h.className = "hm-header";
    h.textContent = `R${r.round}`;
    h.title = r.name || r.track || "";
    grid.appendChild(h);
  });
  const totalHdr = document.createElement("div");
  totalHdr.className = "hm-header";
  totalHdr.textContent = "Total";
  grid.appendChild(totalHdr);

  // data rows
  drivers.forEach(d => {
    const carHex = colorFor(STATE.series, d.car_number);
    const txt = contrastTextFor(carHex);
    const label = document.createElement("div");
    label.className = "hm-label";
    label.innerHTML = `<span class="car-tag" style="background:${carHex};color:${txt}">${d.car_number}</span><span>${escapeHTML(d.driver)}</span>`;
    grid.appendChild(label);
    const byRound = {};
    d.races.forEach(r => { byRound[r.round] = r; });
    races.forEach(r => {
      const mine = byRound[r.round];
      const cell = document.createElement("div");
      cell.className = "hm-cell";
      if (!mine || mine.finish == null) {
        cell.textContent = "·";
        cell.style.color = "var(--dim)";
      } else {
        const f = mine.finish;
        cell.textContent = f;
        cell.style.background = heatmapColor(f);
        cell.style.color = f <= 15 ? "#06220e" : "#2c0a0a";
      }
      grid.appendChild(cell);
    });
    const total = document.createElement("div");
    total.className = "hm-cell";
    total.textContent = d.total;
    total.style.color = "var(--text)";
    total.style.fontWeight = "600";
    grid.appendChild(total);
  });

  host.innerHTML = "";
  host.appendChild(grid);
}

function heatmapColor(finish) {
  // finish 1 → dark green, 20 → gray, 40 → dark red
  if (finish == null) return "transparent";
  const clamp = (a, lo, hi) => Math.max(lo, Math.min(hi, a));
  const t = clamp(finish, 1, 40);
  if (t <= 20) {
    const k = 1 - (t - 1) / 19;  // 1 → 1.0, 20 → 0.0
    // green intensity
    const a = 0.08 + 0.35 * k;
    return `rgba(63, 217, 122, ${a.toFixed(3)})`;
  } else {
    const k = (t - 20) / 20;  // 20 → 0, 40 → 1
    const a = 0.06 + 0.3 * k;
    return `rgba(255, 107, 107, ${a.toFixed(3)})`;
  }
}

// ============================================================
// VIEW: STANDINGS
// ============================================================
function renderStandings() {
  const table = document.getElementById("standings-table");
  if (!STATE.data) return;
  const totals = computeSeasonTotals();
  // per-driver stage/finish/FL season totals
  const rows = totals.map((d, i) => {
    const sumS1 = d.races.reduce((s, r) => s + r.s1, 0);
    const sumS2 = d.races.reduce((s, r) => s + r.s2, 0);
    const sumFin = d.races.reduce((s, r) => s + r.fin, 0);
    const sumFL = d.races.reduce((s, r) => s + r.fl, 0);
    const wins = d.races.filter(r => r.finish === 1).length;
    const top5 = d.races.filter(r => r.finish <= 5).length;
    const top10 = d.races.filter(r => r.finish <= 10).length;
    const carHex = colorFor(STATE.series, d.car_number);
    const txt = contrastTextFor(carHex);
    return `<tr>
      <td class="num" style="color:var(--dim)">${i + 1}</td>
      <td><span class="driver-cell">
        <span class="car-tag" style="background:${carHex};color:${txt}">${d.car_number}</span>
        <span>${escapeHTML(d.driver)}</span>
      </span></td>
      <td><span class="team-code">${d.team ? teamCodeFromName(d.team) : ""}</span></td>
      <td class="num">${d.races.length}</td>
      <td class="num">${wins}</td>
      <td class="num">${top5}</td>
      <td class="num">${top10}</td>
      <td class="num">${d.avgFinish != null ? d.avgFinish.toFixed(1) : "—"}</td>
      <td class="num">${sumS1}</td>
      <td class="num">${sumS2}</td>
      <td class="num">${sumFL}</td>
      <td class="num">${sumFin}</td>
      <td class="num" style="font-weight:600;color:var(--text)">${d.total}</td>
    </tr>`;
  }).join("");

  table.innerHTML = `
    <thead>
      <tr>
        <th class="num">#</th>
        <th>Driver</th>
        <th>Team</th>
        <th class="num">Starts</th>
        <th class="num">Wins</th>
        <th class="num">T5</th>
        <th class="num">T10</th>
        <th class="num">Avg Fin</th>
        <th class="num">S1</th>
        <th class="num">S2</th>
        <th class="num">FL</th>
        <th class="num">Finish Pts</th>
        <th class="num">Total</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  `;
}

// ============================================================
// UTIL
// ============================================================
function escapeHTML(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ============================================================
// GO
// ============================================================
boot();
