// =========================================================================
// NASCAR Points Analysis — app.js
// Loads data/points_<year>.json + data/colors.json, renders 6 views,
// handles routing, series/season/entity switching, filters, sorts.
// =========================================================================

const STATE = {
  series: "NCS",
  season: 2026,
  view: "form",
  entity: "driver",
  data: null,
  colors: null,
  driverBios: null,
  seasonsAvailable: [],
  form: { window: "5", search: "", ftOnly: true, sortKey: null, sortDir: "desc" },
  arc: { selected: new Set(), ftOnly: true },
  breakdown: { drivers: [], ftOnly: true },  // array of driver keys, max 4
  trajectory: { mode: "season", show: "all", labels: "top12", tracks: "all" },
  teammates: { metric: "fin", ftOnly: true },
  profile: { kind: null, slug: null },
  standings: { sortKey: "total", sortDir: "desc" },
};

const SERIES_TO_KEY = { NCS: "W", NOS: "B", NTS: "C" };
const FALLBACK_COLOR = "#9ca3af";
const VIEWS = ["form", "arc", "breakdown", "trajectory", "teammates", "heatmap", "standings", "profile"];

// ============================================================
// BOOT
// ============================================================
async function boot() {
  wireUIControls();
  await loadColors();
  loadDriverBios();  // async, not awaited — profile will use it whenever it arrives
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
  // Profile routes: #/profile/tyler-reddick or #/car/45
  if (view === "profile" || view === "car") {
    STATE.view = "profile";
    STATE.profile = {
      kind: view,              // "profile" (driver) or "car"
      slug: h[1] || null,
    };
    return;
  }
  STATE.view = VIEWS.includes(view) ? view : "form";
}

// Slug helper: "A.J. Allmendinger" → "a-j-allmendinger"
function slugify(name) {
  if (!name) return "";
  return String(name)
    .toLowerCase()
    .replace(/[.']/g, "")            // drop periods/apostrophes
    .replace(/[^a-z0-9]+/g, "-")     // non-alphanumeric → dash
    .replace(/^-+|-+$/g, "")         // trim leading/trailing dashes
    || "driver";
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

// Load optional driver biographies (DOB, hometown, career totals by series).
// Silently no-ops if data/drivers.json doesn't exist — profile view renders
// bio-less in that case.
async function loadDriverBios() {
  try {
    const r = await fetch("data/drivers.json");
    if (!r.ok) { STATE.driverBios = null; return; }
    const payload = await r.json();
    STATE.driverBios = payload.drivers || {};
  } catch (e) {
    // Missing file is the common case early on — not an error
    STATE.driverBios = null;
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
  document.querySelectorAll("#series-sw button").forEach(b => {
    b.addEventListener("click", async () => {
      document.querySelectorAll("#series-sw button")
        .forEach(x => x.classList.toggle("on", x === b));
      STATE.series = b.dataset.series;
      STATE.arc.selected.clear();
      STATE.breakdown.drivers = [];
      await loadCurrentData();
      render();
    });
  });

  document.querySelectorAll("#entity-sw button").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#entity-sw button")
        .forEach(x => x.classList.toggle("on", x === b));
      STATE.entity = b.dataset.entity;
      STATE.arc.selected.clear();
      STATE.breakdown.drivers = [];
      render();
    });
  });

  // Form view toggles
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

  // Arc toggles (full-time filter)
  document.querySelectorAll("#view-arc .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "arc-ft") STATE.arc.ftOnly = (b.dataset.val === "ft");
        renderArc();
      });
    });
  });

  // Breakdown toggle (full-time filter)
  document.querySelectorAll("#view-breakdown .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "breakdown-ft") STATE.breakdown.ftOnly = (b.dataset.val === "ft");
        renderBreakdown();
      });
    });
  });

  // Trajectory toggles
  document.querySelectorAll("#view-trajectory .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "traj-mode") STATE.trajectory.mode = b.dataset.val;
        if (group === "traj-show") STATE.trajectory.show = b.dataset.val;
        if (group === "traj-labels") STATE.trajectory.labels = b.dataset.val;
        if (group === "traj-tracks") STATE.trajectory.tracks = b.dataset.val;
        renderTrajectory();
      });
    });
  });

  // Teammate view toggles
  document.querySelectorAll("#view-teammates .toggle-group").forEach(g => {
    const group = g.dataset.group;
    g.querySelectorAll("button").forEach(b => {
      b.addEventListener("click", () => {
        g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
        if (group === "teammates-metric") STATE.teammates.metric = b.dataset.val;
        if (group === "teammates-ft")     STATE.teammates.ftOnly = (b.dataset.val === "ft");
        renderTeammates();
      });
    });
  });

  document.querySelectorAll(".navlink").forEach(a => {
    a.addEventListener("click", () => {
      document.getElementById("sidebar")?.classList.remove("open");
    });
  });
  document.getElementById("nav-toggle")?.addEventListener("click", () => {
    document.getElementById("sidebar")?.classList.toggle("open");
  });

  document.getElementById("arc-clear")?.addEventListener("click", () => {
    STATE.arc.selected.clear();
    STATE.arc.userCleared = true;
    renderArc();
  });
  document.getElementById("arc-top10")?.addEventListener("click", () => {
    STATE.arc.selected.clear();
    STATE.arc.userCleared = false;
    const totals = computeSeasonTotals();
    totals.slice(0, 10).forEach(t => STATE.arc.selected.add(entityKey(t)));
    renderArc();
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
    case "teammates":  renderTeammates(); break;
    case "profile":    renderProfile(); break;
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

function allEntities() {
  const map = new Map();
  racesSorted().forEach(r => {
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
          manufacturer: d.manufacturer,
          races: [],
        });
      }
      const e = map.get(key);
      e.driversSet.add(d.driver);
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
        track_code: r.track_code,
        track: r.track,
      });
    });
  });
  return Array.from(map.values()).map(e => {
    const counts = {};
    e.races.forEach(r => { counts[r.driver] = (counts[r.driver] || 0) + 1; });
    const drivers = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    return { ...e, drivers };
  });
}

function allDrivers() { return allEntities(); }

function displayName(entity) {
  if (STATE.entity === "owner") {
    if (entity.drivers && entity.drivers.length > 1) {
      return `#${entity.car_number} · ${entity.drivers[0]} +${entity.drivers.length - 1}`;
    }
    return `#${entity.car_number} · ${entity.driver}`;
  }
  return entity.driver;
}

function entityKey(entity) {
  return (STATE.entity === "owner") ? `#${entity.car_number}` : entity.driver;
}

// Returns the hash URL for this entity's profile page.
// In driver mode: #/profile/<driver-slug>. In owner mode: #/car/<car-number>.
function profileHref(entity) {
  if (STATE.entity === "owner") return `#/car/${entity.car_number}`;
  return `#/profile/${slugify(entity.driver)}`;
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

function formRatingFor(driverRaces, windowType) {
  let slice;
  if (windowType === "5") slice = driverRaces.slice(-5);
  else if (windowType === "10") slice = driverRaces.slice(-10);
  else slice = driverRaces;
  const finishes = slice.map(r => r.finish).filter(x => x != null);
  if (finishes.length === 0) return null;
  const avg = finishes.reduce((s, x) => s + x, 0) / finishes.length;
  return Math.max(0, Math.min(100, 100 - (avg - 1) * 2));
}

function seasonTotalRating(driverRaces) {
  return formRatingFor(driverRaces, "season");
}

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
  return null;
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
  if (!bar || !STATE.data) { if (bar) bar.innerHTML = ""; return; }
  const races = racesSorted();
  const totals = computeSeasonTotals();
  const lastRace = races[races.length - 1];
  const leader = totals[0];

  const deltas = allEntities().filter(isFullTime).map(d => {
    const f = formRatingFor(d.races, "5");
    const s = formRatingFor(d.races, "season");
    return { entity: d, delta: (f != null && s != null) ? f - s : null };
  }).filter(d => d.delta != null);
  const hottest = deltas.slice().sort((a,b) => b.delta - a.delta)[0];
  const coldest = deltas.slice().sort((a,b) => a.delta - b.delta)[0];

  const hotColdTip = "Rating delta: last-5-race form rating minus full-season rating. +17.4 means this driver's recent finishes are about 8\u20139 positions better than their season average. \u221213.0 means the opposite \u2014 about 6\u20137 positions worse recently.";
  const leaderTip = "Points leader through the last completed race.";
  const raceTip = "Most recent race in the dataset.";

  bar.innerHTML = `
    <div class="metric" data-tip="${escapeHTML(leaderTip)}"><span class="k">Leader</span>
      <span class="v">${leader ? `${escapeHTML(displayName(leader))} \u00b7 ${leader.total}` : "\u2014"}</span></div>
    <div class="metric" data-tip="${escapeHTML(hotColdTip)}"><span class="k">Hottest</span>
      <span class="v hot">${hottest ? `${escapeHTML(displayName(hottest.entity))} ${signed(hottest.delta.toFixed(1))}` : "\u2014"}</span></div>
    <div class="metric" data-tip="${escapeHTML(hotColdTip)}"><span class="k">Coldest</span>
      <span class="v cold">${coldest ? `${escapeHTML(displayName(coldest.entity))} ${signed(coldest.delta.toFixed(1))}` : "\u2014"}</span></div>
    <div class="metric" data-tip="${escapeHTML(raceTip)}"><span class="k">Last Race</span>
      <span class="v">${lastRace ? `R${lastRace.round} \u00b7 ${escapeHTML(prettyTrack(lastRace.track_code, lastRace.track))}` : "\u2014"}</span></div>
  `;

  // Wire hover handlers for the floating metric tooltip
  const tip = document.getElementById("metric-tooltip");
  if (tip) {
    bar.querySelectorAll(".metric[data-tip]").forEach(el => {
      el.addEventListener("mouseenter", () => {
        tip.textContent = el.getAttribute("data-tip") || "";
        tip.classList.add("show");
        // position below the metric element using viewport coords (fixed positioning)
        const rect = el.getBoundingClientRect();
        // measure tooltip after content is set
        const tipW = tip.offsetWidth || 280;
        const tipH = tip.offsetHeight || 60;
        let left = rect.left;
        // don't let it run off the right edge
        const vw = window.innerWidth;
        if (left + tipW > vw - 8) left = vw - tipW - 8;
        if (left < 8) left = 8;
        let top = rect.bottom + 8;
        // if no room below, flip above
        if (top + tipH > window.innerHeight - 8) top = rect.top - tipH - 8;
        tip.style.left = `${left}px`;
        tip.style.top  = `${top}px`;
      });
      el.addEventListener("mouseleave", () => {
        tip.classList.remove("show");
      });
    });
  }
}

function signed(n) {
  const v = parseFloat(n);
  return v > 0 ? `+${n}` : `${n}`;
}

// ============================================================
// SORT HELPER
// ============================================================
function sortRows(rows, key, dir) {
  const mul = dir === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const va = a[key], vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * mul;
    return String(va).localeCompare(String(vb)) * mul;
  });
}

// ============================================================
// FORM TABLE
// ============================================================
function renderFormTable() {
  const card = document.getElementById("form-card");
  if (!STATE.data) return;

  const entities = allEntities();
  const races = racesSorted();
  // Race columns + sparkline length follow the active window
  let windowSize;
  if (STATE.form.window === "5") windowSize = 5;
  else if (STATE.form.window === "10") windowSize = 10;
  else windowSize = races.length;        // full season
  const shownRaces = races.slice(-Math.min(windowSize, races.length));

  let decorated = entities.map(d => {
    const formRating = formRatingFor(d.races, STATE.form.window);
    const seasonRating = seasonTotalRating(d.races);
    const deltaR = (formRating != null && seasonRating != null) ? formRating - seasonRating : null;
    const lastFinishes = d.races.slice(-shownRaces.length).map(r => r.finish);
    const totalPts = d.races.reduce((s, r) => s + r.total, 0);
    return { ...d, formRating, seasonRating, deltaR, lastFinishes, totalPts, fullTime: isFullTime(d) };
  });

  if (STATE.form.ftOnly) decorated = decorated.filter(d => d.fullTime);

  const q = STATE.form.search.trim().toLowerCase();
  if (q) {
    decorated = decorated.filter(d =>
      d.driver.toLowerCase().includes(q) ||
      (d.car_number || "").toLowerCase().includes(q) ||
      (d.drivers || []).some(n => n.toLowerCase().includes(q))
    );
  }

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
    return `<tr>
      <td class="num" style="color: var(--dim)">${i + 1}</td>
      <td><a class="driver-cell profile-link" href="${profileHref(d)}">
        <span class="car-tag" style="background:${carHex};color:${txtCol}">${d.car_number}</span>
        <span>${escapeHTML(displayName(d))}</span>
      </a></td>
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

  const formColLabel = STATE.form.window === "season"
    ? `Form (Season)`
    : `Form (L${STATE.form.window})`;

  card.innerHTML = `
    <div class="table-scroll">
    <table class="data-table">
      <thead>
        <tr>
          <th class="num">#</th>
          ${th("driver", "Driver", false)}
          ${th("team", "Team", false)}
          ${headerCols}
          <th>${formColLabel}</th>
          ${th("formRating", "Rating", true)}
          ${th("deltaR", "vs Season", true)}
          ${th("totalPts", "Pts", true)}
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="99" class="muted" style="padding:40px;text-align:center">No drivers match.</td></tr>`}</tbody>
    </table>
    </div>
  `;

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

// ============================================================
// TEAM CODE / PILL
// ============================================================
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
    if (/rfk|roush/i.test(name)) return "RFK";
    if (/front row/i.test(name)) return "FRM";
    if (/trackhouse/i.test(name)) return "THR";
    if (/legacy/i.test(name)) return "LMC";
    if (/kaulig/i.test(name)) return "KR";
    if (/spire/i.test(name)) return "SPI";
    if (/jr motorsports/i.test(name)) return "JRM";
    if (/haas/i.test(name)) return "GH";
    if (/wood brothers/i.test(name)) return "WBR";
    if (/rick ware/i.test(name)) return "RWR";
    if (/hyak/i.test(name)) return "HYAK";
    return name.split(/\s+/).map(w => w[0]).join("").slice(0, 4).toUpperCase();
  }
  return team.split(/\s+/).map(w => w[0]).join("").slice(0, 4).toUpperCase();
}

