// =========================================================================
// NASCAR Momentum — app.js
// Loads data/points_<year>.json + data/colors.json, renders 6 views,
// handles routing, series/season/entity switching, filters, sorts.
// =========================================================================

const STATE = {
  series: "NCS",
  season: 2026,
  view: "form",
  entity: "driver",         // driver | owner  — global toggle
  data: null,               // current season's series (races array)
  colors: null,             // full colors.json
  seasonsAvailable: [],
  // form-view settings
  form: { window: "5", search: "", ftOnly: true, sortKey: null, sortDir: "desc" },
  // season-arc view settings
  arc: { selected: new Set() },
  // breakdown view settings
  breakdown: { driver: null },
  // trajectory view settings
  trajectory: { mode: "season", show: "all", labels: "top12" },
  // standings view sort
  standings: { sortKey: "total", sortDir: "desc" },
};

const SERIES_TO_KEY = { NCS: "W", NOS: "B", NTS: "C" };
const FALLBACK_COLOR = "#9ca3af";
const VIEWS = ["form", "arc", "breakdown", "trajectory", "heatmap", "standings"];

// ============================================================
// BOOT
// ============================================================
async function boot() {
  wireUIControls();
  await loadColors();
  await discoverSeasons();
  parseHash();
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
  STATE.view = VIEWS.includes(view) ? view : "form";
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
  const years = [];
  for (let y = 2016; y <= 2028; y++) {
    const r = await fetch(`data/points_${y}.json`, { method: "HEAD" })
      .catch(() => null);
    if (r && r.ok) years.push(y);
  }
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
  const races = seriesBlock.races || [];
  const totalRaces = scheduleLengthForSeries(sCode);
  document.getElementById("season-pill").textContent =
    `${year} · R${races.length} / ${totalRaces}`;
  document.getElementById("footer-updated").textContent =
    `Updated ${(payload.generated_at || "").slice(0,10)}`;
  hideError();
}