// Readable team pill — colored background if palette has org, else a
// subdued fallback pill that's still legible on dark.
function renderTeamPill(series, carNumber, teamString) {
  const palTeam = teamCodeFromPalette(series, carNumber);
  const orgHex = orgColorFor(series, carNumber);
  const code = palTeam || teamCodeFromName(teamString) || "";
  if (!code) return `<span class="team-pill fallback">—</span>`;
  if (orgHex) {
    const textCol = contrastTextFor(orgHex);
    return `<span class="team-pill" style="background:${orgHex};color:${textCol}">${escapeHTML(code)}</span>`;
  }
  return `<span class="team-pill fallback">${escapeHTML(code)}</span>`;
}

// ============================================================
// DRIVER GRID (Arc + Breakdown picker)
// ============================================================
// mode: "multi" (arc) | "single" (breakdown)
// filter: ftOnly flag
// onSelect: (entity) => void
// isSelected: (entity) => boolean
function renderDriverGrid(hostId, mode, ftOnly, onSelect, isSelected) {
  const host = document.getElementById(hostId);
  if (!host) return;
  let entities = allEntities();
  if (ftOnly) entities = entities.filter(isFullTime);
  // sort by current season points desc so the big names float to top
  entities = entities.map(e => ({
    ...e, total: e.races.reduce((s, r) => s + r.total, 0),
  })).sort((a, b) => b.total - a.total);

  host.innerHTML = entities.map(e => {
    const carHex = colorFor(STATE.series, e.car_number);
    const txt = contrastTextFor(carHex);
    const sel = isSelected(e) ? "selected" : "";
    // keep pill narrow: car# + last name (driver mode) / car# + primary last name (owner mode)
    const lastName = e.driver.split(/\s+/).slice(-1)[0];
    const label = (STATE.entity === "owner" && (e.drivers || []).length > 1)
      ? `${lastName} +${(e.drivers || []).length - 1}`
      : lastName;
    return `<div class="driver-pill ${sel}" data-key="${escapeHTML(entityKey(e))}" title="${escapeHTML(displayName(e))} — click to toggle, ↗ to open profile">
      <span class="dp-num" style="background:${carHex};color:${txt}">${e.car_number}</span>
      <span class="dp-name">${escapeHTML(label)}</span>
      <a class="dp-jump profile-link" href="${profileHref(e)}" title="Open ${escapeHTML(displayName(e))} profile" aria-label="Open profile">↗</a>
    </div>`;
  }).join("");

  host.querySelectorAll(".driver-pill").forEach(el => {
    el.addEventListener("click", (ev) => {
      // Don't toggle selection if the jump arrow was clicked
      if (ev.target.closest(".dp-jump")) return;
      const key = el.dataset.key;
      const e = entities.find(x => entityKey(x) === key);
      if (!e) return;
      onSelect(e);
    });
  });
}

// ============================================================
// SEASON CUMULATIVE (was Season Arc)
// ============================================================
function renderArc() {
  const svg = document.getElementById("arc-svg");
  if (!STATE.data) return;

  const races = racesSorted();
  if (races.length === 0) {
    svg.innerHTML = `<text x="20" y="40" fill="var(--muted)">No races loaded.</text>`;
    renderArcGrid();
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

  if (STATE.arc.selected.size === 0 && !STATE.arc.userCleared) {
    const totals = computeSeasonTotals();
    totals.slice(0, 5).forEach(t => STATE.arc.selected.add(entityKey(t)));
  }

  const W = 980, H = 420, pad = { top: 16, right: 150, bottom: 26, left: 48 };
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

  renderArcGrid();
}

function renderArcGrid() {
  renderDriverGrid(
    "arc-driver-grid",
    "multi",
    STATE.arc.ftOnly,
    (e) => {
      const k = entityKey(e);
      if (STATE.arc.selected.has(k)) STATE.arc.selected.delete(k);
      else STATE.arc.selected.add(k);
      renderArc();
    },
    (e) => STATE.arc.selected.has(entityKey(e))
  );
}

// ============================================================
// BREAKDOWN — multi-select up to 4 drivers, car-color-tinted bars
// ============================================================
function renderBreakdown() {
  const svg = document.getElementById("breakdown-svg");
  const tip = document.getElementById("breakdown-tooltip");
  if (!STATE.data) return;

  const entities = allEntities();
  // Default: if nothing selected, pick current leader
  if (STATE.breakdown.drivers.length === 0 && entities.length) {
    const totals = computeSeasonTotals();
    if (totals.length) STATE.breakdown.drivers = [totals[0].driver];
  }
  // Resolve selected entities (keep selections even if hidden by ft filter)
  const selected = STATE.breakdown.drivers
    .map(key => entities.find(x => x.driver === key))
    .filter(Boolean);

  renderBreakdownGrid();

  if (selected.length === 0) {
    svg.innerHTML = `<text x="20" y="40" fill="var(--muted)" font-family="var(--mono)" font-size="11">Select a driver below to see their per-race breakdown.</text>`;
    svg.setAttribute("viewBox", "0 0 920 200");
    document.getElementById("breakdown-legend").innerHTML = "";
    return;
  }

  const races = racesSorted();
  const rounds = races.map(r => r.round);
  const raceByRound = {};
  races.forEach(r => { raceByRound[r.round] = r; });

  // Per-driver race-indexed data
  const driverData = selected.map(d => {
    const byRound = {};
    d.races.forEach(r => { byRound[r.round] = r; });
    return {
      entity: d,
      color: colorFor(STATE.series, d.car_number),
      byRound,
      rows: rounds.map(rd => {
        const r = byRound[rd] || { s1: 0, s2: 0, fin: 0, fl: 0 };
        return {
          round: rd,
          s1: r.s1 || 0, s2: r.s2 || 0, fin: r.fin || 0, fl: r.fl || 0,
          finish_pos: r.finish, start_pos: r.start,
        };
      }),
    };
  });

  // Chart geometry
  const W = 920;
  const H = driverData.length > 1 ? 380 : 340;
  const pad = { top: 20, right: 16, bottom: 34, left: 44 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  // Max total across ALL selected drivers (shared y-scale so comparison is honest)
  let maxTot = 1;
  driverData.forEach(dd => {
    dd.rows.forEach(r => {
      const t = r.s1 + r.s2 + r.fin + r.fl;
      if (t > maxTot) maxTot = t;
    });
  });

  const nRaces = rounds.length;
  const groupWidth = innerW / nRaces;
  const nDrivers = driverData.length;
  // Leave ~25% of group as gaps between groups when multi-driver
  const groupInnerPad = nDrivers > 1 ? 0.18 : 0.25;  // fraction of group
  const availPerGroup = groupWidth * (1 - groupInnerPad);
  const barW = availPerGroup / nDrivers;
  const xStep = groupWidth;
  const yScale = v => pad.top + (1 - v / maxTot) * innerH;

  // Semantic colors (used in SINGLE-driver mode)
  const COL_S1 = "#60a5fa";
  const COL_S2 = "#3b82f6";
  const COL_FN = "#7280a0";
  const COL_FL = "#fbbf24";

  // Helper: given a car hex and a segment type, produce a tinted shade.
  // This is used in MULTI-driver mode so all 4 segments of a driver share a hue.
  function tintedShade(hexOrHsl, segment) {
    // Parse hex to rgb, then lighten / darken / tint
    const rgb = hexToRgb(hexOrHsl) || { r: 110, g: 110, b: 180 };
    const mix = (r, g, b, t) => ({
      r: Math.round(rgb.r + (r - rgb.r) * t),
      g: Math.round(rgb.g + (g - rgb.g) * t),
      b: Math.round(rgb.b + (b - rgb.b) * t),
    });
    let c;
    if (segment === "fin")      c = rgb;                           // base car color
    else if (segment === "s1")  c = mix(255, 255, 255, 0.40);      // lighter
    else if (segment === "s2")  c = mix(255, 255, 255, 0.20);      // slightly lighter
    else if (segment === "fl")  c = mix(255, 215, 0, 0.55);        // golden tint
    else c = rgb;
    return `rgb(${c.r}, ${c.g}, ${c.b})`;
  }
  function hexToRgb(hex) {
    if (!hex) return null;
    // Accept #abc, #abcdef, or rgb()/hsl() — for hsl we give up and return null (fallback happens above).
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.replace("#",""));
    if (!m) return null;
    let s = m[1];
    if (s.length === 3) s = s.split("").map(ch => ch + ch).join("");
    return { r: parseInt(s.slice(0,2), 16), g: parseInt(s.slice(2,4), 16), b: parseInt(s.slice(4,6), 16) };
  }

  // Build SVG
  const svgNS = "http://www.w3.org/2000/svg";
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.innerHTML = "";

  // gridlines
  for (let i = 0; i <= 5; i++) {
    const y = pad.top + (i / 5) * innerH;
    const v = Math.round(maxTot * (1 - i / 5));
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("class", "gridline");
    line.setAttribute("x1", pad.left); line.setAttribute("x2", W - pad.right);
    line.setAttribute("y1", y); line.setAttribute("y2", y);
    svg.appendChild(line);
    const lbl = document.createElementNS(svgNS, "text");
    lbl.setAttribute("x", pad.left - 6); lbl.setAttribute("y", y + 3);
    lbl.setAttribute("text-anchor", "end");
    lbl.setAttribute("fill", "var(--muted)");
    lbl.setAttribute("font-family", "var(--mono)"); lbl.setAttribute("font-size", "10");
    lbl.textContent = v;
    svg.appendChild(lbl);
  }

  // Tooltip showing breakdown for all selected drivers in this race
  const hideTip = () => { if (tip) tip.hidden = true; };
  const showTip = (rd, groupCx, groupTopY) => {
    if (!tip) return;
    const meta = raceByRound[rd];
    const title = `R${rd} · ${escapeHTML(prettyTrack(meta?.track_code, meta?.track))}`;
    const isMulti = driverData.length > 1;
    let body = "";
    driverData.forEach(dd => {
      const r = dd.byRound[rd];
      const hasData = !!r;
      const s1 = r?.s1 || 0, s2 = r?.s2 || 0, fin = r?.fin || 0, fl = r?.fl || 0;
      const total = s1 + s2 + fin + fl;
      const carHex = dd.color;
      const blockParts = [];
      if (isMulti) {
        blockParts.push(`<div class="tt-driver-name"><span class="dot" style="background:${carHex}"></span>#${dd.entity.car_number} ${escapeHTML(dd.entity.driver)}${r?.finish ? ` · P${r.finish}` : ""}</div>`);
      }
      if (!hasData) {
        blockParts.push(`<div class="tt-row"><span class="lbl">did not start</span><span class="val">—</span></div>`);
      } else {
        if (fin) blockParts.push(`<div class="tt-row"><span class="lbl"><span class="sw" style="background:${isMulti ? tintedShade(carHex, "fin") : COL_FN}"></span>Finish</span><span class="val">${fin}</span></div>`);
        if (s1)  blockParts.push(`<div class="tt-row"><span class="lbl"><span class="sw" style="background:${isMulti ? tintedShade(carHex, "s1") : COL_S1}"></span>Stage 1</span><span class="val">${s1}</span></div>`);
        if (s2)  blockParts.push(`<div class="tt-row"><span class="lbl"><span class="sw" style="background:${isMulti ? tintedShade(carHex, "s2") : COL_S2}"></span>Stage 2</span><span class="val">${s2}</span></div>`);
        if (fl)  blockParts.push(`<div class="tt-row"><span class="lbl"><span class="sw" style="background:${isMulti ? tintedShade(carHex, "fl") : COL_FL}"></span>Fastest Lap</span><span class="val">${fl}</span></div>`);
        if (!fin && !s1 && !s2 && !fl) blockParts.push(`<div class="tt-row"><span class="lbl">No points</span><span class="val">0</span></div>`);
        blockParts.push(`<div class="tt-row total"><span class="lbl">Total</span><span class="val">${total}</span></div>`);
      }
      body += `<div class="tt-driver-block">${blockParts.join("")}</div>`;
    });

    tip.classList.toggle("multi", isMulti);
    tip.innerHTML = `<div class="tt-hdr">${escapeHTML(title)}</div>${body}`;
    tip.hidden = false;

    const svgRect = svg.getBoundingClientRect();
    const card = svg.parentElement;
    const cardRect = card.getBoundingClientRect();
    const scale = svgRect.width / W;
    const pxX = (svgRect.left - cardRect.left) + groupCx * scale;
    const pxY = (svgRect.top  - cardRect.top)  + groupTopY * scale;
    const tipRect = tip.getBoundingClientRect();
    let left = pxX - tipRect.width / 2;
    let top = pxY - tipRect.height - 10;
    left = Math.max(6, Math.min(left, card.clientWidth - tipRect.width - 6));
    if (top < 6) top = pxY + 14;
    tip.style.left = `${left}px`;
    tip.style.top  = `${top}px`;
  };

  // Render each race group
  rounds.forEach((rd, i) => {
    const groupCx = pad.left + i * xStep + xStep / 2;
    const groupLeft = pad.left + i * xStep + (xStep - availPerGroup) / 2;
    const isMulti = driverData.length > 1;

    // Hit-rect spans the whole race column for hovering
    let topBound = pad.top + innerH;
    driverData.forEach(dd => {
      const r = dd.byRound[rd];
      if (!r) return;
      const total = r.s1 + r.s2 + r.fin + r.fl;
      const y = yScale(total);
      if (y < topBound) topBound = y;
    });
    const hit = document.createElementNS(svgNS, "rect");
    hit.setAttribute("x", pad.left + i * xStep);
    hit.setAttribute("y", pad.top);
    hit.setAttribute("width", xStep);
    hit.setAttribute("height", innerH);
    hit.setAttribute("fill", "transparent");
    hit.style.cursor = "pointer";
    hit.addEventListener("mouseenter", () => showTip(rd, groupCx, topBound));
    hit.addEventListener("mousemove",  () => showTip(rd, groupCx, topBound));
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("click",      () => showTip(rd, groupCx, topBound));
    svg.appendChild(hit);

    // Per-driver stacked bars inside the group
    driverData.forEach((dd, dIdx) => {
      const r = dd.byRound[rd];
      if (!r) return;
      const xBar = groupLeft + dIdx * barW;
      let y0 = pad.top + innerH;
      const segs = isMulti
        ? [
            { v: r.fin, c: tintedShade(dd.color, "fin") },
            { v: r.s1,  c: tintedShade(dd.color, "s1")  },
            { v: r.s2,  c: tintedShade(dd.color, "s2")  },
            { v: r.fl,  c: tintedShade(dd.color, "fl")  },
          ]
        : [
            { v: r.fin, c: COL_FN },
            { v: r.s1,  c: COL_S1 },
            { v: r.s2,  c: COL_S2 },
            { v: r.fl,  c: COL_FL },
          ];
      segs.filter(s => s.v > 0).forEach(s => {
        const h = (s.v / maxTot) * innerH;
        const y = y0 - h;
        y0 = y;
        const rect = document.createElementNS(svgNS, "rect");
        rect.setAttribute("x", xBar);
        rect.setAttribute("y", y);
        rect.setAttribute("width", Math.max(1, barW - (isMulti ? 1 : 0)));
        rect.setAttribute("height", h);
        rect.setAttribute("fill", s.c);
        rect.style.pointerEvents = "none";
        svg.appendChild(rect);
      });
    });

    // Round label
    const lbl = document.createElementNS(svgNS, "text");
    lbl.setAttribute("x", groupCx); lbl.setAttribute("y", H - 14);
    lbl.setAttribute("text-anchor", "middle");
    lbl.setAttribute("fill", "var(--muted)");
    lbl.setAttribute("font-family", "var(--mono)"); lbl.setAttribute("font-size", "10");
    lbl.textContent = `R${rd}`;
    svg.appendChild(lbl);
  });

  svg.addEventListener("mouseleave", hideTip);

  // Legend
  const isMulti = driverData.length > 1;
  if (isMulti) {
    // In multi-driver mode: one legend entry per driver (color) + a note about the tint gradient
    const driverItems = driverData.map(dd =>
      `<span class="legend-item"><span class="legend-dot" style="background:${dd.color}"></span>#${dd.entity.car_number} ${escapeHTML(dd.entity.driver.split(/\s+/).slice(-1)[0])}</span>`
    ).join("");
    document.getElementById("breakdown-legend").innerHTML = `
      ${driverItems}
      <span class="legend-item muted" style="margin-left:12px">darker = Finish · lighter = Stages · gold tint = FL</span>
    `;
  } else {
    document.getElementById("breakdown-legend").innerHTML = `
      <span class="legend-item"><span class="legend-swatch" style="background:${COL_FN}"></span>Finish points</span>
      <span class="legend-item"><span class="legend-swatch" style="background:${COL_S1}"></span>Stage 1</span>
      <span class="legend-item"><span class="legend-swatch" style="background:${COL_S2}"></span>Stage 2</span>
      <span class="legend-item"><span class="legend-swatch" style="background:${COL_FL}"></span>Fastest lap</span>
    `;
  }
}

function renderBreakdownGrid() {
  renderDriverGrid(
    "breakdown-driver-grid",
    "multi",
    STATE.breakdown.ftOnly,
    (e) => {
      const key = e.driver;
      const idx = STATE.breakdown.drivers.indexOf(key);
      if (idx >= 0) {
        // Deselect — but prevent going below 1 selected driver
        if (STATE.breakdown.drivers.length > 1) {
          STATE.breakdown.drivers.splice(idx, 1);
        }
      } else {
        if (STATE.breakdown.drivers.length >= 4) {
          // At max — replace the first-selected driver with the new one
          STATE.breakdown.drivers.shift();
        }
        STATE.breakdown.drivers.push(key);
      }
      renderBreakdown();
    },
    (e) => STATE.breakdown.drivers.includes(e.driver)
  );
}

// ============================================================
// TRAJECTORY
// ============================================================
function renderTrajectory() {
  const svg = document.getElementById("trajectory-svg");
  if (!STATE.data) return;

  const trackFilter = STATE.trajectory.tracks;
  const includeRace = (race) => {
    if (trackFilter === "all") return true;
    return trackType(race.track_code) === trackFilter;
  };

  // Filter each driver's races by track type + require >= 1 race after filtering
  // to avoid divide-by-zero on the average calculations.
  const eligible = allEntities()
    .filter(isFullTime)
    .map(d => ({ ...d, races: d.races.filter(includeRace) }))
    .filter(d => d.races.length >= 1);

  // Update the sub-title to reflect the current filter
  const subEl = document.getElementById("trajectory-sub");
  if (subEl) {
    const filterLabel = (trackFilter === "all") ? "" : ` · ${TRACK_TYPE_LABELS[trackFilter] || trackFilter} only`;
    subEl.textContent = `Stage points vs. finish points${filterLabel}`;
  }

  if (eligible.length === 0) {
    svg.innerHTML = `<text x="20" y="40" fill="var(--muted)">No races match this filter yet.</text>`;
    document.getElementById("trajectory-legend").innerHTML = "";
    document.getElementById("trajectory-over").innerHTML = "";
    document.getElementById("trajectory-under").innerHTML = "";
    return;
  }

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
      xSeason: stageSeason, ySeason: finSeason,
      xForm: stageL5, yForm: finL5,
      totalSeason,
      label: displayName(d),
      color: colorFor(STATE.series, d.car_number),
    };
  });

  const regPts = pts.map(p => ({ x: p.xSeason, y: p.ySeason }));
  const { a, b } = regression(regPts);

  const withResid = pts.map(p => ({ ...p, expected: a + b * p.xSeason, resid: p.ySeason - (a + b * p.xSeason) }));

  let shown = withResid;
  if (STATE.trajectory.show === "outperform") shown = withResid.filter(p => p.resid > 0);
  if (STATE.trajectory.show === "underperform") shown = withResid.filter(p => p.resid < 0);

  const labelKeys = new Set();
  if (STATE.trajectory.labels === "all") {
    shown.forEach(p => labelKeys.add(entityKey(p.entity)));
  } else if (STATE.trajectory.labels === "top12") {
    const top12 = [...withResid].sort((x, y) => y.totalSeason - x.totalSeason).slice(0, 12);
    top12.forEach(p => labelKeys.add(entityKey(p.entity)));
  }

  const W = 980, H = 540;
  const pad = { top: 26, right: 110, bottom: 48, left: 62 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  const xMax = Math.ceil(Math.max(8, ...pts.map(p => Math.max(p.xSeason, p.xForm))) / 2) * 2;
  const yMax = Math.ceil(Math.max(30, ...pts.map(p => Math.max(p.ySeason, p.yForm))) / 5) * 5;
  const xScale = v => pad.left + (v / xMax) * innerW;
  const yScale = v => pad.top + (1 - v / yMax) * innerH;

  const svgNS = "http://www.w3.org/2000/svg";
  const defs = svg.querySelector("defs");
  svg.innerHTML = "";
  if (defs) svg.appendChild(defs);
  const g = document.createElementNS(svgNS, "g");

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

  // Season points rank (for tooltip "P3 / 47")
  const totals = computeSeasonTotals();
  const rankByKey = new Map();
  const totalN = totals.length;
  totals.forEach((e, i) => rankByKey.set(entityKey(e), i + 1));

  // Real hover tooltip (replaces the native SVG <title>)
  const tip = document.getElementById("trajectory-tooltip");
  const showTrajTip = (p, evt) => {
    if (!tip) return;
    const rank = rankByKey.get(entityKey(p.entity)) || "—";
    const residStr = p.resid >= 0 ? `+${p.resid.toFixed(1)}` : p.resid.toFixed(1);
    const residCls = p.resid >= 0 ? "pos" : "neg";
    const carHex = colorFor(STATE.series, p.entity.car_number);
    tip.classList.remove("multi");
    tip.innerHTML = `
      <div class="tt-hdr" style="color:${carHex}">${escapeHTML(p.entity.driver)} · #${p.entity.car_number}</div>
      <div class="tt-row"><span class="lbl">Avg stage pts</span><span class="val">${p.xSeason.toFixed(1)}</span></div>
      <div class="tt-row"><span class="lbl">Avg finish pts</span><span class="val">${p.ySeason.toFixed(1)}</span></div>
      <div class="tt-row"><span class="lbl">Last-5 stage</span><span class="val">${p.xForm.toFixed(1)}</span></div>
      <div class="tt-row"><span class="lbl">Last-5 finish</span><span class="val">${p.yForm.toFixed(1)}</span></div>
      <div class="tt-row"><span class="lbl">vs trend</span><span class="val" style="color:var(--${residCls === "pos" ? "pos" : "neg"})">${residStr}</span></div>
      <div class="tt-row total"><span class="lbl">Season pts rank</span><span class="val">P${rank} / ${totalN}</span></div>
    `;
    tip.hidden = false;
    // Position relative to the card-chart parent of the svg
    const card = svg.parentElement;
    const cardRect = card.getBoundingClientRect();
    // Place near the cursor
    let left = (evt.clientX - cardRect.left) + 14;
    let top = (evt.clientY - cardRect.top) - 10;
    const tipRect = tip.getBoundingClientRect();
    left = Math.max(6, Math.min(left, card.clientWidth - tipRect.width - 6));
    if (top + tipRect.height > card.clientHeight) top = card.clientHeight - tipRect.height - 6;
    if (top < 6) top = 6;
    tip.style.left = `${left}px`;
    tip.style.top  = `${top}px`;
  };
  const hideTrajTip = () => { if (tip) tip.hidden = true; };
  const wireDot = (el, p) => {
    el.addEventListener("mouseenter", (e) => showTrajTip(p, e));
    el.addEventListener("mousemove",  (e) => showTrajTip(p, e));
    el.addEventListener("mouseleave", hideTrajTip);
    el.addEventListener("click",      (e) => showTrajTip(p, e));
  };

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
      wireDot(head, p);
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
      wireDot(dot, p);
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

  // Hide tooltip when leaving the chart area
  svg.addEventListener("mouseleave", hideTrajTip);

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.appendChild(g);

  document.getElementById("trajectory-legend").innerHTML = `
    <span class="legend-item"><span class="legend-dot" style="background:${STATE.trajectory.mode === "trajectory" ? "var(--accent-2)" : "var(--accent)"}"></span>${STATE.entity === "owner" ? "Car" : "Driver"} · ${STATE.trajectory.mode === "trajectory" ? "season → last-5" : "season avg"}</span>
    <span class="legend-item"><span class="legend-line"></span>League trend</span>
    <span class="legend-item" style="color:var(--pos)">▲ above = converting pace to results</span>
    <span class="legend-item" style="color:var(--neg)">▼ below = leaving points on the table</span>
  `;

  const sorted = [...withResid].sort((x, y) => y.resid - x.resid);
  fillTrajCallout("trajectory-over", sorted.slice(0, 5));
  fillTrajCallout("trajectory-under", sorted.slice(-5).reverse());

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

function fillTrajCallout(hostId, rows) {
  const host = document.getElementById(hostId);
  host.innerHTML = rows.map(r => {
    const col = colorFor(STATE.series, r.entity.car_number);
    const txt = contrastTextFor(col);
    const v = r.resid.toFixed(1);
    const cls = r.resid >= 0 ? "pos" : "neg";
    const sign = r.resid >= 0 ? "+" : "";
    return `<div class="row">
      <a class="name profile-link" href="${profileHref(r.entity)}">
        <span class="car-tag" style="background:${col};color:${txt}">${r.entity.car_number}</span>
        <span>${escapeHTML(r.entity.driver)}</span>
      </a>
      <span class="delta ${cls}">${sign}${v}</span>
    </div>`;
  }).join("");
}

// ============================================================
// TEAMMATE DELTA
// ============================================================
// Alliance map (view-level only; does NOT change the underlying team tag in colors.json).
// WBR rides in the Penske shop so we compare #21 against the PEN cars.
const TEAM_ALLIANCE = { "WBR": "PEN" };
function teamGroup(team) { return TEAM_ALLIANCE[team] || team; }

// Friendly team names for the card header; fall back to the team code itself
// Track type classification — standard 4-category NASCAR split.
// Used by Stage Trajectory's track-type filter and any future track-type splits.
// Categories: super (drafting/plate), short (<1 mile), inter (1.5mi ovals + drafting-style),
// road (twisty circuits + street courses).
const TRACK_TYPES = {
  // Superspeedways — pack drafting, plates/tapered spacers
  DAY: "super",
  TAL: "super",

  // Short tracks — <1 mile ovals
  BRI: "short",
  BRD: "short",
  MAR: "short",
  RCH: "short",
  PHO: "short",        // 1mi flat but universally called a short track
  NWB: "short",
  NWK: "short",
  BGR: "short",        // Bowman Gray (Clash venue)
  IOW: "short",        // 0.875mi oval

  // Intermediate — 1.5mi-ish ovals + atlanta-as-drafting + dover (1mi concrete)
  ECH: "inter",        // Atlanta — pack racing now but still classed intermediate by teams
  ATL: "inter",
  LAS: "inter",
  KAN: "inter",
  CLT: "inter",
  TEX: "inter",
  NSH: "inter",        // Nashville Superspeedway (1.33mi)
  MIA: "inter",
  HOM: "inter",
  MCH: "inter",        // Michigan 2mi
  NHA: "inter",        // New Hampshire 1.058mi
  LOU: "inter",
  DOV: "inter",        // 1mi concrete — behaves like an intermediate for setup
  GWY: "inter",        // Gateway 1.25mi
  WWT: "inter",
  POC: "inter",        // Pocono 2.5mi tri-oval
  DAR: "inter",        // Darlington 1.366mi — not truly intermediate but slots here
  IND: "inter",        // Indy oval — rarely run but fits here

  // Road courses + street courses
  AUS: "road",         // COTA
  SON: "road",
  WGI: "road",
  CHA: "road",         // Charlotte Roval
  ROV: "road",
  IRC: "road",         // Indy RC
  CHI: "road",         // Chicago Street
  CHG: "road",
  MXI: "road",         // Mexico City (road course for 2026)
  MEX: "road",
};

const TRACK_TYPE_LABELS = {
  super: "Superspeedway",
  short: "Short Track",
  inter: "Intermediate",
  road: "Road Course",
};

function trackType(trackCode) {
  return TRACK_TYPES[trackCode] || null;
}

// Track display names — maps racing-reference track codes to the common industry name
// people actually say. When in doubt, use what a NASCAR fan/insider would call it in
// conversation, not the official venue name.
const TRACK_NAMES = {
  DAY: "Daytona",
  ECH: "Atlanta",        // rebranded EchoPark Speedway, still called Atlanta
  ATL: "Atlanta",        // older code for the same track
  AUS: "COTA",           // Circuit of the Americas
  PHO: "Phoenix",
  LAS: "Las Vegas",
  DAR: "Darlington",
  MAR: "Martinsville",
  BRI: "Bristol",
  BRD: "Bristol Dirt",   // dirt configuration, when applicable
  KAN: "Kansas",
  TAL: "Talladega",
  TEX: "Texas",
  DOV: "Dover",
  CLT: "Charlotte",
  CHA: "Roval",          // Charlotte Roval config
  ROV: "Roval",          // alt code
  NHA: "New Hampshire",
  LOU: "New Hampshire",  // Loudon — same track
  POC: "Pocono",
  CHI: "Chicago Street",
  CHG: "Chicago Street",
  NSH: "Nashville",
  MIA: "Homestead",
  HOM: "Homestead",
  IOW: "Iowa",
  GWY: "Gateway",
  WWT: "Gateway",
  SON: "Sonoma",
  WGI: "Watkins Glen",
  MCH: "Michigan",
  RCH: "Richmond",
  IRC: "Indy RC",        // Indianapolis Road Course
  IND: "Indy",           // Indianapolis Motor Speedway (oval)
  BGR: "Bowman Gray",    // BG Stadium (Clash venue)
  NWB: "North Wilkesboro",
  NWK: "North Wilkesboro",
  MXI: "Mexico City",    // 2026 international date
  MEX: "Mexico City",
};

// Return the short, insider-friendly track name.
// Prefers code lookup; falls back to the raw name if code is missing/unknown.
function prettyTrack(code, fallbackName) {
  if (code && TRACK_NAMES[code]) return TRACK_NAMES[code];
  // If we only got a name (no code), try common substrings
  if (fallbackName) {
    const n = fallbackName;
    if (/echopark/i.test(n)) return "Atlanta";
    if (/circuit of the americas/i.test(n)) return "COTA";
    if (/indianapolis/i.test(n) && /road/i.test(n)) return "Indy RC";
    if (/indianapolis/i.test(n)) return "Indy";
    if (/charlotte/i.test(n) && /roval/i.test(n)) return "Roval";
    if (/homestead/i.test(n)) return "Homestead";
    if (/new hampshire|loudon/i.test(n)) return "New Hampshire";
    if (/chicago.*street/i.test(n)) return "Chicago Street";
    if (/gateway|world wide/i.test(n)) return "Gateway";
    if (/bowman gray/i.test(n)) return "Bowman Gray";
    if (/north wilkesboro/i.test(n)) return "North Wilkesboro";
    // Default: strip common suffixes "Speedway", "Motor Speedway", "Raceway", "International Speedway"
    return n
      .replace(/\s+International Speedway\s*$/i, "")
      .replace(/\s+Motor Speedway\s*$/i, "")
      .replace(/\s+Superspeedway\s*$/i, "")
      .replace(/\s+Speedway\s*$/i, "")
      .replace(/\s+Raceway\s*$/i, "")
      .trim();
  }
  return code || "";
}

const TEAM_FULL_NAMES = {
  "JGR": "Joe Gibbs Racing", "HMS": "Hendrick Motorsports", "RCR": "Richard Childress Racing",
  "23XI": "23XI Racing", "PEN": "Team Penske", "RFK": "RFK Racing",
  "FRM": "Front Row Motorsports", "THR": "Trackhouse Racing", "LMC": "Legacy Motor Club",
  "SPI": "Spire Motorsports", "KR": "Kaulig Racing", "HFT": "Haas Factory Team",
  "HYAK": "HYAK Motorsports", "WBR": "Wood Brothers",
  "JTG": "JTG Daugherty", "RWR": "Rick Ware Racing",
  // NOS / NTS teams
  "JRM": "JR Motorsports", "APR": "Alpha Prime", "SSG": "Sam Hunt Racing",
  "JAR": "Jordan Anderson Racing", "RSS": "RSS Racing", "JGM": "Joey Gase Motorsports",
  "MHR": "MBM/Motorsports", "BMR": "Big Machine Racing", "JCR": "Jesse Iwuji Motorsports",
  "MBM": "Mike Beam Motorsports", "DGM": "DGM Racing", "YM": "Young's Motorsports",
  "CFR": "Reaume Brothers", "OM": "Our Motorsports", "SH": "Stewart-Haas",
  "BMM": "Bassett Motorsports", "PRG": "Precision Racing",
  "VM": "Viking Motorsports", "AMR": "AM Racing",
  "TRICON": "Tricon Garage", "KBM": "Kyle Busch Motorsports", "HAT": "Hattori Racing",
  "CR7": "CR7 Motorsports", "HTM": "Halmar Friesen", "BAP": "Bret Holmes Racing",
};
// Display label for the card header when an alliance groups multiple teams together
const GROUP_DISPLAY_NAMES = {
  "PEN": "Team Penske + Wood Brothers",
};

function renderTeammates() {
  const host = document.getElementById("teammates-grid");
  const empty = document.getElementById("teammates-empty");
  if (!STATE.data) return;

  const races = racesSorted();
  const totalRacesInSeason = races.length;
  if (totalRacesInSeason === 0) {
    if (empty) empty.hidden = false;
    if (host) host.innerHTML = "";
    return;
  }

  // Which cars ran every scheduled race = full-time
  const carRaceCount = {};
  races.forEach(r => {
    const seen = new Set();
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      if (seen.has(d.car_number)) return;
      seen.add(d.car_number);
      carRaceCount[d.car_number] = (carRaceCount[d.car_number] || 0) + 1;
    });
  });
  const fullTimeCars = new Set(
    Object.keys(carRaceCount).filter(c => carRaceCount[c] >= totalRacesInSeason)
  );

  // Walk each race, compute per-car deltas vs. the best FULL-TIME teammate in the same group
  const carData = new Map();   // car_number -> aggregated entry
  const trackByRound = {};
  races.forEach(r => { trackByRound[r.round] = { code: r.track_code || "", name: r.track || "" }; });

  races.forEach(r => {
    // Bucket this race's results by group
    const groupAll = {};     // group -> [entry, ...]
    const groupFt  = {};     // group -> [FT-only entries]
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      const team = teamCodeFromPalette(STATE.series, d.car_number);
      if (!team) return;
      const grp = teamGroup(team);
      const rec = {
        car: d.car_number, driver: d.driver, team, grp,
        finish: d.finish_pos,
        total: d.race_pts || 0,
      };
      (groupAll[grp] ||= []).push(rec);
      if (fullTimeCars.has(d.car_number)) {
        (groupFt[grp] ||= []).push(rec);
      }
    });

    // For each group, compute benchmark (best FT car) + each member's delta
    Object.keys(groupAll).forEach(grp => {
      const ftArr = groupFt[grp] || [];
      if (ftArr.length < 2) return;   // need ≥2 FT cars for a benchmark
      const finishes = ftArr.map(e => e.finish).filter(f => f != null);
      if (finishes.length === 0) return;
      const bestFinish = Math.min(...finishes);
      const bestTotal  = Math.max(...ftArr.map(e => e.total));

      groupAll[grp].forEach(e => {
        const isFt = fullTimeCars.has(e.car);
        const deltaFin = (e.finish != null) ? (bestFinish - e.finish) : null;
        const deltaTot = e.total - bestTotal;
        const tlFin = isFt && e.finish != null && e.finish === bestFinish;

        let agg = carData.get(e.car);
        if (!agg) {
          agg = {
            car_number: e.car,
            team: e.team,          // real team code (e.g. WBR)
            group: e.grp,          // alliance group (e.g. PEN)
            drivers: new Map(),    // driver name -> race count
            series: [],
            car_full_time: isFt,
          };
          carData.set(e.car, agg);
        }
        agg.drivers.set(e.driver, (agg.drivers.get(e.driver) || 0) + 1);
        agg.series.push({
          round: r.round,
          driver: e.driver,
          finish: e.finish,
          total: e.total,
          delta_fin: deltaFin,
          delta_tot: deltaTot,
          tl_fin: tlFin,
          track_code: trackByRound[r.round]?.code || "",
          track_name: trackByRound[r.round]?.name || "",
        });
      });
    });
  });

  // Season points per car (for group/team ranking)
  const seasonPts = {};
  races.forEach(r => {
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      seasonPts[d.car_number] = (seasonPts[d.car_number] || 0) + (d.race_pts || 0);
    });
  });

  // Build final per-car records
  const cars = [];
  carData.forEach((agg, car) => {
    const driversRanked = [...agg.drivers.entries()].sort((a, b) => b[1] - a[1]);
    const fins = agg.series.map(s => s.delta_fin).filter(x => x != null);
    const avgFin = fins.length ? fins.reduce((s,x) => s+x, 0) / fins.length : 0;
    const tots = agg.series.map(s => s.delta_tot);
    const avgTot = tots.length ? tots.reduce((s,x) => s+x, 0) / tots.length : 0;
    const tl = agg.series.filter(s => s.tl_fin).length;
    cars.push({
      car_number: car,
      team: agg.team,
      group: agg.group,
      primary_driver: driversRanked[0][0],
      drivers: driversRanked.map(([n]) => n),
      driver_counts: driversRanked.map(([n, c]) => ({ name: n, races: c })),
      n_races: agg.series.length,
      car_full_time: agg.car_full_time,
      season_points: seasonPts[car] || 0,
      avg_delta_fin: avgFin,
      avg_delta_tot: avgTot,
      tl_races_fin: tl,
      series: agg.series.slice().sort((a, b) => a.round - b.round),
    });
  });

  // Filter part-timers if the toggle says so
  const visibleCars = STATE.teammates.ftOnly
    ? cars.filter(c => c.car_full_time)
    : cars;

  // Bucket by group (alliance-aware)
  const byGroup = {};
  visibleCars.forEach(c => { (byGroup[c.group] ||= []).push(c); });
  const groups = Object.entries(byGroup).filter(([_, arr]) => arr.length >= 2);

  if (groups.length === 0) {
    host.innerHTML = "";
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;

  // Sort groups by best-car season points desc
  groups.sort((a, b) =>
    Math.max(...b[1].map(d => d.season_points)) -
    Math.max(...a[1].map(d => d.season_points))
  );
  groups.forEach(([_, arr]) => arr.sort((a, b) => b.season_points - a.season_points));

  const metric = STATE.teammates.metric;
  const avgKey = metric === "fin" ? "avg_delta_fin" : "avg_delta_tot";
  const deltaField = metric === "fin" ? "delta_fin" : "delta_tot";

  const html = groups.map(([grp, members]) => {
    // Team pill color derived from the GROUP's org color (look up any member with the group's team code,
    // else fall back to the first member's org color)
    const repCar = members.find(m => m.team === grp) || members[0];
    const orgHex = orgColorFor(STATE.series, repCar.car_number) || "#9ca3af";
    const orgTxt = contrastTextFor(orgHex);
    const displayName = GROUP_DISPLAY_NAMES[grp] || TEAM_FULL_NAMES[grp] || grp;
    const bestCar = members[0];
    const ftCount = members.filter(m => m.car_full_time).length;
    const ptCount = members.length - ftCount;

    const rows = members.map(d => {
      const carHex = colorFor(STATE.series, d.car_number);
      const carTxt = contrastTextFor(carHex);
      const avg = d[avgKey];
      const avgCls = tmDeltaClass(metric, avg);
      const sparkPts = d.series.map(s => ({ v: s[deltaField], tl: s.tl_fin, round: s.round }));
      const svg = tmSparkline(sparkPts, carHex, metric, d.car_number);
      const isShared = d.drivers.length > 1;
      const showWbrTag = (d.team !== d.group);
      const ptTag = d.car_full_time ? "" : ` <span class="tm-pt-tag">PT</span>`;
      const tmHref = (STATE.entity === "owner") ? `#/car/${d.car_number}` : `#/profile/${slugify(d.primary_driver)}`;
      return `<div class="tm-row${d.car_full_time ? "" : " part-time"}">
        <span class="tm-car" style="background:${carHex};color:${carTxt}">${d.car_number}</span>
        <div class="tm-name">
          <div class="tm-name-row">
            <a class="tm-name-primary profile-link" href="${tmHref}">${escapeHTML(d.primary_driver)}</a>${ptTag}
            ${isShared ? `<span class="tm-shared" data-car="${d.car_number}" title="Shared car — hover for details">i</span>` : ""}
            ${showWbrTag ? `<span class="tm-true-team">${escapeHTML(d.team)}</span>` : ""}
          </div>
          <div class="tm-name-sub">${d.n_races} race${d.n_races === 1 ? "" : "s"}</div>
        </div>
        <div class="tm-spark">${svg}</div>
        <div class="tm-avg ${avgCls}">${avg >= 0 ? "+" : ""}${avg.toFixed(1)}</div>
        <div class="tm-tl"><span class="big">${d.tl_races_fin}</span>/${d.n_races}</div>
      </div>`;
    }).join("");

    return `<div class="tm-card">
      <div class="tm-card-head">
        <span class="team-pill" style="background:${orgHex};color:${orgTxt}">${escapeHTML(grp)}</span>
        <span class="tm-team-name">${escapeHTML(displayName)}</span>
        <span class="tm-team-meta">${ftCount} FT${ptCount > 0 ? ` + ${ptCount} PT` : ""} · ${bestCar.season_points}pts</span>
      </div>
      <div class="tm-col-headers">
        <span></span>
        <span>Driver</span>
        <span style="text-align:center">Per-race Δ</span>
        <span class="tm-right tm-help" data-explain="avg">Δ AVG</span>
        <span class="tm-right tm-help" data-explain="best">BEST</span>
      </div>
      ${rows}
    </div>`;
  }).join("");

  host.innerHTML = html;

  // Paint sparklines at their actual rendered widths so circles stay truly round.
  // Waiting one frame lets the browser complete layout before we measure.
  requestAnimationFrame(() => tmPaintSparklines(host));

  // Watch for container width changes and repaint sparklines (not the full render).
  // One observer on the grid, not one per SVG — saves a ton of observer overhead.
  if (!host._tmResizeObserver && typeof ResizeObserver !== "undefined") {
    let timer = null;
    host._tmResizeObserver = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => tmPaintSparklines(host), 80);
    });
    host._tmResizeObserver.observe(host);
  }

  // ---- Wire hover tooltips ----
  const tip = document.getElementById("metric-tooltip");
  if (!tip) return;

  const carMap = new Map(cars.map(c => [c.car_number, c]));
  const seriesLookup = new Map();
  cars.forEach(c => c.series.forEach(s => seriesLookup.set(`${c.car_number}|${s.round}`, { ...s, primary_driver: c.primary_driver })));

  function showTip(html, evt, className) {
    tip.innerHTML = html;
    tip.className = "";
    if (className) {
      // classList.add throws on tokens with spaces — split and spread
      className.split(/\s+/).filter(Boolean).forEach(c => tip.classList.add(c));
    }
    tip.classList.add("show");
    const rect = tip.getBoundingClientRect();
    let left = evt.clientX + 12, top = evt.clientY + 12;
    if (left + rect.width > window.innerWidth - 8) left = evt.clientX - rect.width - 12;
    if (top + rect.height > window.innerHeight - 8) top = evt.clientY - rect.height - 12;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    tip.style.left = `${left}px`;
    tip.style.top  = `${top}px`;
  }
  function hideTip() { tip.classList.remove("show"); }

  // Dot tooltips — use event delegation on the host because dots are painted
  // asynchronously (next animation frame) by tmPaintSparklines. Direct listeners
  // would attach before the dots exist.
  function handleDotHover(ev) {
    const hit = ev.target.closest(".tm-dot-hit");
    if (!hit || !host.contains(hit)) return;
    const round = hit.getAttribute("data-round");
    const car = hit.getAttribute("data-car");
    const s = seriesLookup.get(`${car}|${round}`);
    if (!s) return;
    const v = metric === "fin" ? s.delta_fin : s.delta_tot;
    const cls = v >= 0 ? "pos" : "neg";
    const vStr = v >= 0 ? `+${v}` : `${v}`;
    const trackLabel = prettyTrack(s.track_code, s.track_name);
    const driverLine = s.driver !== s.primary_driver
      ? `<div class="tm-tt-driver">Driver: ${escapeHTML(s.driver)}</div>`
      : "";
    const html = `
      <div class="tm-tt-hdr">#${car} · R${s.round}${trackLabel ? " · " + escapeHTML(trackLabel) : ""}</div>
      ${driverLine}
      <div class="tm-tt-row"><span class="lbl">Finish</span><span class="val">P${s.finish ?? "—"}</span></div>
      <div class="tm-tt-row"><span class="lbl">Race pts</span><span class="val">${s.total}</span></div>
      <div class="tm-tt-row ${cls}"><span class="lbl">vs best FT teammate</span><span class="val">${vStr}${s.tl_fin ? " ★" : ""}</span></div>
    `;
    showTip(html, ev, "tm-tip");
  }
  function handleDotLeave(ev) {
    // Only hide when actually leaving a .tm-dot-hit (not when moving between children of one)
    const hit = ev.target.closest(".tm-dot-hit");
    const going = ev.relatedTarget && ev.relatedTarget.closest ? ev.relatedTarget.closest(".tm-dot-hit") : null;
    if (hit && !going) hideTip();
  }
  // Remove any stale listeners from prior renders on the same host
  if (host._dotMove) host.removeEventListener("mousemove", host._dotMove);
  if (host._dotOut)  host.removeEventListener("mouseout",  host._dotOut);
  host._dotMove = handleDotHover;
  host._dotOut  = handleDotLeave;
  host.addEventListener("mousemove", host._dotMove);
  host.addEventListener("mouseout",  host._dotOut);

  // Shared-car "ⁱ" popovers
  host.querySelectorAll(".tm-shared").forEach(el => {
    const car = el.getAttribute("data-car");
    const c = carMap.get(car);
    if (!c || !c.driver_counts || c.driver_counts.length < 2) return;
    const rows = c.driver_counts.map((dc, i) => {
      const cls = i === 0 ? "primary" : "";
      return `<div class="tm-sl-row ${cls}"><span>${escapeHTML(dc.name)}</span><span class="n">${dc.races} race${dc.races === 1 ? "" : "s"}</span></div>`;
    }).join("");
    const html = `<div class="tm-sl-hdr">Shared Car #${car} · ${c.n_races} races total</div>${rows}`;
    el.addEventListener("mouseenter", e => showTip(html, e, "tm-tip tm-sl"));
    el.addEventListener("mousemove",  e => showTip(html, e, "tm-tip tm-sl"));
    el.addEventListener("mouseleave", hideTip);
  });

  // Column-header explainers
  host.querySelectorAll(".tm-help").forEach(el => {
    const k = el.getAttribute("data-explain");
    const msg = k === "avg"
      ? "Δ AVG: season average delta vs. the best full-time car on the team each race. Closer to 0 = consistently near the team's top performer."
      : "BEST: races this car was the best-finishing full-time car on the team, out of total races run.";
    el.addEventListener("mouseenter", e => showTip(msg, e, "tm-tip tm-explain"));
    el.addEventListener("mousemove",  e => showTip(msg, e, "tm-tip tm-explain"));
    el.addEventListener("mouseleave", hideTip);
  });
}