function scheduleLengthForSeries(series) {
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

  // Entity switcher (Driver vs Owner/Car) — global
  document.querySelectorAll("#entity-sw button").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#entity-sw button")
        .forEach(x => x.classList.toggle("on", x === b));
      STATE.entity = b.dataset.entity;
      STATE.arc.selected.clear();
      STATE.breakdown.driver = null;
      render();
    });
  });

  // Form-view toggles (window + full-time filter)
  document.querySelectorAll("#view-form .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "window") STATE.form.window = b.dataset.val;
        if (group === "ftfilter") STATE.form.ftOnly = (b.dataset.val === "ft");
        renderFormTable();
      });
    });
  });
  document.getElementById("form-search")?.addEventListener("input", (e) => {
    STATE.form.search = e.target.value.toLowerCase();
    renderFormTable();
  });

  // Trajectory-view toggles
  document.querySelectorAll("#view-trajectory .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "traj-mode") STATE.trajectory.mode = b.dataset.val;
        if (group === "traj-show") STATE.trajectory.show = b.dataset.val;
        if (group === "traj-labels") STATE.trajectory.labels = b.dataset.val;
        renderTrajectory();
      });
    });
  });

  // Nav links
  document.querySelectorAll(".navlink").forEach(a => {
    a.addEventListener("click", () => {
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
    totals.slice(0, 10).forEach(t => STATE.arc.selected.add(entityKey(t)));
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
  VIEWS.forEach(v => {
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
    case "trajectory": renderTrajectory(); break;
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

// Group by driver OR by car_number (owner mode).
// In owner mode the display name is "#NN — <primary driver>" (or list of drivers
// if the car was shared); driver swaps accumulate in one bucket.
function allEntities() {
  const map = new Map();
  racesSorted().forEach(r => {
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      const key = (STATE.entity === "owner")
        ? `#${d.car_number}`
        : d.driver;
      if (!map.has(key)) {
        map.set(key, {
          key,
          driver: d.driver,              // primary / most-recent
          driversSet: new Set(),         // all drivers that drove this car
          car_number: d.car_number,
          team: d.team,
          manufacturer: d.manufacturer,
          races: [],
        });
      }
      const e = map.get(key);
      e.driversSet.add(d.driver);
      // keep most-recent driver as primary display
      e.driver = d.driver;
      e.team = d.team;
      e.manufacturer = d.manufacturer || e.manufacturer;
      e.races.push({
        round: r.round,
        finish: d.finish_pos,
        start: d.start_pos,
        s1: d.stage_1_pts || 0,
        s2: d.stage_2_pts || 0,
        fin: d.finish_pts || 0,
        fl: d.fastest_lap_pt || 0,
        total: d.race_pts || 0,
        status: d.status,
        driver: d.driver,
      });
    });
  });
  // Convert driversSet → array sorted by race count in this car
  return Array.from(map.values()).map(e => {
    const counts = {};
    e.races.forEach(r => { counts[r.driver] = (counts[r.driver] || 0) + 1; });
    const drivers = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    return { ...e, drivers };
  });
}

// Backward-compat name kept for existing callers we didn't rewrite internally
function allDrivers() { return allEntities(); }

// The label we show in chips, callouts, etc.
function displayName(entity) {
  if (STATE.entity === "owner") {
    if (entity.drivers && entity.drivers.length > 1) {
      return `#${entity.car_number} · ${entity.drivers[0]} +${entity.drivers.length - 1}`;
    }
    return `#${entity.car_number} · ${entity.driver}`;
  }
  return entity.driver;
}
// Key used in Sets (arc selection, etc.)
function entityKey(entity) {
  return (STATE.entity === "owner") ? `#${entity.car_number}` : entity.driver;
}

function computeSeasonTotals() {
  const entities = allEntities();
  return entities.map(d => {
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
// Bigger = better. 1st → 98, 10th → 80, 20th → 60, 30th → 40, 40th → 20.
function formRatingFor(driverRaces, windowType) {
  let slice;
  if (windowType === "5") slice = driverRaces.slice(-5);
  else if (windowType === "10") slice = driverRaces.slice(-10);
  else slice = driverRaces;
  const finishes = slice.map(r => r.finish).filter(x => x != null);
  if (finishes.length === 0) return null;
  const avg = finishes.reduce((s, x) => s + x, 0) / finishes.length;
  const rating = Math.max(0, Math.min(100, 100 - (avg - 1) * 2));
  return rating;
}

function seasonTotalRating(driverRaces) {
  return formRatingFor(driverRaces, "season");
}

// Full-time detector: started every race this season (our current definition).
function isFullTime(entity) {
  const totalRaces = racesSorted().length;
  return entity.races.length >= totalRaces && totalRaces > 0;
}

// ============================================================
// COLORS
// ============================================================
function colorFor(series, carNumber) {
  const k = SERIES_TO_KEY[series];
  const pal = STATE.colors && STATE.colors[k];
  if (pal && pal[carNumber] && pal[carNumber].car) return pal[carNumber].car;
  return hashColor(`${series}:${carNumber}`);
}
function orgColorFor(series, carNumber) {
  const k = SERIES_TO_KEY[series];
  const pal = STATE.colors && STATE.colors[k];
  if (pal && pal[carNumber] && pal[carNumber].org) return pal[carNumber].org;
  return FALLBACK_COLOR;
}
function teamCodeFromPalette(series, carNumber) {
  const k = SERIES_TO_KEY[series];
  const pal = STATE.colors && STATE.colors[k];
  if (pal && pal[carNumber] && pal[carNumber].team) return pal[carNumber].team;
  return null;
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

  // Hottest/coldest from eligible (full-time) entities only, so part-timers
  // with one good road-course run don't top the leaderboard.
  const deltas = allEntities().filter(isFullTime).map(d => {
    const f = formRatingFor(d.races, "5");
    const s = formRatingFor(d.races, "season");
    return { entity: d, delta: (f != null && s != null) ? f - s : null };
  }).filter(d => d.delta != null);
  const hottest = deltas.slice().sort((a,b) => b.delta - a.delta)[0];
  const coldest = deltas.slice().sort((a,b) => a.delta - b.delta)[0];

  bar.innerHTML = `
    <div class="metric"><span class="k">Leader</span>
      <span class="v">${leader ? `${escapeHTML(displayName(leader))} · ${leader.total}` : "—"}</span></div>
    <div class="metric"><span class="k">Hottest</span>
      <span class="v hot">${hottest ? `${escapeHTML(displayName(hottest.entity))} ${signed(hottest.delta.toFixed(1))}` : "—"}</span></div>
    <div class="metric"><span class="k">Coldest</span>
      <span class="v cold">${coldest ? `${escapeHTML(displayName(coldest.entity))} ${signed(coldest.delta.toFixed(1))}` : "—"}</span></div>
    <div class="metric"><span class="k">Last Race</span>
      <span class="v">${lastRace ? `R${lastRace.round} · ${lastRace.track_code || lastRace.track || ""}` : "—"}</span></div>
  `;
}

function signed(n) {
  const v = parseFloat(n);
  return v > 0 ? `+${n}` : `${n}`;
}

// ============================================================
// SORT HELPER (used by Form + Standings)
// ============================================================
function sortRows(rows, key, dir) {
  const mul = dir === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const va = a[key], vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;     // nulls always last
    if (vb == null) return -1;
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * mul;
    return String(va).localeCompare(String(vb)) * mul;
  });
}

// ============================================================
// VIEW: FORM TABLE
// ============================================================
function renderFormTable() {
  const card = document.getElementById("form-card");
  if (!STATE.data) return;

  const entities = allEntities();
  const races = racesSorted();
  const shownRaces = races.slice(-5);

  // Build decorated rows
  let decorated = entities.map(d => {
    const formRating = formRatingFor(d.races, STATE.form.window);
    const seasonRating = seasonTotalRating(d.races);
    const deltaR = (formRating != null && seasonRating != null) ? formRating - seasonRating : null;
    const lastFinishes = d.races.slice(-5).map(r => r.finish);
    const totalPts = d.races.reduce((s, r) => s + r.total, 0);
    const avgFinish = mean(d.races.map(r => r.finish).filter(x => x != null));
    return {
      ...d,
      formRating, seasonRating, deltaR,
      lastFinishes, totalPts, avgFinish,
      fullTime: isFullTime(d),
    };
  });

  // Full-time filter (default on)
  if (STATE.form.ftOnly) {
    decorated = decorated.filter(d => d.fullTime);
  }

  // Search
  const q = STATE.form.search.trim().toLowerCase();
  if (q) {
    decorated = decorated.filter(d =>
      d.driver.toLowerCase().includes(q) ||
      (d.car_number || "").toLowerCase().includes(q) ||
      (d.drivers || []).some(n => n.toLowerCase().includes(q))
    );
  }

  // Sort: user key, else default by formRating desc
  const sortKey = STATE.form.sortKey || "formRating";
  const sortDir = STATE.form.sortKey ? STATE.form.sortDir : "desc";
  decorated = sortRows(decorated, sortKey, sortDir);

  const headerCols = shownRaces.map(r =>
    `<th class="num" title="${escapeHTML(r.name || '')}">R${r.round}</th>`
  ).join("");

  const rows = decorated.map((d, i) => {
    const carHex = colorFor(STATE.series, d.car_number);
    const txtCol = contrastTextFor(carHex);
    const raceCells = shownRaces.map(r => {
      const mine = d.races.find(x => x.round === r.round);
      if (!mine || mine.finish == null) return `<td class="num"><span class="heat heat-none">·</span></td>`;
      return `<td class="num">${heatCell(mine.finish)}</td>`;
    }).join("");
    const spark = sparkSVG(d.lastFinishes, carHex, 58, 18);
    const trend = trendArrow(d.deltaR);
    const ratingCls = d.deltaR == null ? "" : d.deltaR > 6 ? "hot" : d.deltaR < -6 ? "cold" : "";
    const teamPill = renderTeamPill(STATE.series, d.car_number, d.team);
    return `<tr data-driver="${escapeHTML(d.driver)}">
      <td class="num" style="color: var(--dim)">${i + 1}</td>
      <td><span class="driver-cell">
        <span class="car-tag" style="background:${carHex};color:${txtCol}">${d.car_number}</span>
        <span>${escapeHTML(displayName(d))}</span>
      </span></td>
      <td>${teamPill}</td>
      ${raceCells}
      <td><span class="form-wrap">${spark}<span class="trend ${trend.cls}">${trend.a}</span></span></td>
      <td class="num">
        <span class="rating-stack">
          <span class="rating-big ${ratingCls}">${d.formRating != null ? d.formRating.toFixed(1) : "—"}</span>
          <span class="rating-small">season ${d.seasonRating != null ? d.seasonRating.toFixed(1) : "—"}</span>
        </span>
      </td>
      <td class="num">${deltaPill(d.deltaR)}</td>
      <td class="num" style="color: var(--muted)">${d.totalPts}</td>
    </tr>`;
  }).join("");

  const th = (key, label, numeric) => {
    const active = STATE.form.sortKey === key;
    const cls = `sortable ${numeric ? "num" : ""} ${active ? "sort-" + STATE.form.sortDir : ""}`.trim();
    const arrow = active ? (STATE.form.sortDir === "asc" ? "▲" : "▼") : "↕";
    return `<th class="${cls}" data-sort="${key}">${label}<span class="sort-arrow">${arrow}</span></th>`;
  };

  card.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th class="num">#</th>
          ${th("driver", "Driver", false)}
          ${th("team", "Team", false)}
          ${headerCols}
          <th>Form (L5)</th>
          ${th("formRating", "Rating", true)}
          ${th("deltaR", "vs Season", true)}
          ${th("totalPts", "Pts", true)}
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="99" class="muted" style="padding:40px;text-align:center">No drivers match.</td></tr>`}</tbody>
    </table>
  `;

  // wire sortable headers
  card.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (STATE.form.sortKey === key) {
        STATE.form.sortDir = STATE.form.sortDir === "asc" ? "desc" : "asc";
      } else {
        STATE.form.sortKey = key;
        STATE.form.sortDir = (key === "driver" || key === "team") ? "asc" : "desc";
      }
      renderFormTable();
    });
  });

  const sub = document.getElementById("form-sub");
  const ftNote = STATE.form.ftOnly ? "full-time only" : "all entrants";
  sub.textContent = `${decorated.length} ${STATE.entity === "owner" ? "cars" : "drivers"} · ${ftNote} · window: ${STATE.form.window === "season" ? "full season" : `last ${STATE.form.window} races`}`;
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

// ---- Team code / pill rendering ------------------------------------------
function teamCodeFromName(team) {
  if (!team) return "";
  const m = team.match(/\(([^)]+)\)\s*$/);
  if (m) {
    const name = m[1];
    if (/joe gibbs/i.test(name)) return "JGR";
    if (/hendrick/i.test(name)) return "HMS";
    if (/childress/i.test(name)) return "RCR";
    if (/23xi/i.test(name)) return "23XI";
    if (/penske/i.test(name)) return "PEN";
    if (/rfk|roush/i.test(name)) return "RFR";
    if (/front row/i.test(name)) return "FRM";
    if (/trackhouse/i.test(name)) return "TMS";
    if (/legacy/i.test(name)) return "LMC";
    if (/kaulig/i.test(name)) return "KR";
    if (/spire/i.test(name)) return "SPI";
    if (/jr motorsports/i.test(name)) return "JRM";
    if (/haas/i.test(name)) return "GH";
    if (/wood brothers/i.test(name)) return "WMS";
    if (/rick ware/i.test(name)) return "RWR";
    if (/hyak/i.test(name)) return "HYAK";
    return name.split(/\s+/).map(w => w[0]).join("").slice(0, 4).toUpperCase();
  }
  return team.split(/\s+/).map(w => w[0]).join("").slice(0, 4).toUpperCase();
}

// Render a colored team pill using palette team-code + org color.
// Falls back to sponsor-string parsing if colors.json doesn't have the entry.
function renderTeamPill(series, carNumber, teamString) {
  const palTeam = teamCodeFromPalette(series, carNumber);
  const orgHex = orgColorFor(series, carNumber);
  const code = palTeam || teamCodeFromName(teamString) || "";
  if (!code) return `<span class="team-code">—</span>`;
  const bg = (orgHex && orgHex !== FALLBACK_COLOR) ? orgHex : "transparent";
  const textCol = contrastTextFor(bg);
  const borderCol = (bg === "transparent") ? "var(--border)" : "transparent";
  return `<span class="team-pill" style="background:${bg};color:${textCol};border:1px solid ${borderCol}">${escapeHTML(code)}</span>`;
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

  const entities = allEntities();
  const roundsPresent = races.map(r => r.round);
  const seriesData = entities.map(d => {
    const byRound = {};
    d.races.forEach(r => { byRound[r.round] = r.total || 0; });
    let cum = 0;
    const pts = roundsPresent.map(rd => {
      if (byRound[rd] != null) cum += byRound[rd];
      return cum;
    });
    return {
      key: entityKey(d),
      label: displayName(d),
      car_number: d.car_number,
      pts,
      color: colorFor(STATE.series, d.car_number),
      entity: d,
    };
  });

  if (STATE.arc.selected.size === 0) {
    const totals = computeSeasonTotals();
    totals.slice(0, 5).forEach(t => STATE.arc.selected.add(entityKey(t)));
  }

  // WIDER right pad so end-of-line labels are never clipped.
  const W = 980, H = 420, pad = { top: 16, right: 140, bottom: 26, left: 48 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  const maxPts = Math.max(1, ...seriesData.map(s => s.pts[s.pts.length - 1] || 0));
  const nRaces = roundsPresent.length;

  const xScale = (i) => pad.left + (i / Math.max(1, nRaces - 1)) * innerW;
  const yScale = (v) => pad.top + (1 - v / maxPts) * innerH;

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

  // End-of-line labels: if two labels would collide vertically, nudge them apart.
  const active = seriesData
    .filter(s => STATE.arc.selected.has(s.key))
    .map(s => ({ ...s, labelY: yScale(s.pts[s.pts.length - 1]) }))
    .sort((a, b) => a.labelY - b.labelY);
  const MIN_GAP = 12;
  for (let i = 1; i < active.length; i++) {
    if (active[i].labelY - active[i - 1].labelY < MIN_GAP) {
      active[i].labelY = active[i - 1].labelY + MIN_GAP;
    }
  }

  const lines = active.map(s => {
    const d = s.pts.map((v, i) => `${xScale(i)},${yScale(v)}`).join(" ");
    const xEnd = xScale(nRaces - 1);
    const yEnd = yScale(s.pts[s.pts.length - 1]);
    // connector if the label was nudged
    const connector = Math.abs(s.labelY - yEnd) > 2
      ? `<line x1="${xEnd + 2}" y1="${yEnd}" x2="${xEnd + 5}" y2="${s.labelY}" stroke="${s.color}" stroke-width="0.8" opacity="0.6"/>`
      : "";
    return `<g>
      <polyline points="${d}" fill="none" stroke="${s.color}" stroke-width="1.8" stroke-linejoin="round"/>
      ${connector}
      <text x="${xEnd + 7}" y="${s.labelY + 3}" fill="${s.color}" font-family="var(--mono)" font-size="10">${escapeHTML(s.label)}</text>
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
    .filter(s => STATE.arc.selected.has(s.key))
    .map(s => {
      const txt = contrastTextFor(s.color);
      return `<span class="chip" style="background:${s.color};color:${txt}">
        ${escapeHTML(s.label)}
        <span class="x" data-key="${escapeHTML(s.key)}">×</span>
      </span>`;
    }).join("");
  host.innerHTML = chips;
  host.querySelectorAll(".x").forEach(x => {
    x.addEventListener("click", () => {
      STATE.arc.selected.delete(x.dataset.key);
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

  const picker = document.getElementById("breakdown-driver");
  const entities = allEntities().sort((a, b) => displayName(a).localeCompare(displayName(b)));
  if (!STATE.breakdown.driver && entities.length) STATE.breakdown.driver = entities[0].driver;
  picker.innerHTML = entities.map(d =>
    `<option value="${escapeHTML(d.driver)}" ${d.driver === STATE.breakdown.driver ? "selected" : ""}>${escapeHTML(displayName(d))}</option>`
  ).join("");

  const d = entities.find(x => x.driver === STATE.breakdown.driver) || entities[0];
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

  document.getElementById("breakdown-legend").innerHTML = `
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_FN}"></span>Finish points</span>
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_S1}"></span>Stage 1</span>
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_S2}"></span>Stage 2</span>
    <span class="legend-item"><span class="legend-swatch" style="background:${COL_FL}"></span>Fastest lap</span>
  `;
}

// ============================================================
// VIEW: TRAJECTORY (stage pts vs finish pts)
// ============================================================
function renderTrajectory() {
  const svg = document.getElementById("trajectory-svg");
  if (!STATE.data) return;

  const races = racesSorted();
  const allE = allEntities();
  // Full-time only (same rule as Form Table default)
  const eligible = allE.filter(isFullTime);

  if (eligible.length === 0) {
    svg.innerHTML = `<text x="20" y="40" fill="var(--muted)">Not enough data yet.</text>`;
    document.getElementById("trajectory-legend").innerHTML = "";
    document.getElementById("trajectory-over").innerHTML = "";
    document.getElementById("trajectory-under").innerHTML = "";
    return;
  }

  // Compute season avgs and last-5 avgs per entity
  const pts = eligible.map(d => {
    const n = d.races.length;
    const nL5 = Math.min(5, n);
    const last5 = d.races.slice(-nL5);
    const stageSeason = d.races.reduce((s, r) => s + (r.s1 + r.s2), 0) / n;
    const finSeason = d.races.reduce((s, r) => s + r.fin, 0) / n;
    const totalSeason = d.races.reduce((s, r) => s + r.total, 0) / n;
    const stageL5 = last5.reduce((s, r) => s + (r.s1 + r.s2), 0) / nL5;
    const finL5 = last5.reduce((s, r) => s + r.fin, 0) / nL5;
    return {
      entity: d,
      xSeason: stageSeason,
      ySeason: finSeason,
      xForm: stageL5,
      yForm: finL5,
      totalSeason,
      label: displayName(d),
      color: colorFor(STATE.series, d.car_number),
    };
  });

  // Regression on season points (stable baseline)
  const regPts = pts.map(p => ({ x: p.xSeason, y: p.ySeason }));
  const { a, b } = regression(regPts);

  // Residuals (season-based; stable across mode toggles)
  const withResid = pts.map(p => {
    const expected = a + b * p.xSeason;
    return { ...p, expected, resid: p.ySeason - expected };
  });

  // Filter: outperform / underperform / all
  let shown = withResid;
  if (STATE.trajectory.show === "outperform") shown = withResid.filter(p => p.resid > 0);
  if (STATE.trajectory.show === "underperform") shown = withResid.filter(p => p.resid < 0);

  // Labels: top 12 by total season pts
  const labelKeys = new Set();
  if (STATE.trajectory.labels === "all") {
    shown.forEach(p => labelKeys.add(entityKey(p.entity)));
  } else if (STATE.trajectory.labels === "top12") {
    const top12 = [...withResid].sort((x, y) => y.totalSeason - x.totalSeason).slice(0, 12);
    top12.forEach(p => labelKeys.add(entityKey(p.entity)));
  }

  // ===== chart geometry =====
  const W = 980, H = 540;
  const pad = { top: 26, right: 110, bottom: 48, left: 62 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  const xMaxRaw = Math.max(8, ...pts.map(p => Math.max(p.xSeason, p.xForm)));
  const yMaxRaw = Math.max(30, ...pts.map(p => Math.max(p.ySeason, p.yForm)));
  const xMax = Math.ceil(xMaxRaw / 2) * 2;
  const yMax = Math.ceil(yMaxRaw / 5) * 5;
  const xScale = v => pad.left + (v / xMax) * innerW;
  const yScale = v => pad.top + (1 - v / yMax) * innerH;

  const svgNS = "http://www.w3.org/2000/svg";
  // preserve defs
  const defs = svg.querySelector("defs");
  svg.innerHTML = "";
  if (defs) svg.appendChild(defs);

  const g = document.createElementNS(svgNS, "g");

  // gridlines + tick labels
  for (let v = 0; v <= xMax; v += 2) {
    const x = xScale(v);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("class", "gridline");
    line.setAttribute("x1", x); line.setAttribute("x2", x);
    line.setAttribute("y1", pad.top); line.setAttribute("y2", H - pad.bottom);
    g.appendChild(line);
    const lbl = document.createElementNS(svgNS, "text");
    lbl.setAttribute("x", x); lbl.setAttribute("y", H - pad.bottom + 14);
    lbl.setAttribute("text-anchor", "middle");
    lbl.setAttribute("fill", "var(--muted)");
    lbl.setAttribute("font-family", "var(--mono)"); lbl.setAttribute("font-size", "10");
    lbl.textContent = v;
    g.appendChild(lbl);
  }
  for (let v = 0; v <= yMax; v += 10) {
    const y = yScale(v);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("class", "gridline");
    line.setAttribute("x1", pad.left); line.setAttribute("x2", W - pad.right);
    line.setAttribute("y1", y); line.setAttribute("y2", y);
    g.appendChild(line);
    const lbl = document.createElementNS(svgNS, "text");
    lbl.setAttribute("x", pad.left - 8); lbl.setAttribute("y", y + 3);
    lbl.setAttribute("text-anchor", "end");
    lbl.setAttribute("fill", "var(--muted)");
    lbl.setAttribute("font-family", "var(--mono)"); lbl.setAttribute("font-size", "10");
    lbl.textContent = v;
    g.appendChild(lbl);
  }

  // axis titles
  const xt = document.createElementNS(svgNS, "text");
  xt.setAttribute("x", pad.left + innerW / 2); xt.setAttribute("y", H - 10);
  xt.setAttribute("text-anchor", "middle"); xt.setAttribute("class", "axis-title");
  xt.textContent = STATE.trajectory.mode === "season"
    ? "Avg stage pts / race  →"
    : "Last-5 avg stage pts / race  →";
  g.appendChild(xt);
  const yt = document.createElementNS(svgNS, "text");
  yt.setAttribute("x", -(pad.top + innerH / 2));
  yt.setAttribute("y", 16);
  yt.setAttribute("transform", "rotate(-90)");
  yt.setAttribute("text-anchor", "middle"); yt.setAttribute("class", "axis-title");
  yt.textContent = STATE.trajectory.mode === "season"
    ? "↑  Avg finish pts / race"
    : "↑  Last-5 avg finish pts / race";
  g.appendChild(yt);

  // regression line
  const rx1 = 0, rx2 = xMax;
  const ry1 = a + b * rx1, ry2 = a + b * rx2;
  const reg = document.createElementNS(svgNS, "line");
  reg.setAttribute("class", "regline");
  reg.setAttribute("x1", xScale(rx1)); reg.setAttribute("x2", xScale(rx2));
  reg.setAttribute("y1", yScale(Math.max(0, ry1))); reg.setAttribute("y2", yScale(Math.max(0, ry2)));
  g.appendChild(reg);
  const rlbl = document.createElementNS(svgNS, "text");
  rlbl.setAttribute("x", xScale(rx2) + 6); rlbl.setAttribute("y", yScale(Math.max(0, ry2)) + 3);
  rlbl.setAttribute("class", "regline-label");
  rlbl.textContent = "LEAGUE TREND";
  g.appendChild(rlbl);

  // dots / arrows
  shown.forEach(p => {
    const color = p.color;
    const key = entityKey(p.entity);
    if (STATE.trajectory.mode === "trajectory") {
      const x1 = xScale(p.xSeason), y1 = yScale(p.ySeason);
      const x2 = xScale(p.xForm),   y2 = yScale(p.yForm);
      const tail = document.createElementNS(svgNS, "circle");
      tail.setAttribute("cx", x1); tail.setAttribute("cy", y1); tail.setAttribute("r", 3);
      tail.setAttribute("fill", "none"); tail.setAttribute("stroke", color);
      tail.setAttribute("stroke-width", "1.2"); tail.setAttribute("opacity", "0.55");
      g.appendChild(tail);
      const arr = document.createElementNS(svgNS, "line");
      arr.setAttribute("x1", x1); arr.setAttribute("y1", y1);
      arr.setAttribute("x2", x2); arr.setAttribute("y2", y2);
      arr.setAttribute("stroke", color); arr.setAttribute("stroke-width", "1.4");
      arr.setAttribute("marker-end", "url(#traj-arrowhead)");
      arr.setAttribute("style", `color:${color}`);
      arr.setAttribute("opacity", "0.85");
      g.appendChild(arr);
      const head = document.createElementNS(svgNS, "circle");
      head.setAttribute("class", "traj-dot");
      head.setAttribute("cx", x2); head.setAttribute("cy", y2); head.setAttribute("r", 5);
      head.setAttribute("fill", color); head.setAttribute("stroke", "var(--bg)"); head.setAttribute("stroke-width", "1");
      head.appendChild(trajTitle(p));
      g.appendChild(head);
      if (labelKeys.has(key)) {
        const lbl = document.createElementNS(svgNS, "text");
        lbl.setAttribute("x", x2 + 9); lbl.setAttribute("y", y2 + 3);
        lbl.setAttribute("class", "traj-label");
        lbl.textContent = "#" + p.entity.car_number;
        g.appendChild(lbl);
      }
    } else {
      const cx = xScale(p.xSeason), cy = yScale(p.ySeason);
      const dot = document.createElementNS(svgNS, "circle");
      dot.setAttribute("class", "traj-dot");
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
      dot.setAttribute("r", 6);
      dot.setAttribute("fill", color);
      dot.setAttribute("stroke", "var(--bg)");
      dot.setAttribute("stroke-width", "1.2");
      dot.appendChild(trajTitle(p));
      g.appendChild(dot);
      if (labelKeys.has(key)) {
        const lbl = document.createElementNS(svgNS, "text");
        lbl.setAttribute("x", cx + 10); lbl.setAttribute("y", cy + 3);
        lbl.setAttribute("class", "traj-label");
        lbl.textContent = "#" + p.entity.car_number;
        g.appendChild(lbl);
      }
    }
  });

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.appendChild(g);

  // legend
  document.getElementById("trajectory-legend").innerHTML = `
    <span class="legend-item"><span class="legend-dot" style="background:${STATE.trajectory.mode === "trajectory" ? "var(--accent-2)" : "var(--accent)"}"></span>${STATE.entity === "owner" ? "Car" : "Driver"} · ${STATE.trajectory.mode === "trajectory" ? "season → last-5" : "season avg"}</span>
    <span class="legend-item"><span class="legend-line"></span>League trend (expected finish pts given stage pts)</span>
    <span class="legend-item" style="color:var(--pos)">▲ above trend = converting pace to results</span>
    <span class="legend-item" style="color:var(--neg)">▼ below trend = leaving points on the table</span>
  `;

  // callouts (always season-based)
  const sorted = [...withResid].sort((x, y) => y.resid - x.resid);
  const over = sorted.slice(0, 5);
  const under = sorted.slice(-5).reverse();
  fillTrajCallout("trajectory-over", over);
  fillTrajCallout("trajectory-under", under);

  // sub-header
  const sub = document.getElementById("trajectory-sub");
  sub.textContent = STATE.trajectory.mode === "trajectory"
    ? "Pace vs. results — arrows from season avg → last-5 avg (momentum direction)"
    : "Pace vs. results — season average per " + (STATE.entity === "owner" ? "car" : "driver") + " · dashed line = league trend";
}

function regression(pts) {
  const n = pts.length;
  if (n < 2) return { a: 0, b: 0 };
  const sx = pts.reduce((s, p) => s + p.x, 0);
  const sy = pts.reduce((s, p) => s + p.y, 0);
  const sxx = pts.reduce((s, p) => s + p.x * p.x, 0);
  const sxy = pts.reduce((s, p) => s + p.x * p.y, 0);
  const denom = n * sxx - sx * sx;
  if (Math.abs(denom) < 1e-9) return { a: sy / n, b: 0 };
  const b = (n * sxy - sx * sy) / denom;
  const a = (sy - b * sx) / n;
  return { a, b };
}

function trajTitle(p) {
  const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
  const residStr = p.resid >= 0 ? `+${p.resid.toFixed(1)}` : p.resid.toFixed(1);
  t.textContent =
    `${p.entity.driver}  #${p.entity.car_number}\n` +
    `Season  stg ${p.xSeason.toFixed(1)}  fin ${p.ySeason.toFixed(1)}\n` +
    `Last-5  stg ${p.xForm.toFixed(1)}  fin ${p.yForm.toFixed(1)}\n` +
    `vs trend  ${residStr}`;
  return t;
}

function fillTrajCallout(hostId, rows) {
  const host = document.getElementById(hostId);
  host.innerHTML = rows.map(r => {
    const col = colorFor(STATE.series, r.entity.car_number);
    const txt = contrastTextFor(col);
    const v = r.resid.toFixed(1);
    const cls = r.resid >= 0 ? "pos" : "neg";
    const sign = r.resid >= 0 ? "+" : "";
    return `<div class="row">
      <span class="name">
        <span class="car-tag" style="background:${col};color:${txt}">${r.entity.car_number}</span>
        <span>${escapeHTML(r.entity.driver)}</span>
      </span>
      <span class="delta ${cls}">${sign}${v}</span>
    </div>`;
  }).join("");
}

// ============================================================
// VIEW: HEATMAP — brighter greens/reds
// ============================================================
function renderHeatmap() {
  const host = document.getElementById("heatmap-wrap");
  if (!STATE.data) return;
  const races = racesSorted();
  const drivers = computeSeasonTotals();
  if (drivers.length === 0 || races.length === 0) {
    host.innerHTML = `<div class="loading">No data yet.</div>`;
    return;
  }

  const grid = document.createElement("div");
  grid.className = "heatmap-grid";
  grid.style.gridTemplateColumns = `200px repeat(${races.length}, 30px) 44px`;

  const corner = document.createElement("div");
  corner.className = "hm-header hm-header-corner";
  corner.textContent = STATE.entity === "owner" ? "Car" : "Driver";
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

  drivers.forEach(d => {
    const carHex = colorFor(STATE.series, d.car_number);
    const txt = contrastTextFor(carHex);
    const label = document.createElement("div");
    label.className = "hm-label";
    label.innerHTML = `<span class="car-tag" style="background:${carHex};color:${txt}">${d.car_number}</span><span>${escapeHTML(displayName(d))}</span>`;
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
        const bg = heatmapColor(f);
        cell.style.background = bg;
        cell.style.color = heatmapText(f);
      }
      grid.appendChild(cell);
    });
    const total = document.createElement("div");
    total.className = "hm-cell";
    total.textContent = d.total;
    total.style.color = "var(--text)";
    total.style.fontWeight = "700";
    grid.appendChild(total);
  });

  host.innerHTML = "";
  host.appendChild(grid);
}