// Build the sparkline SVG for a teammate row
function tmSparkline(seriesPts, color, metric, carLabel) {
  // Emit a placeholder SVG with the data encoded. After the DOM is inserted,
  // tmPaintSparklines() measures each SVG's actual rendered width and draws
  // using viewBox = pixel dimensions (so circles stay truly round).
  if (seriesPts.length === 0) return "";
  const data = encodeURIComponent(JSON.stringify(seriesPts));
  return `<svg class="tm-spk" data-series="${data}" data-color="${color}" data-metric="${metric}" data-car="${carLabel}" style="width:100%;height:38px;display:block;"></svg>`;
}

// Measure every .tm-spk SVG and draw it at its real pixel dimensions so circles stay round.
function tmPaintSparklines(root) {
  const svgs = (root || document).querySelectorAll("svg.tm-spk");
  svgs.forEach(svg => {
    const rect = svg.getBoundingClientRect();
    const W = Math.max(80, Math.floor(rect.width));
    const H = 38;
    const pad = { t: 5, b: 5, l: 3, r: 3 };
    const innerW = W - pad.l - pad.r, innerH = H - pad.t - pad.b;

    const seriesPts = JSON.parse(decodeURIComponent(svg.getAttribute("data-series") || "[]"));
    const color = svg.getAttribute("data-color") || "#9ca3af";
    const metric = svg.getAttribute("data-metric") || "fin";
    const carLabel = svg.getAttribute("data-car") || "";
    const clipCap = metric === "fin" ? 40 : 50;

    const xScale = i => pad.l + (seriesPts.length === 1 ? innerW / 2 : (i / (seriesPts.length - 1)) * innerW);
    const yScale = v => {
      const clipped = Math.max(-clipCap, Math.min(0, v));
      return pad.t + ((0 - clipped) / clipCap) * innerH;
    };

    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.removeAttribute("preserveAspectRatio");  // default = xMidYMid meet, preserves circle shape

    const zeroY = yScale(0);
    const zero = `<line class="tm-spk-zero" x1="${pad.l}" x2="${W - pad.r}" y1="${zeroY}" y2="${zeroY}"/>`;
    const pathD = seriesPts.map((p, i) => `${xScale(i)},${yScale(p.v)}`).join(" ");
    const line = `<polyline class="tm-spk-line" points="${pathD}" stroke="${color}"/>`;
    const dots = seriesPts.map((p, i) => {
      const x = xScale(i), y = yScale(p.v);
      const r = p.tl ? 3 : 2.4;
      const fill = p.tl ? "transparent" : color;
      const stroke = p.tl ? color : "none";
      const sw = p.tl ? 1.4 : 0;
      return `<g class="tm-dot-hit" data-round="${p.round}" data-car="${carLabel}">
        <circle cx="${x}" cy="${y}" r="7" fill="transparent"/>
        <circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>
      </g>`;
    }).join("");

    svg.innerHTML = `${zero}${line}${dots}`;
  });
}