// Brighter heatmap scale — saturated green for top finishes, saturated red for back.
function heatmapColor(finish) {
  if (finish == null) return "transparent";
  const clamp = (a, lo, hi) => Math.max(lo, Math.min(hi, a));
  const t = clamp(finish, 1, 40);
  if (t <= 20) {
    // 1→1.0, 20→0.0
    const k = 1 - (t - 1) / 19;
    // alpha 0.18 → 0.75 (bigger jump than before)
    const a = 0.18 + 0.57 * k;
    return `rgba(50, 230, 100, ${a.toFixed(3)})`;
  } else {
    // 21→0.0, 40→1.0
    const k = (t - 20) / 20;
    const a = 0.15 + 0.55 * k;
    return `rgba(255, 70, 70, ${a.toFixed(3)})`;
  }
}
function heatmapText(finish) {
  if (finish == null) return "var(--dim)";
  if (finish <= 5) return "#00140a";
  if (finish >= 35) return "#230707";
  if (finish <= 10) return "#cef5d9";
  if (finish >= 25) return "#ffd2d2";
  return "#eef0f5";
}

// ============================================================
// VIEW: STANDINGS — bigger numbers, team pills, weekly Δ arrows, sortable
// ============================================================
function renderStandings() {
  const table = document.getElementById("standings-table");
  if (!STATE.data) return;

  const races = racesSorted();
  const lastRaceRound = races.length ? races[races.length - 1].round : null;
  const nMinus1Cutoff = lastRaceRound; // "current" includes through last race
  const previousCutoff = lastRaceRound ? lastRaceRound - 1 : null;

  // Current totals (through last race)
  const currentMap = pointsMapThroughRound(nMinus1Cutoff);
  const currentRows = rankingRowsFrom(currentMap);

  // Previous-week totals (through last race minus 1) — used for Δ-arrows
  const previousMap = previousCutoff && previousCutoff >= 1
    ? pointsMapThroughRound(previousCutoff)
    : new Map();
  const previousRank = new Map();
  Array.from(previousMap.entries())
    .sort((a, b) => b[1].total - a[1].total)
    .forEach(([k, _v], i) => previousRank.set(k, i + 1));

  // Decorate
  let rows = currentRows.map((r, i) => {
    const currRank = i + 1;
    const prevRank = previousRank.has(r.key) ? previousRank.get(r.key) : null;
    const posChange = prevRank != null ? (prevRank - currRank) : null; // positive = moved up
    return { ...r, currRank, prevRank, posChange };
  });

  // Sort (default by total desc, which is what currentRows already is)
  const sk = STATE.standings.sortKey;
  const sd = STATE.standings.sortDir;
  if (sk && sk !== "total") {
    rows = sortRows(rows, sk, sd);
    // rank column always shows current-points rank, which does NOT move when sorting other cols
  } else if (sk === "total" && sd === "asc") {
    rows = rows.slice().reverse();
  }

  const body = rows.map(r => {
    const carHex = colorFor(STATE.series, r.car_number);
    const txt = contrastTextFor(carHex);
    const teamPill = renderTeamPill(STATE.series, r.car_number, r.team);
    const pc = r.posChange;
    let pcPill;
    if (r.prevRank == null) {
      pcPill = `<span class="pos-change new">NEW</span>`;
    } else if (pc === 0) {
      pcPill = `<span class="pos-change flat">—</span>`;
    } else if (pc > 0) {
      pcPill = `<span class="pos-change up">▲${pc}</span>`;
    } else {
      pcPill = `<span class="pos-change down">▼${Math.abs(pc)}</span>`;
    }
    return `<tr>
      <td class="rank-cell">${r.currRank}${pcPill}</td>
      <td><span class="driver-cell">
        <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
        <span>${escapeHTML(r.displayLabel)}</span>
      </span></td>
      <td>${teamPill}</td>
      <td class="num">${r.starts}</td>
      <td class="num">${r.wins}</td>
      <td class="num">${r.top5}</td>
      <td class="num">${r.top10}</td>
      <td class="num">${r.avgFinish != null ? r.avgFinish.toFixed(1) : "—"}</td>
      <td class="num">${r.sumS1}</td>
      <td class="num">${r.sumS2}</td>
      <td class="num">${r.sumFL}</td>
      <td class="num">${r.sumFin}</td>
      <td class="num total-col">${r.total}</td>
    </tr>`;
  }).join("");

  const th = (key, label, numeric) => {
    const active = STATE.standings.sortKey === key;
    const cls = `sortable ${numeric ? "num" : ""} ${active ? "sort-" + STATE.standings.sortDir : ""}`.trim();
    const arrow = active ? (STATE.standings.sortDir === "asc" ? "▲" : "▼") : "↕";
    return `<th class="${cls}" data-sort="${key}">${label}<span class="sort-arrow">${arrow}</span></th>`;
  };

  table.innerHTML = `
    <thead>
      <tr>
        <th class="num">#</th>
        ${th("driver", "Driver", false)}
        ${th("team", "Team", false)}
        ${th("starts", "Starts", true)}
        ${th("wins", "Wins", true)}
        ${th("top5", "T5", true)}
        ${th("top10", "T10", true)}
        ${th("avgFinish", "Avg Fin", true)}
        ${th("sumS1", "S1", true)}
        ${th("sumS2", "S2", true)}
        ${th("sumFL", "FL", true)}
        ${th("sumFin", "Finish Pts", true)}
        ${th("total", "Total", true)}
      </tr>
    </thead>
    <tbody>${body}</tbody>
  `;

  table.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (STATE.standings.sortKey === key) {
        STATE.standings.sortDir = STATE.standings.sortDir === "asc" ? "desc" : "asc";
      } else {
        STATE.standings.sortKey = key;
        STATE.standings.sortDir = (key === "driver" || key === "team") ? "asc" : "desc";
      }
      renderStandings();
    });
  });
}