function tmDeltaClass(metric, avg) {
  const scale = metric === "fin" ? 1 : 3;
  if (avg >= -2 * scale) return "good";
  if (avg <= -8 * scale) return "bad";
  return "meh";
}

// ============================================================
// PROFILE (driver or car)
// ============================================================
// Resolves a slug to an entity from the current season's data.
// Returns null if not found. This is the current-season view — career-wide
// aggregation will come in a later pass with lazy-loaded other seasons.
function findEntityFromSlug() {
  if (!STATE.data || !STATE.profile.slug) return null;
  const races = racesSorted();
  if (STATE.profile.kind === "car") {
    // Find any race where this car_number appears
    for (const r of races) {
      for (const d of (r.results || [])) {
        if (d.ineligible) continue;
        if (d.car_number === STATE.profile.slug) {
          // Return an entity wrapped like allEntities() would
          return allEntities().find(e => e.car_number === d.car_number) || null;
        }
      }
    }
    return null;
  }
  // driver profile (default)
  for (const e of allEntities()) {
    if (slugify(e.driver) === STATE.profile.slug) return e;
    // Also check every driver who ever drove this car (shared-car case)
    if (e.drivers && e.drivers.some(dn => slugify(dn) === STATE.profile.slug)) {
      return allEntities().find(x => x.driver === e.drivers.find(dn => slugify(dn) === STATE.profile.slug)) || e;
    }
  }
  return null;
}