// Build a points/summary map through a given round (used for last-week deltas).
function pointsMapThroughRound(maxRound) {
  const map = new Map();
  (STATE.data?.races || []).forEach(r => {
    if (r.round > maxRound) return;
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      const key = (STATE.entity === "owner") ? `#${d.car_number}` : d.driver;
      if (!map.has(key)) {
        map.set(key, {
          key,
          driver: d.driver,
          driversSet: new Set(),
          car_number: d.car_number,
          team: d.team,
          total: 0, starts: 0, wins: 0, top5: 0, top10: 0,
          finishes: [],
          sumS1: 0, sumS2: 0, sumFin: 0, sumFL: 0,
        });
      }
      const e = map.get(key);
      e.driversSet.add(d.driver);
      e.driver = d.driver;           // most-recent
      e.team = d.team;
      e.car_number = d.car_number;
      e.total += d.race_pts || 0;
      e.sumS1 += d.stage_1_pts || 0;
      e.sumS2 += d.stage_2_pts || 0;
      e.sumFin += d.finish_pts || 0;
      e.sumFL += d.fastest_lap_pt || 0;
      e.starts += 1;
      if (d.finish_pos != null) {
        e.finishes.push(d.finish_pos);
        if (d.finish_pos === 1) e.wins += 1;
        if (d.finish_pos <= 5)  e.top5 += 1;
        if (d.finish_pos <= 10) e.top10 += 1;
      }
    });
  });
  return map;
}

function rankingRowsFrom(map) {
  const rows = Array.from(map.values()).map(e => {
    const avgFinish = e.finishes.length
      ? e.finishes.reduce((s, x) => s + x, 0) / e.finishes.length
      : null;
    const driversArr = Array.from(e.driversSet);
    const displayLabel = (STATE.entity === "owner")
      ? (driversArr.length > 1
          ? `#${e.car_number} · ${e.driver} +${driversArr.length - 1}`
          : `#${e.car_number} · ${e.driver}`)
      : e.driver;
    return {
      ...e,
      avgFinish,
      displayLabel,
      // for sorting by driver name, we want the visible label
      driver: displayLabel,
    };
  });
  rows.sort((a, b) => b.total - a.total);
  return rows;
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