// Determine which season a car ran (needed for the career table once lazy-loaded).
// For now just the current season.
function profileRaceRows(entity) {
  const races = racesSorted();
  const byRound = {};
  entity.races.forEach(r => { byRound[r.round] = r; });
  return races.map(r => {
    const mine = byRound[r.round];
    const meta = { round: r.round, date: r.date, track: r.track, track_code: r.track_code, name: r.name };
    if (!mine) return { ...meta, dns: true };
    return {
      ...meta,
      start: mine.start,
      finish: mine.finish,
      s1: mine.s1, s2: mine.s2, fin: mine.fin, fl: mine.fl,
      total: mine.total,
      status: mine.status,
      driver: mine.driver,
    };
  });
}

function profileSummary(entity) {
  const rows = entity.races;
  const finishes = rows.map(r => r.finish).filter(x => x != null);
  const starts = rows.length;
  const wins = finishes.filter(f => f === 1).length;
  const t5 = finishes.filter(f => f <= 5).length;
  const t10 = finishes.filter(f => f <= 10).length;
  const avgFin = finishes.length ? (finishes.reduce((s, x) => s + x, 0) / finishes.length) : null;
  const totalPts = rows.reduce((s, r) => s + (r.total || 0), 0);
  return { starts, wins, t5, t10, avgFin, totalPts };
}

function profileRank(entity) {
  const totals = computeSeasonTotals();
  const idx = totals.findIndex(t => t.driver === entity.driver && t.car_number === entity.car_number);
  return { rank: idx + 1, of: totals.length };
}

// Compute teammate deltas just for this driver this season (reuses teammate view's logic lightly)
function profileTeammates(entity) {
  if (!STATE.data) return [];
  const races = racesSorted();
  const totalSeason = races.length;
  // Build full-time car set
  const carCount = {};
  races.forEach(r => {
    const seen = new Set();
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      if (seen.has(d.car_number)) return;
      seen.add(d.car_number);
      carCount[d.car_number] = (carCount[d.car_number] || 0) + 1;
    });
  });
  const ftCars = new Set(Object.keys(carCount).filter(c => carCount[c] >= totalSeason));

  const myTeam = teamCodeFromPalette(STATE.series, entity.car_number);
  if (!myTeam) return [];

  // Alliance: WBR rides with PEN
  const ALLIANCE = { WBR: "PEN" };
  const myGroup = ALLIANCE[myTeam] || myTeam;

  // Head-to-head record per teammate + avg delta
  const mates = {};  // teammate driver name → { car, beat, lost, tied, deltas: [] }
  races.forEach(r => {
    let myEntry = null;
    const teamEntries = [];
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      const t = teamCodeFromPalette(STATE.series, d.car_number);
      if (!t) return;
      const g = ALLIANCE[t] || t;
      if (g !== myGroup) return;
      if (d.car_number === entity.car_number) myEntry = d;
      else teamEntries.push(d);
    });
    if (!myEntry || myEntry.finish_pos == null) return;
    teamEntries.forEach(te => {
      if (te.finish_pos == null) return;
      const key = te.driver;
      if (!mates[key]) mates[key] = { driver: te.driver, car: te.car_number, beat: 0, lost: 0, tied: 0, deltaSum: 0, races: 0 };
      if (myEntry.finish_pos < te.finish_pos) mates[key].beat++;
      else if (myEntry.finish_pos > te.finish_pos) mates[key].lost++;
      else mates[key].tied++;
      mates[key].deltaSum += (te.finish_pos - myEntry.finish_pos);  // positive = I beat them
      mates[key].races++;
    });
  });
  return Object.values(mates)
    .map(m => ({ ...m, avgDelta: m.races ? m.deltaSum / m.races : 0 }))
    .sort((a, b) => b.avgDelta - a.avgDelta);
}

function renderProfile() {
  const host = document.getElementById("view-profile");
  if (!host) return;
  if (!STATE.data) {
    host.innerHTML = `<div class="view-head"><h1>Profile</h1><div class="view-sub">No data loaded.</div></div>`;
    return;
  }

  const entity = findEntityFromSlug();
  if (!entity) {
    host.innerHTML = `
      <div class="view-head"><h1>Profile not found</h1>
        <div class="view-sub">No driver or car matched "${escapeHTML(STATE.profile.slug || "")}" in ${STATE.season} ${STATE.series}. <a href="#/standings" class="profile-backlink">Back to Standings →</a></div>
      </div>`;
    return;
  }

  // Resolve display entity based on current DRIVER/OWNER toggle.
  // In owner mode, profile is a CAR (aggregated); in driver mode, a DRIVER.
  // Currently this is the natural entity shape from allEntities(), which respects the toggle.
  const kind = STATE.entity;  // "driver" | "owner"
  const summary = profileSummary(entity);
  const { rank, of } = profileRank(entity);
  const carHex = colorFor(STATE.series, entity.car_number);
  const carTxt = contrastTextFor(carHex);
  const teamCode = teamCodeFromPalette(STATE.series, entity.car_number) || "";
  const orgHex = orgColorFor(STATE.series, entity.car_number) || "#555";
  const orgTxt = contrastTextFor(orgHex);

  const displayTitle = (kind === "owner")
    ? (entity.drivers && entity.drivers.length > 1
        ? `#${entity.car_number} · ${entity.driver} +${entity.drivers.length - 1}`
        : `#${entity.car_number} · ${entity.driver}`)
    : entity.driver;

  const rows = profileRaceRows(entity);
  const mfr = { TYT: "Toyota", CHE: "Chevrolet", CHV: "Chevrolet", FRD: "Ford", FOR: "Ford" }[entity.manufacturer] || entity.manufacturer || "—";
  const teamName = TEAM_FULL_NAMES[teamCode] || teamCode;

  // Bio lookup — use primary driver for both kinds (car profiles show the main driver's bio/career)
  const bioDriverName = entity.driver;  // primary driver for this entity
  const bio = STATE.driverBios ? STATE.driverBios[slugify(bioDriverName)] : null;
  const bioParts = [];
  if (bio && kind !== "owner") {
    // Age + hometown only shown in driver mode — would be misleading in car mode
    if (bio.dob) {
      const age = calcAge(bio.dob);
      if (age != null) bioParts.push(`<span class="v">${age}</span> years old`);
    }
    if (bio.hometown) bioParts.push(`<span class="v">${escapeHTML(bio.hometown)}</span>`);
  }
  const bioLine = bioParts.length
    ? `<span class="profile-hero-bio">${bioParts.join(" · ")}</span>`
    : "";

  // Career totals panel: works for both driver and car profiles.
  // Car profiles label it explicitly as being the primary driver's career.
  const careerPanelHTML = (bio && bio.career && Object.keys(bio.career).length > 0)
    ? renderCareerTotalsPanel(bio.career, kind === "owner" ? bioDriverName : null)
    : (STATE.driverBios === null
        ? "" // no data file yet — just hide the panel instead of showing a nag
        : `<div class="profile-panel full">
             <div class="profile-panel-head">
               <span class="profile-panel-title">Career By Series</span>
             </div>
             <div class="profile-panel-body">
               <div class="muted" style="padding:10px 4px;font-size:12px;">No career data available for ${escapeHTML(bioDriverName)} yet.</div>
             </div>
           </div>`);

  host.innerHTML = `
    <div class="profile-breadcrumb">
      <a href="#/standings" class="profile-backlink">← Standings</a>
      <span class="sep">/</span>
      <span>${escapeHTML(displayTitle)}</span>
    </div>

    <div class="profile-hero" style="--driver-color:${carHex}">
      <div class="profile-hero-car" style="background:${carHex};color:${carTxt}">${entity.car_number}</div>
      <div class="profile-hero-info">
        <h1 class="profile-hero-name">${escapeHTML(displayTitle)}</h1>
        <div class="profile-hero-meta">
          <span class="team-pill" style="background:${orgHex};color:${orgTxt}">${escapeHTML(teamCode)}</span>
          <span class="profile-hero-team"><strong>${escapeHTML(mfr)}</strong> · ${escapeHTML(teamName)}</span>
          ${bioLine}
        </div>
      </div>
      <div class="profile-hero-rank">
        <div class="profile-rank-num" style="color:${carHex}">${rank}${rankSuffix(rank)}</div>
        <div class="profile-rank-label">${STATE.season} ${STATE.series}</div>
        <div class="profile-rank-pts">${summary.totalPts} pts</div>
      </div>
    </div>

    ${careerPanelHTML}

    <div class="profile-section-label">${STATE.season} Season</div>
    <div class="profile-stats">
      <div class="stat"><span class="k">Starts</span><span class="v">${summary.starts}</span></div>
      <div class="stat"><span class="k">Wins</span><span class="v ${summary.wins > 0 ? 'hot' : ''}">${summary.wins}</span></div>
      <div class="stat"><span class="k">Top 5</span><span class="v">${summary.t5}</span></div>
      <div class="stat"><span class="k">Top 10</span><span class="v">${summary.t10}</span></div>
      <div class="stat"><span class="k">Avg Finish</span><span class="v">${summary.avgFin ? summary.avgFin.toFixed(1) : '—'}</span></div>
      <div class="stat"><span class="k">Points rank</span><span class="v">${rank} / ${of}</span></div>
    </div>

    <div class="profile-panels">
      <div class="profile-panel">
        <div class="profile-panel-head">
          <span class="profile-panel-title">${STATE.season} Season Cumulative</span>
          <span class="profile-panel-sub">Points accrued by race</span>
        </div>
        <div class="profile-panel-body">
          <svg id="profile-chart" style="width:100%;height:260px;display:block;"></svg>
        </div>
      </div>

      <div class="profile-panel">
        <div class="profile-panel-head">
          <span class="profile-panel-title">${STATE.season} Finish Per Race</span>
          <span class="profile-panel-sub">Green = top · Red = bad day</span>
        </div>
        <div class="profile-panel-body">
          <div class="profile-heat-strip" id="profile-heat-strip"></div>
        </div>
      </div>

      <div class="profile-panel full">
        <div class="profile-panel-head">
          <span class="profile-panel-title">${STATE.season} Track Splits</span>
          <div class="profile-panel-head-right">
            <div class="toggle-group mini" data-group="splits-range">
              <button class="on" data-val="season">Season</button>
              <button data-val="career" disabled title="Career-wide splits require multi-year data (coming with lazy-load feature)">Career</button>
            </div>
          </div>
        </div>
        <div class="profile-panel-body">
          <div class="track-splits-grid" id="profile-track-splits"></div>
        </div>
      </div>

      <div class="profile-panel full">
        <div class="profile-panel-head">
          <span class="profile-panel-title">${STATE.season} Race-by-Race</span>
          <span class="profile-panel-sub">${rows.filter(r => !r.dns).length} starts</span>
        </div>
        <div class="profile-panel-body" style="padding:0;">
          <div style="overflow-x:auto;">
          <table class="profile-race-table">
            <thead>
              <tr>
                <th>R</th>
                <th>Track</th>
                <th>Race</th>
                <th class="num">Start</th>
                <th class="num">Finish</th>
                <th class="num">S1</th>
                <th class="num">S2</th>
                <th class="num">FL</th>
                <th class="num">Fin pts</th>
                <th class="num">Total</th>
              </tr>
            </thead>
            <tbody id="profile-race-tbody"></tbody>
          </table>
          </div>
        </div>
      </div>

      <div class="profile-panel full">
        <div class="profile-panel-head">
          <span class="profile-panel-title">${STATE.season} Teammates</span>
          <span class="profile-panel-sub">Head-to-head vs. ${escapeHTML(teamCode)} drivers</span>
        </div>
        <div class="profile-panel-body">
          <div id="profile-teammates"></div>
        </div>
      </div>
    </div>
  `;

  // --- Fill in the chart ---
  paintProfileChart(entity, rows);
  paintProfileHeatStrip(rows);
  paintProfileTrackSplits(entity);
  paintProfileRaceTable(rows, kind);
  paintProfileTeammates(entity);
}

function rankSuffix(n) {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "st";
  if (mod10 === 2 && mod100 !== 12) return "nd";
  if (mod10 === 3 && mod100 !== 13) return "rd";
  return "th";
}

// Compute age in whole years given a YYYY-MM-DD birthdate string
function calcAge(dobIso) {
  if (!dobIso) return null;
  const parts = dobIso.split("-").map(Number);
  if (parts.length !== 3) return null;
  const [y, m, d] = parts;
  const now = new Date();
  let age = now.getFullYear() - y;
  const hadBirthday = (now.getMonth() + 1) > m || ((now.getMonth() + 1) === m && now.getDate() >= d);
  if (!hadBirthday) age -= 1;
  return (age >= 0 && age < 120) ? age : null;
}

// Render the career-totals panel using scraped per-series totals.
// If `carModeDriverName` is non-null, we're on a car profile and should note
// that the career stats belong to the primary driver of the car, not the car.
function renderCareerTotalsPanel(career, carModeDriverName) {
  const SERIES_ORDER = ["NCS", "NOS", "NTS"];
  const SERIES_NAMES = { NCS: "Cup Series", NOS: "Xfinity Series", NTS: "Truck Series" };
  const availableSeries = SERIES_ORDER.filter(s => career[s]);
  if (availableSeries.length === 0) {
    return `<div class="profile-panel full">
      <div class="profile-panel-head">
        <span class="profile-panel-title">Career By Series</span>
      </div>
      <div class="profile-panel-body">
        <div class="muted" style="padding:10px 4px;font-size:12px;">No career data available.</div>
      </div>
    </div>`;
  }

  const cards = availableSeries.map(code => {
    const c = career[code];
    const winPct = (c.starts && c.wins != null) ? ((c.wins / c.starts) * 100).toFixed(1) : null;
    const t5Pct = (c.starts && c.top5 != null) ? ((c.top5 / c.starts) * 100).toFixed(1) : null;
    const t10Pct = (c.starts && c.top10 != null) ? ((c.top10 / c.starts) * 100).toFixed(1) : null;
    return `<div class="career-card">
      <div class="career-card-head">
        <span class="career-series-code">${code}</span>
        <span class="career-series-name">${SERIES_NAMES[code]}</span>
        <span class="career-years">${c.years != null ? c.years + ' yrs' : ''}</span>
      </div>
      <div class="career-card-body">
        <div class="career-stat"><span class="k">Starts</span><span class="v">${c.starts ?? '—'}</span></div>
        <div class="career-stat"><span class="k">Wins</span><span class="v ${c.wins > 0 ? 'hot' : ''}">${c.wins ?? '—'}</span>${winPct ? `<span class="pct">${winPct}%</span>` : ''}</div>
        <div class="career-stat"><span class="k">Top 5</span><span class="v">${c.top5 ?? '—'}</span>${t5Pct ? `<span class="pct">${t5Pct}%</span>` : ''}</div>
        <div class="career-stat"><span class="k">Top 10</span><span class="v">${c.top10 ?? '—'}</span>${t10Pct ? `<span class="pct">${t10Pct}%</span>` : ''}</div>
        <div class="career-stat"><span class="k">Poles</span><span class="v">${c.poles ?? '—'}</span></div>
        <div class="career-stat"><span class="k">Laps Led</span><span class="v">${c.laps_led != null ? c.laps_led.toLocaleString() : '—'}</span></div>
        <div class="career-stat"><span class="k">Avg Start</span><span class="v">${c.avg_start != null ? c.avg_start.toFixed(1) : '—'}</span></div>
        <div class="career-stat"><span class="k">Avg Finish</span><span class="v">${c.avg_finish != null ? c.avg_finish.toFixed(1) : '—'}</span></div>
      </div>
    </div>`;
  }).join("");

  const subLabel = carModeDriverName
    ? `Career of primary driver: ${escapeHTML(carModeDriverName)}`
    : "Lifetime totals";

  return `<div class="profile-panel full">
    <div class="profile-panel-head">
      <span class="profile-panel-title">Career By Series</span>
      <span class="profile-panel-sub">${subLabel}</span>
    </div>
    <div class="profile-panel-body">
      <div class="career-cards">${cards}</div>
    </div>
  </div>`;
}

function paintProfileChart(entity, rows) {
  const svg = document.getElementById("profile-chart");
  if (!svg) return;
  const carHex = colorFor(STATE.series, entity.car_number);

  // Cumulative
  let cum = 0;
  const pts = rows.filter(r => !r.dns).map(r => { cum += r.total || 0; return { round: r.round, cum, finish: r.finish, track_code: r.track_code, track: r.track }; });
  if (pts.length === 0) { svg.innerHTML = ""; return; }
  const rawMax = pts[pts.length - 1].cum;
  const maxPts = Math.max(50, Math.ceil((rawMax * 1.08) / 50) * 50);

  function draw() {
    const rect = svg.getBoundingClientRect();
    const W = Math.max(320, Math.floor(rect.width));
    const H = 260;
    const pad = { t: 16, r: 48, b: 32, l: 52 };
    const innerW = W - pad.l - pad.r, innerH = H - pad.t - pad.b;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.removeAttribute("preserveAspectRatio");

    const xScale = i => pad.l + (pts.length === 1 ? innerW / 2 : (i / (pts.length - 1)) * innerW);
    const yScale = v => pad.t + (1 - v / maxPts) * innerH;

    const gridY = [];
    for (let i = 0; i <= 5; i++) {
      const y = pad.t + (i / 5) * innerH;
      const v = Math.round(maxPts * (1 - i / 5));
      gridY.push(`<line class="chart-gridline" x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}"/>`);
      gridY.push(`<text class="axis-label" x="${pad.l - 6}" y="${y + 3}" text-anchor="end">${v}</text>`);
    }
    const xLabels = pts.map((p, i) =>
      `<text class="axis-label" x="${xScale(i)}" y="${H - 10}" text-anchor="middle">R${p.round}</text>`
    ).join("");

    const lineD = pts.map((p, i) => `${xScale(i)},${yScale(p.cum)}`).join(" ");
    const areaD = `M${xScale(0)},${pad.t + innerH} L${pts.map((p, i) => `${xScale(i)},${yScale(p.cum)}`).join(" L")} L${xScale(pts.length - 1)},${pad.t + innerH} Z`;

    const dots = pts.map((p, i) => {
      const isWin = p.finish === 1;
      const r = isWin ? 5 : 3.5;
      const stroke = isWin ? "#fff" : "none";
      const x = xScale(i), y = yScale(p.cum);
      return `<g class="profile-chart-hit" data-round="${p.round}" data-finish="${p.finish ?? ''}" data-track="${escapeHTML(p.track || '')}" data-track-code="${escapeHTML(p.track_code || '')}" data-cum="${p.cum}">
        <circle cx="${x}" cy="${y}" r="10" fill="transparent"/>
        <circle cx="${x}" cy="${y}" r="${r}" fill="${carHex}" stroke="${stroke}" stroke-width="${isWin ? 1.5 : 0}"/>
      </g>`;
    }).join("");

    const last = pts[pts.length - 1];
    const lastX = xScale(pts.length - 1), lastY = yScale(last.cum);
    const labelTotal = `<text x="${lastX + 8}" y="${lastY + 4}" font-family="var(--mono)" font-size="12" font-weight="700" fill="${carHex}">${last.cum}</text>`;

    svg.innerHTML = `
      <defs>
        <linearGradient id="profile-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${carHex}" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="${carHex}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${gridY.join("")}
      ${xLabels}
      <path d="${areaD}" fill="url(#profile-grad)" opacity="0.4"/>
      <polyline points="${lineD}" fill="none" stroke="${carHex}" stroke-width="2"/>
      ${dots}
      ${labelTotal}
    `;
  }
  requestAnimationFrame(draw);
  if (typeof ResizeObserver !== "undefined" && !svg._ro) {
    let t = null;
    svg._ro = new ResizeObserver(() => { clearTimeout(t); t = setTimeout(draw, 80); });
    svg._ro.observe(svg);
  }

  // Hover tooltip — event delegation survives re-draws
  const tip = document.getElementById("metric-tooltip");
  if (tip) {
    const rowsByRound = {};
    rows.forEach(r => { rowsByRound[r.round] = r; });

    function showChartTip(ev) {
      const hit = ev.target.closest(".profile-chart-hit");
      if (!hit) return;
      const round = parseInt(hit.getAttribute("data-round"), 10);
      const r = rowsByRound[round];
      if (!r) return;
      let cls = "f-normal";
      if (r.finish === 1) cls = "f-win";
      else if (r.finish <= 5) cls = "f-t5";
      else if (r.finish <= 10) cls = "f-t10";
      else if (r.finish > 25) cls = "f-bad";
      const html = `
        <div class="tm-tt-hdr">R${r.round} · ${escapeHTML(prettyTrack(r.track_code, r.track))}</div>
        <div class="tm-tt-row"><span class="lbl">Start</span><span class="val">${r.start ?? "—"}</span></div>
        <div class="tm-tt-row"><span class="lbl">Finish</span><span class="val"><span class="finish-badge ${cls}">${r.finish ?? "—"}</span></span></div>
        <div class="tm-tt-row"><span class="lbl">Race points</span><span class="val">${r.total ?? 0}</span></div>
        <div class="tm-tt-row"><span class="lbl">Cumulative</span><span class="val">${hit.getAttribute("data-cum")}</span></div>
      `;
      tip.innerHTML = html;
      tip.className = "tm-tip show";
      const rect = tip.getBoundingClientRect();
      let left = ev.clientX + 12, top = ev.clientY + 12;
      if (left + rect.width > window.innerWidth - 8) left = ev.clientX - rect.width - 12;
      if (top + rect.height > window.innerHeight - 8) top = ev.clientY - rect.height - 12;
      if (left < 8) left = 8;
      if (top < 8) top = 8;
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    }
    function hideChartTip(ev) {
      const hit = ev.target.closest(".profile-chart-hit");
      const going = ev.relatedTarget && ev.relatedTarget.closest ? ev.relatedTarget.closest(".profile-chart-hit") : null;
      if (hit && !going) tip.classList.remove("show");
    }
    if (svg._chartMove) svg.removeEventListener("mousemove", svg._chartMove);
    if (svg._chartOut)  svg.removeEventListener("mouseout",  svg._chartOut);
    svg._chartMove = showChartTip;
    svg._chartOut  = hideChartTip;
    svg.addEventListener("mousemove", svg._chartMove);
    svg.addEventListener("mouseout",  svg._chartOut);
  }
}

function paintProfileHeatStrip(rows) {
  const host = document.getElementById("profile-heat-strip");
  if (!host) return;
  host.innerHTML = rows.map(r => {
    if (r.dns) {
      return `<div class="profile-heat-cell heat-dns" data-round="${r.round}" data-dns="1"><span>—</span><span class="r">R${r.round}</span></div>`;
    }
    let cls = "heat-mid";
    if (r.finish === 1) cls = "heat-top";
    else if (r.finish <= 5) cls = "heat-up";
    else if (r.finish <= 10) cls = "heat-mid";
    else if (r.finish <= 20) cls = "heat-down";
    else cls = "heat-bot";
    return `<div class="profile-heat-cell ${cls}" data-round="${r.round}">${r.finish}<span class="r">R${r.round}</span></div>`;
  }).join("");

  // Hover wiring
  const tip = document.getElementById("metric-tooltip");
  if (!tip) return;
  const rowsByRound = {};
  rows.forEach(r => { rowsByRound[r.round] = r; });

  function showHeatTip(ev) {
    const cell = ev.target.closest(".profile-heat-cell");
    if (!cell || !host.contains(cell)) return;
    const round = parseInt(cell.getAttribute("data-round"), 10);
    const r = rowsByRound[round];
    if (!r) return;
    let html;
    const tt = escapeHTML(prettyTrack(r.track_code, r.track));
    if (r.dns) {
      html = `
        <div class="tm-tt-hdr">R${r.round} · ${tt}</div>
        <div class="tm-tt-row"><span class="lbl">Result</span><span class="val" style="color:var(--dim);font-style:italic;">Did not start</span></div>
      `;
    } else {
      let cls = "f-normal";
      if (r.finish === 1) cls = "f-win";
      else if (r.finish <= 5) cls = "f-t5";
      else if (r.finish <= 10) cls = "f-t10";
      else if (r.finish > 25) cls = "f-bad";
      html = `
        <div class="tm-tt-hdr">R${r.round} · ${tt}</div>
        <div class="tm-tt-row"><span class="lbl">Start</span><span class="val">${r.start ?? "—"}</span></div>
        <div class="tm-tt-row"><span class="lbl">Finish</span><span class="val"><span class="finish-badge ${cls}">${r.finish}</span></span></div>
        <div class="tm-tt-row"><span class="lbl">Race points</span><span class="val">${r.total ?? 0}</span></div>
      `;
    }
    tip.innerHTML = html;
    tip.className = "tm-tip show";
    const rect = tip.getBoundingClientRect();
    let left = ev.clientX + 12, top = ev.clientY + 12;
    if (left + rect.width > window.innerWidth - 8) left = ev.clientX - rect.width - 12;
    if (top + rect.height > window.innerHeight - 8) top = ev.clientY - rect.height - 12;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }
  function hideHeatTip(ev) {
    const cell = ev.target.closest(".profile-heat-cell");
    const going = ev.relatedTarget && ev.relatedTarget.closest ? ev.relatedTarget.closest(".profile-heat-cell") : null;
    if (cell && !going) tip.classList.remove("show");
  }
  if (host._heatMove) host.removeEventListener("mousemove", host._heatMove);
  if (host._heatOut)  host.removeEventListener("mouseout",  host._heatOut);
  host._heatMove = showHeatTip;
  host._heatOut  = hideHeatTip;
  host.addEventListener("mousemove", host._heatMove);
  host.addEventListener("mouseout",  host._heatOut);
}

function paintProfileRaceTable(rows, kind) {
  const tbody = document.getElementById("profile-race-tbody");
  if (!tbody) return;
  tbody.innerHTML = rows.map(r => {
    const trackDisplay = escapeHTML(prettyTrack(r.track_code, r.track));
    if (r.dns) {
      return `<tr style="opacity:0.4">
        <td class="rnd">R${r.round}</td>
        <td class="track"><strong>${escapeHTML(r.track_code || '')}</strong> · ${trackDisplay}</td>
        <td colspan="8" style="color:var(--dim);font-style:italic">DNS</td>
      </tr>`;
    }
    let cls = "f-normal";
    if (r.finish === 1) cls = "f-win";
    else if (r.finish <= 5) cls = "f-t5";
    else if (r.finish <= 10) cls = "f-t10";
    else if (r.finish > 25) cls = "f-bad";
    const driverNote = (kind === "owner" && r.driver) ? `<div class="race-driver-tag">${escapeHTML(r.driver)}</div>` : "";
    return `<tr>
      <td class="rnd">R${r.round}</td>
      <td class="track"><strong>${escapeHTML(r.track_code || '')}</strong> · ${trackDisplay}${driverNote}</td>
      <td style="color:var(--muted)">${escapeHTML(r.name || '')}</td>
      <td class="num">${r.start ?? '—'}</td>
      <td class="num"><span class="finish-badge ${cls}">${r.finish ?? '—'}</span></td>
      <td class="num">${r.s1 || '—'}</td>
      <td class="num">${r.s2 || '—'}</td>
      <td class="num">${r.fl || '—'}</td>
      <td class="num">${r.fin}</td>
      <td class="num" style="font-weight:700">${r.total}</td>
    </tr>`;
  }).join("");
}

// Compute per-track-type stats for a single entity's races.
// Returns an object keyed by track type code (super/short/inter/road) with
// stats: starts, wins, top5, top10, avgFinish, avgStagePts.
// Uncategorized tracks (null from trackType()) are excluded.
function computeTrackSplits(entity) {
  const buckets = { super: [], short: [], inter: [], road: [] };
  entity.races.forEach(r => {
    const t = trackType(r.track_code);
    if (t && buckets[t]) buckets[t].push(r);
  });

  const result = {};
  for (const [key, races] of Object.entries(buckets)) {
    const finishes = races.map(r => r.finish).filter(x => x != null);
    const starts = races.length;
    const stagePts = races.map(r => (r.s1 || 0) + (r.s2 || 0));
    result[key] = {
      starts,
      wins: finishes.filter(f => f === 1).length,
      top5: finishes.filter(f => f <= 5).length,
      top10: finishes.filter(f => f <= 10).length,
      avgFinish: finishes.length ? finishes.reduce((s, x) => s + x, 0) / finishes.length : null,
      avgStagePts: stagePts.length ? stagePts.reduce((s, x) => s + x, 0) / stagePts.length : null,
      bestFinish: finishes.length ? Math.min(...finishes) : null,
    };
  }
  return result;
}

function paintProfileTrackSplits(entity) {
  const host = document.getElementById("profile-track-splits");
  if (!host) return;
  const splits = computeTrackSplits(entity);
  const ORDER = ["super", "short", "inter", "road"];

  host.innerHTML = ORDER.map(key => {
    const s = splits[key];
    const label = TRACK_TYPE_LABELS[key];
    if (s.starts === 0) {
      return `<div class="track-split-card empty">
        <div class="track-split-head">
          <span class="track-split-label">${label}</span>
          <span class="track-split-count muted">0 races</span>
        </div>
        <div class="track-split-empty">— no races yet —</div>
      </div>`;
    }
    // Color avg finish: green for <=10, neutral 11-20, red 21+
    let avgCls = "";
    if (s.avgFinish != null) {
      if (s.avgFinish <= 10) avgCls = "hot";
      else if (s.avgFinish >= 21) avgCls = "cold";
    }
    return `<div class="track-split-card">
      <div class="track-split-head">
        <span class="track-split-label">${label}</span>
        <span class="track-split-count">${s.starts} race${s.starts === 1 ? "" : "s"}</span>
      </div>
      <div class="track-split-body">
        <div class="track-split-stat"><span class="k">Wins</span><span class="v ${s.wins > 0 ? 'hot' : ''}">${s.wins}</span></div>
        <div class="track-split-stat"><span class="k">Top 5</span><span class="v">${s.top5}</span></div>
        <div class="track-split-stat"><span class="k">Top 10</span><span class="v">${s.top10}</span></div>
        <div class="track-split-stat"><span class="k">Avg Fin</span><span class="v ${avgCls}">${s.avgFinish != null ? s.avgFinish.toFixed(1) : '—'}</span></div>
        <div class="track-split-stat"><span class="k">Stage pts/race</span><span class="v">${s.avgStagePts != null ? s.avgStagePts.toFixed(1) : '—'}</span></div>
        <div class="track-split-stat"><span class="k">Best</span><span class="v">P${s.bestFinish ?? '—'}</span></div>
      </div>
    </div>`;
  }).join("");
}

function paintProfileTeammates(entity) {
  const host = document.getElementById("profile-teammates");
  if (!host) return;
  const mates = profileTeammates(entity);
  if (mates.length === 0) {
    host.innerHTML = `<div class="muted" style="padding:10px;font-size:12px;">No teammates this season (single-car team).</div>`;
    return;
  }
  host.innerHTML = `
    <div class="profile-tm-header">
      <span></span><span>Teammate</span><span style="text-align:right;">Avg ΔFin</span><span style="text-align:right;">Beat</span>
    </div>
    ${mates.map(m => {
      const c = colorFor(STATE.series, m.car);
      const t = contrastTextFor(c);
      const cls = m.avgDelta > 0.5 ? "beat" : m.avgDelta < -0.5 ? "lost" : "tied";
      const sign = m.avgDelta > 0 ? "+" : "";
      return `<div class="profile-tm-row">
        <span class="tm-car" style="background:${c};color:${t}">${m.car}</span>
        <span class="tm-name"><a class="profile-link" href="#/profile/${slugify(m.driver)}">${escapeHTML(m.driver)}</a></span>
        <span class="profile-tm-delta ${cls}">${sign}${m.avgDelta.toFixed(1)}</span>
        <span class="profile-tm-record">${m.beat}-${m.lost}${m.tied > 0 ? "-" + m.tied : ""}</span>
      </div>`;
    }).join("")}
  `;
}

// ============================================================
// HEATMAP
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
    h.title = prettyTrack(r.track_code, r.track) + (r.name ? ` — ${r.name}` : "");
    grid.appendChild(h);
  });
  const totalHdr = document.createElement("div");
  totalHdr.className = "hm-header";
  totalHdr.textContent = "Total";
  grid.appendChild(totalHdr);

  drivers.forEach(d => {
    const carHex = colorFor(STATE.series, d.car_number);
    const txt = contrastTextFor(carHex);
    const label = document.createElement("a");
    label.className = "hm-label profile-link";
    label.href = profileHref(d);
    label.innerHTML = `<span class="car-tag" style="background:${carHex};color:${txt}">${d.car_number}</span><span>${escapeHTML(displayName(d))}</span>`;
    grid.appendChild(label);
    const byRound = {};
    d.races.forEach(r => { byRound[r.round] = r; });
    races.forEach(r => {
      const mine = byRound[r.round];
      const cell = document.createElement("div");
      cell.className = "hm-cell";
      const trackLabel = prettyTrack(r.track_code, r.track);
      if (!mine || mine.finish == null) {
        cell.textContent = "·";
        cell.style.color = "var(--dim)";
        cell.title = `R${r.round} · ${trackLabel} — DNS`;
      } else {
        const f = mine.finish;
        cell.textContent = f;
        cell.style.background = heatmapColor(f);
        cell.style.color = heatmapText(f);
        cell.title = `R${r.round} · ${trackLabel} · ${d.driver} — P${f}`;
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

function heatmapColor(finish) {
  if (finish == null) return "transparent";
  const clamp = (a, lo, hi) => Math.max(lo, Math.min(hi, a));
  const t = clamp(finish, 1, 40);
  if (t <= 20) {
    const k = 1 - (t - 1) / 19;
    const a = 0.18 + 0.57 * k;
    return `rgba(50, 230, 100, ${a.toFixed(3)})`;
  } else {
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
// STANDINGS
// ============================================================
function renderStandings() {
  const table = document.getElementById("standings-table");
  if (!STATE.data) return;

  const races = racesSorted();
  const lastRaceRound = races.length ? races[races.length - 1].round : null;
  const previousCutoff = lastRaceRound ? lastRaceRound - 1 : null;

  const currentMap = pointsMapThroughRound(lastRaceRound);
  const currentRows = rankingRowsFrom(currentMap);

  const previousMap = previousCutoff && previousCutoff >= 1
    ? pointsMapThroughRound(previousCutoff)
    : new Map();
  const previousRank = new Map();
  Array.from(previousMap.entries())
    .sort((a, b) => b[1].total - a[1].total)
    .forEach(([k], i) => previousRank.set(k, i + 1));

  let rows = currentRows.map((r, i) => {
    const currRank = i + 1;
    const prevRank = previousRank.has(r.key) ? previousRank.get(r.key) : null;
    const posChange = prevRank != null ? (prevRank - currRank) : null;
    return { ...r, currRank, prevRank, posChange };
  });

  const sk = STATE.standings.sortKey;
  const sd = STATE.standings.sortDir;
  if (sk && sk !== "total") {
    rows = sortRows(rows, sk, sd);
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
    const profileSlug = (STATE.entity === "owner") ? r.car_number : slugify(r.primaryDriver);
    const profileKind = (STATE.entity === "owner") ? "car" : "profile";
    return `<tr>
      <td class="rank-cell">${r.currRank}${pcPill}</td>
      <td><a class="driver-cell profile-link" href="#/${profileKind}/${profileSlug}">
        <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
        <span>${escapeHTML(r.displayLabel)}</span>
      </a></td>
      <td>${teamPill}</td>
      <td class="num">${r.starts}</td>
      <td class="num">${r.wins}</td>
      <td class="num">${r.top5}</td>
      <td class="num">${r.top10}</td>
      <td class="num">${r.avgFinish != null ? r.avgFinish.toFixed(1) : "—"}</td>
      <td class="num">${r.sumS1}</td>
      <td class="num">${r.sumS2}</td>
      <td class="num">${r.sumFL}</td>
      <td class="num total-col">${r.total}</td>
    </tr>`;
  }).join("");

  const th = (key, label, numeric) => {
    const active = STATE.standings.sortKey === key;
    const cls = `sortable ${numeric ? "num" : ""} ${active ? "sort-" + STATE.standings.sortDir : ""}`.trim();
    const arrow = active ? (STATE.standings.sortDir === "asc" ? "▲" : "▼") : "↕";
    return `<th class="${cls}" data-sort="${key}">${label}<span class="sort-arrow">${arrow}</span></th>`;
  };
  // Special header with a tooltip indicator for the FL column (data is incomplete)
  const thFL = () => {
    const key = "sumFL";
    const active = STATE.standings.sortKey === key;
    const cls = `sortable num has-info ${active ? "sort-" + STATE.standings.sortDir : ""}`.trim();
    const arrow = active ? (STATE.standings.sortDir === "asc" ? "▲" : "▼") : "↕";
    const tip = "FL data incomplete — being refined. The scraper's fastest-lap inference is imperfect and often can't uniquely identify the FL driver, so many races show 0 here even when a real FL bonus was awarded.";
    return `<th class="${cls}" data-sort="${key}" title="${escapeHTML(tip)}">FL<span class="sort-arrow">${arrow}</span></th>`;
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
        ${thFL()}
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

function pointsMapThroughRound(maxRound) {
  const map = new Map();
  (STATE.data?.races || []).forEach(r => {
    if (r.round > maxRound) return;
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      const key = (STATE.entity === "owner") ? `#${d.car_number}` : d.driver;
      if (!map.has(key)) {
        map.set(key, {
          key, driver: d.driver, driversSet: new Set(),
          car_number: d.car_number, team: d.team,
          total: 0, starts: 0, wins: 0, top5: 0, top10: 0,
          finishes: [],
          sumS1: 0, sumS2: 0, sumFin: 0, sumFL: 0,
        });
      }
      const e = map.get(key);
      e.driversSet.add(d.driver);
      e.driver = d.driver;
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
    const primaryDriver = e.driver;  // keep the original driver name for slugging
    const displayLabel = (STATE.entity === "owner")
      ? (driversArr.length > 1
          ? `#${e.car_number} · ${e.driver} +${driversArr.length - 1}`
          : `#${e.car_number} · ${e.driver}`)
      : e.driver;
    return { ...e, avgFinish, displayLabel, primaryDriver, driver: displayLabel };
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

boot();
