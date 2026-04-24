// =========================================================================
// NASCAR Points Analysis — app.js
// Loads data/points_<year>.json + data/colors.json, renders 6 views,
// handles routing, series/season/entity switching, filters, sorts.
// =========================================================================

const STATE = {
  series: "NCS",
  season: 2026,
  view: "arc",
  // Identity model: the app is car-centric. Every primary row is a car
  // (#car_number). If multiple drivers drove that car in a season, the UI
  // surfaces them via an "i" tooltip next to the car's primary driver name.
  // `entity` is kept as a constant for backward compatibility with code paths
  // that still read it; do not mutate.
  entity: "owner",
  // Time cursor: when set, all data views behave as if the season ended at this
  // round number. null = "latest", the default. Reset to null on season change.
  throughRound: null,
  data: null,
  colors: null,
  driverBios: null,
  seasonsAvailable: [],
  form: { window: "5", search: "", ftOnly: true, sortKey: null, sortDir: "desc" },
  arc: { selected: new Set(), ftOnly: true, metric: "points", teamFilter: null },
  breakdown: { drivers: [], ftOnly: true, teamFilter: null },
  trajectory: { mode: "season", show: "all", labels: "top12", tracks: "all",
                selected: new Set(), seasons: new Set(), teamFilter: null },
  teammates: { metric: "fin", ftOnly: true },
  profile: { kind: null, slug: null },
  standings: { sortKey: "total", sortDir: "desc" },
  // Table-split chart: the car whose arc is shown next to Trending/Standings.
  // Null = first row by default. Set when user clicks any row in the table.
  selectedCar: null,
};

const SERIES_TO_KEY = { NCS: "W", NOS: "B", NTS: "C" };
const FALLBACK_COLOR = "#9ca3af";
const VIEWS = ["form", "arc", "breakdown", "trajectory", "teammates", "heatmap", "standings", "playoffs", "profile"];

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
  populateRacePicker();
  renderTimeCursorBanner();
  document.getElementById("time-cursor-reset")?.addEventListener("click", () => {
    STATE.throughRound = null;
    populateRacePicker();   // refresh selected state
    renderTimeCursorBanner();
    render();
  });
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
    // Remember where we came from so the profile's Back link returns there.
    // Only update the memory if the PREVIOUS view wasn't also a profile — otherwise
    // profile→profile navigation would overwrite the real back target.
    if (STATE.view && STATE.view !== "profile") {
      STATE.prevView = STATE.view;
    }
    STATE.view = "profile";
    STATE.profile = {
      kind: view,              // "profile" (driver) or "car"
      slug: h[1] || null,
    };
    return;
  }
  STATE.view = VIEWS.includes(view) ? view : "arc";  // arc is the landing tab
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

// ============================================================
// MULTI-SEASON CACHE (used by Stage Analysis for cross-year views)
// Keyed by year → { [seriesCode]: seriesBlock }
// ============================================================
const SEASON_CACHE = {};

async function loadSeasonIntoCache(year) {
  // Returns the full payload (all series) for a year. Cached after first hit.
  if (SEASON_CACHE[year]) return SEASON_CACHE[year];
  const urls = [`data/points_${year}.json`, `data/points.json`];
  for (const u of urls) {
    try {
      const r = await fetch(u);
      if (!r.ok) continue;
      const payload = await r.json();
      SEASON_CACHE[year] = payload.series || {};
      return SEASON_CACHE[year];
    } catch (e) { /* try next */ }
  }
  return null;
}

// Fetches every year in STATE.trajectory.seasons that isn't already cached.
// Resolves when all are loaded.
async function ensureTrajectorySeasonsLoaded() {
  const years = [...STATE.trajectory.seasons];
  await Promise.all(years.map(y => loadSeasonIntoCache(y)));
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
      STATE.throughRound = null;  // cursor is series-specific, reset on series change
      STATE.arc.selected.clear();
      STATE.breakdown.drivers = [];
      STATE.trajectory.selected.clear();
      STATE.trajectory.seasons.clear();
      await loadCurrentData();
      populateRacePicker();
      renderTimeCursorBanner();
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
        if (group === "arc-metric") STATE.arc.metric = b.dataset.val;
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

  // Trajectory toggles — exclude traj-seasons, which is a multi-select group
  // managed by renderTrajectorySeasonChips() (different selection semantics
  // and it needs to re-wire on every render as data loads).
  document.querySelectorAll("#view-trajectory .toggle-group").forEach(g => {
    const group = g.dataset.group;
    if (group === "traj-seasons") return;
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

  // Takeover back button returns to dashboard home (default = Trending tab)
  // Profile back: return to the tab we were on before entering the profile.
  // Falls back to Season Arc (the default landing tab) if nothing remembered.
  document.getElementById("takeover-back")?.addEventListener("click", (e) => {
    e.preventDefault();
    const prev = STATE.prevView && STATE.prevView !== "profile" ? STATE.prevView : "arc";
    location.hash = `#/${prev}`;
  });
  // Playoffs back: return to the dashboard default
  document.getElementById("playoffs-back")?.addEventListener("click", (e) => {
    e.preventDefault();
    location.hash = "#/";
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

  document.getElementById("traj-clear")?.addEventListener("click", () => {
    STATE.trajectory.selected.clear();
    renderTrajectory();
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
    STATE.throughRound = null;  // reset cursor on season change
    STATE.trajectory.selected.clear();
    STATE.trajectory.seasons.clear();
    await loadCurrentData();
    populateRacePicker();
    renderTimeCursorBanner();
    render();
  });
}

// ============================================================
// TIME CURSOR (race-picker + banner)
// ------------------------------------------------------------
// Populates the race-picker dropdown with every race in the loaded season,
// plus a "Latest" option that unsets the cursor. Also paints the banner
// that appears when a non-latest round is selected.
// ============================================================
function populateRacePicker() {
  const sel = document.getElementById("race-picker");
  if (!sel) return;
  const races = allRacesSorted();
  if (!races.length) { sel.innerHTML = ""; return; }
  // The cursor null state means "latest" — which is literally the last race.
  // So we just select the last race when cursor is null, and let the user
  // see they're on the latest race rather than showing a separate option.
  const effectiveRound = STATE.throughRound != null ? STATE.throughRound : races[races.length - 1].round;
  sel.innerHTML = races.map(r => {
    const trackName = prettyTrack(r.track_code, r.track) || "—";
    const s = (r.round === effectiveRound) ? "selected" : "";
    return `<option value="${r.round}" ${s}>R${r.round} · ${escapeHTML(trackName)}</option>`;
  }).join("");
  if (!sel._wired) {
    sel.addEventListener("change", () => {
      const picked = parseInt(sel.value, 10);
      // Picking the last scheduled race = "back to latest" = null cursor.
      // Picking any other race = set cursor to that round.
      const lastRound = allRacesSorted().slice(-1)[0]?.round;
      STATE.throughRound = (picked === lastRound) ? null : picked;
      renderTimeCursorBanner();
      render();
    });
    sel._wired = true;
  }
}

function renderTimeCursorBanner() {
  const banner = document.getElementById("time-cursor-banner");
  const text = document.getElementById("time-cursor-banner-text");
  if (!banner || !text) return;
  if (STATE.throughRound == null) {
    banner.hidden = true;
    return;
  }
  const races = allRacesSorted();
  const race = races.find(r => r.round === STATE.throughRound);
  const total = races.length;
  const trackLabel = race ? prettyTrack(race.track_code, race.track) : "";
  text.innerHTML = `Viewing <strong>${STATE.season} ${STATE.series}</strong> through <strong>R${STATE.throughRound}${trackLabel ? " · " + escapeHTML(trackLabel) : ""}</strong> of ${total} — historical snapshot`;
  banner.hidden = false;
}

// ============================================================
// RENDER
// ============================================================
// Views that live as tabs inside the center panel.
const TAB_VIEWS = ["arc", "form", "breakdown", "trajectory", "teammates", "heatmap", "standings"];
// Views that take over the whole page (hide dashboard). Only playoffs now —
// profile is a center-column takeover that keeps the side panels visible.
const TAKEOVER_VIEWS = ["playoffs"];

function render() {
  const dashboard = document.getElementById("dashboard");
  const takeover = document.getElementById("takeover");
  const inTakeover = TAKEOVER_VIEWS.includes(STATE.view);
  const inProfile  = STATE.view === "profile";

  if (dashboard) dashboard.hidden = inTakeover;
  if (takeover) takeover.hidden = !inTakeover;

  // Takeover section visibility (only playoffs lives here now)
  const pElem = document.getElementById("view-playoffs");
  if (pElem) pElem.hidden = (STATE.view !== "playoffs");

  // Profile takeover — sits inside the center column, hides tab-body when active
  const profileTakeover = document.getElementById("profile-takeover");
  const tabBody = document.getElementById("tab-body");
  if (profileTakeover) profileTakeover.hidden = !inProfile;
  if (tabBody) tabBody.hidden = inProfile;

  // Tab-panel visibility. Default to "arc" when the URL doesn't point to a
  // specific tab view (Season Arc is the new landing tab).
  const activeTab = TAB_VIEWS.includes(STATE.view) ? STATE.view : "arc";
  TAB_VIEWS.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.hidden = (v !== activeTab);
  });

  // Tab button active-state — dim when profile is active (no tab is "really" on)
  document.querySelectorAll(".dash-tab").forEach(a => {
    a.classList.toggle("active", !inProfile && a.dataset.view === activeTab);
  });

  // ---- Always-on dashboard side panels (when not in full-page takeover) ----
  if (!inTakeover) {
    renderMetricBar();
    renderStandingsMini();
    renderFormMini();

    if (inProfile) {
      renderProfile();
    } else {
      // Render the active tab's content
      switch (activeTab) {
        case "arc":        renderArc(); break;
        case "form":       renderFormTable(); break;
        case "breakdown":  renderBreakdown(); break;
        case "trajectory": renderTrajectory(); break;
        case "teammates":  renderTeammates(); break;
        case "heatmap":    renderHeatmap(); break;
        case "standings":  renderStandings(); break;
      }
    }
  } else {
    renderMetricBar();
    if (STATE.view === "playoffs") renderPlayoffs();
  }
}

// ============================================================
// DERIVED METRICS
// ============================================================
// Returns races sorted by round, OPTIONALLY filtered by the time cursor.
// When STATE.throughRound is null (default), returns all scraped races.
// When set, clips to races at or before that round — every downstream view
// (standings, arc, breakdown, trajectory, playoffs, heatmap, trending)
// automatically becomes a point-in-time snapshot because they all read from here.
function racesSorted() {
  const all = (STATE.data?.races || [])
    .slice()
    .sort((a, b) => (a.round || 0) - (b.round || 0));
  if (STATE.throughRound != null) {
    return all.filter(r => (r.round || 0) <= STATE.throughRound);
  }
  return all;
}

// Unfiltered access — used by the race picker, which needs to show every race
// scheduled (including ones beyond the cursor, so users can navigate forward).
function allRacesSorted() {
  return (STATE.data?.races || [])
    .slice()
    .sort((a, b) => (a.round || 0) - (b.round || 0));
}

function allEntities() {
  return entitiesFromRaces(racesSorted());
}

// Pure helper: build the entity map from any races array. Used by allEntities
// (single-season, the default) and by trajectoryEntities() (multi-season).
function entitiesFromRaces(races) {
  const seriesKey = SERIES_TO_KEY[STATE.series];
  const map = new Map();
  races.forEach(r => {
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      // Car-centric: key is always car number. Multiple drivers across a
      // season roll up into the same entity row and get surfaced via the
      // "i" tooltip in each view.
      const key = `#${d.car_number}`;

      // Two-tier team code resolution (palette no longer stores team codes):
      // 1. d.team_code from scraper — authoritative, built from current race data
      // 2. Fallback: owner parse from team string (for pre-upgrade historical data)
      const teamCode = d.team_code
        || teamCodeFromName(d.team, seriesKey, d.car_number)
        || null;

      if (!map.has(key)) {
        map.set(key, {
          key,
          driver: d.driver,
          driversSet: new Set(),
          driverStarts: {},   // driver name → number of starts in this car
          car_number: d.car_number,
          team: d.team,
          team_code: teamCode,
          manufacturer: d.manufacturer,
          races: [],
        });
      }
      const e = map.get(key);
      e.driversSet.add(d.driver);
      e.driverStarts[d.driver] = (e.driverStarts[d.driver] || 0) + 1;
      e.driver = d.driver;  // keeps the "most recent driver seen" for legacy callers
      e.team = d.team;
      if (teamCode) e.team_code = teamCode;
      e.manufacturer = d.manufacturer || e.manufacturer;
      e.races.push({
        round: r.round,
        season: r.season,   // set by trajectoryEntities for multi-year; undefined for single-season
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
  // Finalize each entity: sort drivers by starts desc, derive primary + co-drivers.
  return Array.from(map.values()).map(e => {
    const driversByStarts = Object.entries(e.driverStarts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, starts]) => ({ name, starts }));
    const primaryDriver = driversByStarts[0] ? driversByStarts[0].name : e.driver;
    const coDrivers = driversByStarts.slice(1);  // [{name, starts}, ...]
    return {
      ...e,
      drivers: driversByStarts.map(d => d.name),   // legacy field: ordered driver list
      driversByStarts,                              // [{name, starts}] ordered most → least
      primaryDriver,                                // headline driver for this car
      coDrivers,                                    // non-primary drivers, with their start counts
      driver: primaryDriver,                        // the main "driver" label is now the primary
    };
  });
}

// Builds entities across the seasons selected in the Stage Analysis view.
// When no seasons are selected, falls back to the current single season.
// Returns { entities, totalRaces, seasonsUsed } — totalRaces is the combined
// race count across all selected seasons (used for the 90% full-time threshold).
function trajectoryEntities() {
  const selected = [...STATE.trajectory.seasons].sort();
  const sCode = STATE.series;

  // Fast path: no multi-season selection → reuse current single-season data
  if (selected.length === 0 ||
      (selected.length === 1 && selected[0] === STATE.season)) {
    return {
      entities: allEntities(),
      totalRaces: racesSorted().length,
      seasonsUsed: [STATE.season],
    };
  }

  // Multi-season: concatenate races from the cache
  const combined = [];
  selected.forEach(year => {
    const seriesBlock = SEASON_CACHE[year] && SEASON_CACHE[year][sCode];
    if (!seriesBlock) return;
    (seriesBlock.races || []).forEach(r => {
      // Tag each race with its season so we can dedupe / display per-year later
      combined.push({ ...r, season: year });
    });
  });
  // Sort combined races chronologically: by year, then by round (within year)
  combined.sort((a, b) => (a.season - b.season) || (a.round - b.round));
  return {
    entities: entitiesFromRaces(combined),
    totalRaces: combined.length,
    seasonsUsed: selected,
  };
}

function allDrivers() { return allEntities(); }

function displayName(entity) {
  if (entity.drivers && entity.drivers.length > 1) {
    return `#${entity.car_number} · ${entity.primaryDriver} +${entity.drivers.length - 1}`;
  }
  return `#${entity.car_number} · ${entity.primaryDriver || entity.driver}`;
}

function entityKey(entity) {
  return `#${entity.car_number}`;
}

// Returns the hash URL for this entity's profile page.
// Car-centric app: every profile is a car profile.
function profileHref(entity) {
  return `#/car/${entity.car_number}`;
}

function computeSeasonTotals() {
  const entities = allEntities();
  return entities.map(d => {
    const total = d.races.reduce((s, r) => s + r.total, 0);
    const avgFinish = mean(d.races.map(r => r.finish).filter(x => x != null));
    return { ...d, total, avgFinish };
  }).sort((a, b) => b.total - a.total);
}

// ============================================================
// CO-DRIVER BADGE — shared across every view
// ------------------------------------------------------------
// A car that had multiple drivers in a season (substitutes, driver changes,
// one-off relief) gets a small "ⁱ" badge next to its primary driver's name.
// Hovering the badge reveals all drivers who drove the car, sorted by starts.
// Data source: entity.driversByStarts, set by entitiesFromRaces().
// ============================================================

// Returns the HTML for the badge, or "" if the car had a single driver.
// Pass-through: entity must have `driversByStarts` (or `coDrivers`) populated.
function renderCoDriverBadge(entity) {
  const list = entity && entity.driversByStarts;
  if (!Array.isArray(list) || list.length < 2) return "";
  const car = entity.car_number || "";
  // The badge uses data-car so one wire-up call can find and attach to every
  // badge on the page at once, regardless of which view rendered it.
  return `<span class="co-badge" data-car="${escapeHTML(String(car))}" title="Shared car — hover for drivers">i</span>`;
}

// Scans a host element for all .co-badge nodes and wires up a hover tooltip
// that lists every driver who drove the car (with start counts, primary
// highlighted). Safe to call multiple times — it re-binds only the nodes
// inside `host`. Data comes from the current allEntities() snapshot, keyed
// by car number.
function wireCoDriverBadges(host) {
  if (!host) return;
  const tip = document.getElementById("metric-tooltip");
  if (!tip) return;
  // Build a lookup of car_number → entity (for the active dataset).
  const byCar = new Map();
  allEntities().forEach(e => byCar.set(String(e.car_number), e));

  host.querySelectorAll(".co-badge").forEach(el => {
    const car = el.getAttribute("data-car");
    const ent = byCar.get(String(car));
    if (!ent || !Array.isArray(ent.driversByStarts) || ent.driversByStarts.length < 2) return;

    const rowsHTML = ent.driversByStarts.map((dc, i) => {
      const cls = i === 0 ? "primary" : "";
      const s = dc.starts || 0;
      return `<div class="co-tip-row ${cls}"><span>${escapeHTML(dc.name)}</span><span class="n">${s} race${s === 1 ? "" : "s"}</span></div>`;
    }).join("");
    const totalRaces = ent.races ? ent.races.length : 0;
    const html = `<div class="co-tip-hdr">Shared Car #${escapeHTML(String(car))} · ${totalRaces} races total</div>${rowsHTML}`;

    const show = (evt) => {
      tip.innerHTML = html;
      tip.className = "";
      ["show", "co-tip"].forEach(c => tip.classList.add(c));
      const rect = tip.getBoundingClientRect();
      let left = evt.clientX + 12, top = evt.clientY + 12;
      if (left + rect.width  > window.innerWidth  - 8) left = evt.clientX - rect.width  - 12;
      if (top  + rect.height > window.innerHeight - 8) top  = evt.clientY - rect.height - 12;
      if (left < 8) left = 8;
      if (top  < 8) top  = 8;
      tip.style.left = `${left}px`;
      tip.style.top  = `${top}px`;
    };
    const hide = () => tip.classList.remove("show");

    el.addEventListener("mouseenter", show);
    el.addEventListener("mousemove",  show);
    el.addEventListener("mouseleave", hide);
    // Clicking the badge keeps the tooltip open briefly for mobile / tap users.
    // Simpler than a full popover: on tap, show, then hide after 4s if no move.
    el.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      show(e);
      clearTimeout(el._coTimer);
      el._coTimer = setTimeout(hide, 4000);
    });
  });
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
  if (totalRaces <= 0) return false;
  // A driver is "full-time" if they've run at least 90% of the season's races.
  // This tolerates missed races due to suspension, injury, or DNS while still
  // excluding part-time entrants, one-race substitutes, and crossover drivers.
  // Early in the season (few races run), we still require all of them — a
  // driver at 4/5 is fine (80% >= 90% is false, so we need the small-n guard
  // below). With fewer than 10 races run, be strict: need to have run them all
  // minus one.
  if (totalRaces < 10) return entity.races.length >= totalRaces - 1;
  return entity.races.length >= Math.ceil(totalRaces * 0.9);
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
// Team org color — looked up by team code, not car number. This is the
// single source of truth: one team == one color, any series, any season.
// Fall back to the JS-side constants (TEAM_FULL_NAMES / TEAM_ALLIANCE) for
// metadata if colors.json doesn't have the team entry yet.
function orgColorForTeam(teamCode) {
  if (!teamCode) return null;
  const teams = STATE.colors && STATE.colors.teams;
  if (teams && teams[teamCode] && teams[teamCode].org) return teams[teamCode].org;
  return null;
}
// Back-compat shim: some call sites still pass (series, carNumber). They all
// ultimately want the team color, so resolve car -> team_code -> org via the
// entity map if possible. Prefer callers pass team_code directly.
function orgColorFor(series, carNumber) {
  // Find the entity for this car in the current series and use its team_code.
  if (!STATE.data) return null;
  for (const race of (STATE.data.races || [])) {
    for (const d of (race.results || [])) {
      if (d.car_number === carNumber && d.team_code) {
        return orgColorForTeam(d.team_code);
      }
    }
  }
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
    <div class="metric" data-tip="${escapeHTML(raceTip)}"><span class="k">${STATE.throughRound != null ? "As Of" : "Last Race"}</span>
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
    const spark = sparkSVG(d.lastFinishes, carHex, 58, 18);
    const trend = trendArrow(d.deltaR);
    const ratingCls = d.deltaR == null ? "" : d.deltaR > 6 ? "hot" : d.deltaR < -6 ? "cold" : "";
    const teamPill = renderTeamPill(d.team_code);
    return `<tr data-car-key="${escapeHTML(entityKey(d))}">
      <td class="num" style="color: var(--dim)">${i + 1}</td>
      <td><a class="driver-cell profile-link" href="${profileHref(d)}">
        <span class="car-tag" style="background:${carHex};color:${txtCol}">${d.car_number}</span>
        <span>${escapeHTML(displayName(d))}</span>
        ${renderCoDriverBadge(d)}
      </a></td>
      <td>${teamPill}</td>
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

  wireCoDriverBadges(card);
  wireTableSplitSelection(card, "selected-car-svg", "selected-car-head");

  const sub = document.getElementById("form-sub");
  const ftNote = STATE.form.ftOnly ? "full-time only" : "all entrants";
  sub.textContent = `${decorated.length} cars · ${ftNote} · window: ${STATE.form.window === "season" ? "full season" : `last ${STATE.form.window} races`}`;
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
// Owner string → 3-letter team code. Kept in sync with scripts/team_codes.py.
// When scraper produces `team_code` directly on the race record, that takes
// precedence; this is the fallback for historical data scraped before the
// scraper-side resolution was added.
const OWNER_TO_TEAM_CODE = {
  // Cup / Xfinity / Truck primary teams
  "Joe Gibbs":                "JGR",
  "Rick Hendrick":            "HMS",
  "Roger Penske":             "PEN",
  "Wood Brothers":            "WBR",
  "23XI Racing":              "23XI",
  "Richard Childress":        "RCR",
  "Jack Roush":               "RFK",
  "Trackhouse Racing":        "THR",
  "Legacy Motor Club":        "LMC",
  "Spire Motorsports":        "SPI",
  "Matthew Kaulig":           "KR",
  "HYAK Motorsports":         "HYAK",
  "Rick Ware":                "RWR",
  "Gene Haas":                "HAAS",
  "Tony Stewart":             "SHR",
  "Stewart-Haas":             "SHR",
  "Stewart-Haas Racing":      "SHR",
  "Stewart Haas":             "SHR",
  "Stewart Haas Racing":      "SHR",
  "Greg Zipadelli":           "SHR",
  "Joe Custer":               "SHR",
  "JR Motorsports":           "JRM",
  "Bob Jenkins":              "FRM",
  "Carl Long":                "MBM",
  "B.J. McLeod":              "BJM",
  // Xfinity-only
  "Jeremy Clements":          "JCR",
  "Jimmy Means":              "JMR",
  "Jordan Anderson":          "JAR",
  "Mike Harmon":              "MHR",
  "Mario Gosselin":           "DGM",
  "Sam Hunt":                 "SHR",
  "Joey Gase Motorsports  With Sc": "JGM",
  "Joey Gase Motorsports":    "JGM",
  "Bobby Dotter":             "SSG",
  "Stanton Barrett":          "BAR",
  "Scott Borchetta":          "BMR",
  "Randy Young":              "RSS",
  "Tommy Joe Martins":        "AMR",
  "Chris Hettinger":          "HET",
  "Dan Pardus":               "PAR",
  "Don Sackett":              "VAV",
  "Rod Sieg":                 "SIE",
  "Tim Self":                 "SEL",
  "Wayne Peterson":           "WPR",
  // Truck-only
  "Kyle Busch":               "KBM",
  "Bill McAnally":            "BMA",
  "David Gilliland":          "TRICON",
  "Al Niece":                 "AMR",
  "Duke Thorson":             "TTM",
  "Kevin Cywinski":           "MHR",
  "Rackley W.A.R.":           "RWM",
  "Codie Rohrbaugh":          "CR7",
  "Mike Curb":                "HAT",
  "Charlie Henderson":        "CHR",
  "Chris Larsen":             "HLR",
  "Josh Reaume":              "CFR",
  "Johnny Gray":              "JGR2",
  "Terry Carroll":            "TCM",
  "Larry Berg":               "LBM",
  "Timmy Hill":               "HLL",
  "Freedom Racing":            "FRR",
};

// Rare unparseable rows — fallback by (series_code, car_number)
const CAR_FALLBACK_CODES = {
  "C|93": "CST", "C|69": "MCR", "C|95": "BBM", "W|44": "NYR",
};

function teamCodeFromName(team, seriesCode, carNumber) {
  if (!team) {
    // Still try the car-number fallback when sponsor is missing
    return seriesCode && carNumber ? (CAR_FALLBACK_CODES[seriesCode + "|" + carNumber] || "") : "";
  }
  // Format 1: "Sponsor Name ( Owner Name )"
  const m = team.match(/\(\s*([^)]+?)\s*\)\s*$/);
  let owner = null;
  if (m) {
    owner = m[1].trim();
  } else {
    // Format 2: bare owner name
    const bare = team.trim();
    if (OWNER_TO_TEAM_CODE[bare]) owner = bare;
  }
  if (owner && OWNER_TO_TEAM_CODE[owner]) return OWNER_TO_TEAM_CODE[owner];
  // Format 3: substring match — RR sometimes omits the parens or the sponsor
  // prefix is embedded weirdly. Scan the team string for any known owner.
  const lowerTeam = team.toLowerCase();
  for (const knownOwner of Object.keys(OWNER_TO_TEAM_CODE)) {
    if (lowerTeam.includes(knownOwner.toLowerCase())) {
      return OWNER_TO_TEAM_CODE[knownOwner];
    }
  }
  // Fallback by car number
  if (seriesCode && carNumber) {
    const fb = CAR_FALLBACK_CODES[seriesCode + "|" + carNumber];
    if (fb) return fb;
  }
  return "";
}

// Readable team pill — takes the pre-resolved team code from the entity
// (entity.team_code, produced by the scraper or the owner-parse fallback)
// and looks up the team's brand color from colors.json's team-keyed section.
// `seriesAndCar` kept as a trailing arg for back-compat with old call sites;
// it's now unused for color resolution.
function renderTeamPill(teamCode, _seriesUnused, _carUnused) {
  if (!teamCode) return `<span class="team-pill fallback">—</span>`;
  const orgHex = orgColorForTeam(teamCode);
  if (orgHex) {
    const textCol = contrastTextFor(orgHex);
    return `<span class="team-pill" style="background:${orgHex};color:${textCol}">${escapeHTML(teamCode)}</span>`;
  }
  return `<span class="team-pill fallback">${escapeHTML(teamCode)}</span>`;
}

// ============================================================
// DRIVER GRID (Arc + Breakdown picker)
// ============================================================
// mode: "multi" (arc) | "single" (breakdown)
// filter: ftOnly flag
// onSelect: (entity) => void
// isSelected: (entity) => boolean
// Renders team pills (optional) + driver pills.
// onSelect(entity) — driver pill click handler
// isSelected(entity) — returns true if entity is currently selected
// onTeamSelect(teamDrivers) — optional: if present, clicking team pill will call this
//   with an array of sorted entities for that team. If omitted, no team row is shown.
function renderDriverGrid(hostId, mode, ftOnly, onSelect, isSelected, onTeamSelect, teamFilter) {
  const host = document.getElementById(hostId);
  if (!host) return;
  let entities = allEntities();
  if (ftOnly) entities = entities.filter(isFullTime);
  if (teamFilter) entities = entities.filter(e => e.team_code === teamFilter);
  // sort by current season points desc so the big names float to top
  entities = entities.map(e => ({
    ...e, total: e.races.reduce((s, r) => s + r.total, 0),
  })).sort((a, b) => b.total - a.total);

  // -------- Team-pill row --------
  // Was driver-mode-only. In car-mode, team grouping is less meaningful at the
  // picker level (each car already carries its own team via the car-number
  // color), so we skip it and just render the car grid.
  const teamRowHTML = "";

  const driverPillsHTML = entities.map(e => {
    const carHex = colorFor(STATE.series, e.car_number);
    const txt = contrastTextFor(carHex);
    const sel = isSelected(e) ? "selected" : "";
    // car# + primary driver's last name; append "+N" if the car had co-drivers
    const lastName = (e.primaryDriver || e.driver || "").split(/\s+/).slice(-1)[0];
    const coCount = (e.coDrivers || []).length;
    const label = coCount > 0 ? `${lastName} +${coCount}` : lastName;
    return `<div class="driver-pill ${sel}" data-key="${escapeHTML(entityKey(e))}" title="${escapeHTML(displayName(e))} — click to toggle, ↗ to open profile">
      <span class="dp-num" style="background:${carHex};color:${txt}">${e.car_number}</span>
      <span class="dp-name">${escapeHTML(label)}</span>
      ${renderCoDriverBadge(e)}
      <a class="dp-jump profile-link" href="${profileHref(e)}" title="Open ${escapeHTML(displayName(e))} profile" aria-label="Open profile">↗</a>
    </div>`;
  }).join("");

  host.innerHTML = teamRowHTML + `<div class="driver-grid">${driverPillsHTML}</div>`;

  // Driver pill click
  host.querySelectorAll(".driver-pill").forEach(el => {
    el.addEventListener("click", (ev) => {
      if (ev.target.closest(".dp-jump")) return;
      const key = el.dataset.key;
      const e = entities.find(x => entityKey(x) === key);
      if (!e) return;
      onSelect(e);
    });
  });

  // Team pill click — invokes onTeamSelect with the sorted array of team drivers
  if (onTeamSelect) {
    host.querySelectorAll(".team-pill-btn").forEach(el => {
      el.addEventListener("click", () => {
        const teamKey = el.dataset.team;
        // Rebuild the team's driver list from current entities using resolved team_code
        const teamDrivers = entities.filter(e => {
          const rawCode = e.team_code;
          if (!rawCode) return false;
          return (TEAM_ALLIANCE[rawCode] || rawCode) === teamKey;
        });
        teamDrivers.sort((a, b) => b.total - a.total);
        onTeamSelect(teamDrivers);
      });
    });
  }

  wireCoDriverBadges(host);
}

// ============================================================
// SEASON CUMULATIVE (was Season Arc)
// ============================================================
function renderArc() {
  const svg = document.getElementById("arc-svg");
  if (!STATE.data) return;

  renderTeamFilter("arc-team-filter", "arc", () => renderArc());

  const races = racesSorted();
  if (races.length === 0) {
    svg.innerHTML = `<text x="20" y="40" fill="var(--muted)">No races loaded.</text>`;
    renderArcGrid();
    return;
  }

  const entities = applyTeamFilter(allEntities(), "arc");
  const roundsPresent = races.map(r => r.round);

  // Compute per-round cumulative points for every entity
  const cumByEntity = entities.map(d => {
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

  // If metric is 'position', convert each round's points to a standings rank.
  // Rank is computed across ALL entities that have at least one start by that round
  // (so back-markers who run 2 races don't rank ahead of full-timers who haven't raced yet).
  const metric = STATE.arc.metric || "points";
  const isPosition = metric === "position";

  const seriesData = cumByEntity.map(s => ({
    ...s,
    // In position mode we overwrite `pts` with per-round ranks (1 = best)
    // Null sentinel for "no data yet" (hasn't started a race by that round)
    values: s.pts.slice(),
  }));

  if (isPosition) {
    // Mark drivers who have no starts up to each round
    // We need a Set per entity: set of rounds in which they participated
    const participatedByEntity = {};
    cumByEntity.forEach(s => {
      participatedByEntity[s.key] = new Set();
      s.entity.races.forEach(r => participatedByEntity[s.key].add(r.round));
    });

    // For each round index, rank everyone who has participated in at least one race by then
    roundsPresent.forEach((_, i) => {
      // Track whether each entity has raced yet by this round
      const hasRacedYet = cumByEntity.map(s => {
        for (let j = 0; j <= i; j++) {
          if (participatedByEntity[s.key].has(roundsPresent[j])) return true;
        }
        return false;
      });
      // Ranked by cumulative points at this round (desc), ties broken arbitrarily
      const indexed = cumByEntity.map((s, idx) => ({ idx, pts: s.pts[i], hasRaced: hasRacedYet[idx] }));
      const ranked = indexed
        .filter(x => x.hasRaced)
        .sort((a, b) => b.pts - a.pts);
      // Build rank lookup
      const rankByIdx = {};
      ranked.forEach((x, rank) => { rankByIdx[x.idx] = rank + 1; });
      seriesData.forEach((s, idx) => {
        s.values[i] = rankByIdx[idx] ?? null;
      });
    });
  }

  if (STATE.arc.selected.size === 0 && !STATE.arc.userCleared) {
    const totals = computeSeasonTotals();
    totals.slice(0, 5).forEach(t => STATE.arc.selected.add(entityKey(t)));
  }

  const W = 980, H = 420, pad = { top: 16, right: 150, bottom: 26, left: 48 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  // Scale computation differs by metric
  let yMax, yMin;
  if (isPosition) {
    // Find the worst rank any SELECTED driver reached (so axis adapts)
    const allRanksInSelected = seriesData
      .filter(s => STATE.arc.selected.has(s.key))
      .flatMap(s => s.values.filter(v => v != null));
    yMax = allRanksInSelected.length ? Math.max(...allRanksInSelected) : 30;
    // Pad slightly and round up to nearest 5
    yMax = Math.ceil((yMax + 2) / 5) * 5;
    yMin = 1;
  } else {
    yMax = Math.max(1, ...seriesData.map(s => s.values[s.values.length - 1] || 0));
    yMin = 0;
  }
  const nRaces = roundsPresent.length;

  const xScale = (i) => pad.left + (i / Math.max(1, nRaces - 1)) * innerW;
  // For points: low values at bottom, high at top.
  // For position: P1 at top, higher numbers at bottom (inverted scale).
  const yScale = (v) => {
    if (isPosition) {
      return pad.top + ((v - yMin) / (yMax - yMin)) * innerH;
    }
    return pad.top + (1 - v / yMax) * innerH;
  };

  // Gridlines + labels
  const gridlines = [];
  const gridSteps = 5;
  for (let i = 0; i <= gridSteps; i++) {
    const y = pad.top + (i / gridSteps) * innerH;
    let val;
    if (isPosition) {
      val = Math.round(yMin + (yMax - yMin) * (i / gridSteps));
      val = `P${val}`;
    } else {
      val = Math.round(yMax * (1 - i / gridSteps));
    }
    gridlines.push(`<line class="gridline" x1="${pad.left}" x2="${W - pad.right}" y1="${y}" y2="${y}"/>`);
    gridlines.push(`<text x="${pad.left - 6}" y="${y + 3}" text-anchor="end" fill="var(--muted)" font-family="var(--mono)" font-size="10">${val}</text>`);
  }
  const xLabels = roundsPresent.map((r, i) =>
    `<text x="${xScale(i)}" y="${H - 8}" text-anchor="middle" fill="var(--muted)" font-family="var(--mono)" font-size="10">R${r}</text>`
  ).join("");

  const active = seriesData
    .filter(s => STATE.arc.selected.has(s.key))
    .map(s => {
      const last = s.values[s.values.length - 1];
      return { ...s, labelY: last != null ? yScale(last) : null };
    })
    .filter(s => s.labelY != null)
    .sort((a, b) => a.labelY - b.labelY);
  const MIN_GAP = 12;
  for (let i = 1; i < active.length; i++) {
    if (active[i].labelY - active[i - 1].labelY < MIN_GAP) {
      active[i].labelY = active[i - 1].labelY + MIN_GAP;
    }
  }

  const lines = active.map(s => {
    // Skip null values (entity hadn't raced yet)
    const segs = [];
    let current = [];
    s.values.forEach((v, i) => {
      if (v == null) {
        if (current.length >= 2) segs.push(current);
        current = [];
      } else {
        current.push(`${xScale(i)},${yScale(v)}`);
      }
    });
    if (current.length >= 2) segs.push(current);
    const polylines = segs.map(pts => `<polyline points="${pts.join(" ")}" fill="none" stroke="${s.color}" stroke-width="1.8" stroke-linejoin="round"/>`).join("");
    const lastVal = s.values[s.values.length - 1];
    const xEnd = xScale(nRaces - 1);
    const yEnd = lastVal != null ? yScale(lastVal) : s.labelY;
    const connector = Math.abs(s.labelY - yEnd) > 2
      ? `<line x1="${xEnd + 2}" y1="${yEnd}" x2="${xEnd + 5}" y2="${s.labelY}" stroke="${s.color}" stroke-width="0.8" opacity="0.6"/>`
      : "";
    return `<g>
      ${polylines}
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
    (e) => STATE.arc.selected.has(entityKey(e)),
    (teamDrivers) => {
      teamDrivers.forEach(e => STATE.arc.selected.add(entityKey(e)));
      renderArc();
    },
    STATE.arc.teamFilter
  );
}

// ============================================================
// BREAKDOWN — multi-select up to 4 drivers, car-color-tinted bars
// ============================================================
function renderBreakdown() {
  const svg = document.getElementById("breakdown-svg");
  const tip = document.getElementById("breakdown-tooltip");
  if (!STATE.data) return;

  renderTeamFilter("breakdown-team-filter", "breakdown", () => renderBreakdown());

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
  const showTip = (rd, groupCx, groupTopY, evt) => {
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

    const card = svg.parentElement;
    const cardRect = card.getBoundingClientRect();
    const tipRect = tip.getBoundingClientRect();

    // Prefer placing the tooltip offset to the right of the cursor (24px gap),
    // flipping to the left side if we'd run off the card's right edge.
    let left, top;
    if (evt && typeof evt.clientX === "number") {
      const cx = evt.clientX - cardRect.left;
      const cy = evt.clientY - cardRect.top;
      left = cx + 24;
      if (left + tipRect.width > card.clientWidth - 6) {
        left = cx - tipRect.width - 24;
      }
      // Vertically try to keep centered on cursor, but clamp inside card
      top = cy - tipRect.height / 2;
      if (top < 6) top = 6;
      if (top + tipRect.height > card.clientHeight - 6) top = card.clientHeight - tipRect.height - 6;
    } else {
      // Fallback: old anchored-to-group behavior
      const svgRect = svg.getBoundingClientRect();
      const scale = svgRect.width / W;
      const pxX = (svgRect.left - cardRect.left) + groupCx * scale;
      const pxY = (svgRect.top  - cardRect.top)  + groupTopY * scale;
      left = pxX - tipRect.width / 2;
      top = pxY - tipRect.height - 10;
      left = Math.max(6, Math.min(left, card.clientWidth - tipRect.width - 6));
      if (top < 6) top = pxY + 14;
    }
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
    hit.addEventListener("mouseenter", (e) => showTip(rd, groupCx, topBound, e));
    hit.addEventListener("mousemove",  (e) => showTip(rd, groupCx, topBound, e));
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("click",      (e) => showTip(rd, groupCx, topBound, e));
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
    (e) => STATE.breakdown.drivers.includes(e.driver),
    (teamDrivers) => {
      const CAP = 4;
      const picks = teamDrivers.slice(0, CAP).map(e => e.driver);
      if (picks.length > 0) {
        STATE.breakdown.drivers = picks;
        renderBreakdown();
      }
    },
    STATE.breakdown.teamFilter
  );
}

// ============================================================
// TRAJECTORY (a.k.a. Stage Analysis)
// ============================================================
function renderTrajectory() {
  const svg = document.getElementById("trajectory-svg");
  if (!STATE.data) return;

  renderTeamFilter("trajectory-team-filter", "trajectory", () => renderTrajectory());

  const trackFilter = STATE.trajectory.tracks;
  const includeRace = (race) => {
    if (trackFilter === "all") return true;
    return trackType(race.track_code) === trackFilter;
  };

  // Pull entities + metadata. In single-season mode this is allEntities();
  // in multi-season mode it's the combined cross-year roll-up.
  let { entities, totalRaces, seasonsUsed } = trajectoryEntities();

  // Apply team filter if set (single-season only — team mapping across years
  // may not be coherent anyway). For multi-year, skip filtering entirely.
  if (STATE.trajectory.teamFilter && seasonsUsed.length <= 1) {
    entities = entities.filter(e => e.team_code === STATE.trajectory.teamFilter);
  }

  // Full-time: ≥90% of races in the combined pool (or all of them if few).
  // This generalizes isFullTime() across multi-year aggregations.
  const ftThreshold = totalRaces < 10 ? Math.max(1, totalRaces - 1)
                                      : Math.ceil(totalRaces * 0.9);
  const isFtHere = (d) => d.races.length >= ftThreshold;

  // Filter each driver's races by track type + require >= 1 race after filtering
  // to avoid divide-by-zero on the average calculations.
  let eligible = entities
    .filter(isFtHere)
    .map(d => ({ ...d, races: d.races.filter(includeRace) }))
    .filter(d => d.races.length >= 1);

  // Driver-pill filter — if the user has picked specific drivers in the picker,
  // narrow the chart to those only. Empty selection = show everyone (default).
  if (STATE.trajectory.selected.size > 0) {
    eligible = eligible.filter(d => STATE.trajectory.selected.has(entityKey(d)));
  }

  // Update the sub-title to reflect the current filter
  const subEl = document.getElementById("trajectory-sub");
  if (subEl) {
    const modeDesc = STATE.trajectory.mode === "trajectory"
      ? `arrows from season avg → last-5 avg (momentum direction)`
      : `season average per car`;
    const trackPart = (trackFilter === "all") ? "" : ` · ${TRACK_TYPE_LABELS[trackFilter] || trackFilter} only`;
    const seasonsPart = seasonsUsed.length > 1
      ? ` · ${seasonsUsed[0]}–${seasonsUsed[seasonsUsed.length - 1]} combined (${totalRaces} races)`
      : "";
    subEl.textContent = `Pace vs. results — ${modeDesc}${seasonsPart}${trackPart}`;
  }

  // Paint the season-chips toolbar + driver picker (both always present;
  // they're idempotent and cheap to re-render on every data refresh).
  renderTrajectorySeasonChips();
  renderTrajectoryDriverGrid(entities);

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
    <span class="legend-item"><span class="legend-dot" style="background:${STATE.trajectory.mode === "trajectory" ? "var(--accent-2)" : "var(--accent)"}"></span>Car · ${STATE.trajectory.mode === "trajectory" ? "season → last-5" : "season avg"}</span>
    <span class="legend-item"><span class="legend-line"></span>League trend</span>
    <span class="legend-item" style="color:var(--pos)">▲ above = converting pace to results</span>
    <span class="legend-item" style="color:var(--neg)">▼ below = leaving points on the table</span>
  `;

  const sorted = [...withResid].sort((x, y) => y.resid - x.resid);
  fillTrajCallout("trajectory-over", sorted.slice(0, 5));
  fillTrajCallout("trajectory-under", sorted.slice(-5).reverse());
}

// Paint the multi-season toggle chips under the main toolbar. Empty selection
// = single-season (current year from header picker). Any toggle adds/removes
// that year to the combined aggregation.
function renderTrajectorySeasonChips() {
  const host = document.getElementById("traj-seasons");
  if (!host) return;
  const available = STATE.seasonsAvailable || [];
  const selected = STATE.trajectory.seasons;
  // If nothing selected, show current header season as implicitly "on"
  const implicitSelected = selected.size === 0 ? new Set([STATE.season]) : selected;
  host.innerHTML = available.map(y => {
    const on = implicitSelected.has(y) ? "on" : "";
    return `<button class="${on}" data-year="${y}">${y}</button>`;
  }).join("");
  host.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", async () => {
      const y = parseInt(btn.dataset.year, 10);
      // If user taps the current implicit selection with no others set, seed
      // the set with just that year first so we have something concrete to toggle.
      if (STATE.trajectory.seasons.size === 0) {
        STATE.trajectory.seasons.add(STATE.season);
      }
      if (STATE.trajectory.seasons.has(y)) {
        STATE.trajectory.seasons.delete(y);
      } else {
        STATE.trajectory.seasons.add(y);
      }
      // Fetch any newly-selected years that aren't cached yet, then re-render.
      await ensureTrajectorySeasonsLoaded();
      // Whenever the season set changes, reset the driver selection — different
      // years may not share drivers, so keeping a stale selection would confuse.
      STATE.trajectory.selected.clear();
      renderTrajectory();
    });
  });
}

// Driver-pill picker for Stage Analysis. Mirrors the Arc view's picker but
// wires into STATE.trajectory.selected. entities = the pool to pick from
// (already aggregated across whatever seasons are selected).
function renderTrajectoryDriverGrid(entities) {
  const host = document.getElementById("trajectory-driver-grid");
  if (!host) return;
  // The shared renderDriverGrid pulls from allEntities(). For multi-season
  // views we need our aggregated entity list instead, so we paint the pills
  // ourselves using the same pattern but fed by the passed-in `entities`.

  // Filter to entities that actually have race data, sort by total points desc
  const decorated = entities
    .map(e => ({ ...e, _total: e.races.reduce((s, r) => s + (r.total || 0), 0) }))
    .sort((a, b) => b._total - a._total);

  // Optional: trim to a manageable max so the grid doesn't sprawl on multi-year
  const MAX_PILLS = 80;
  const shown = decorated.slice(0, MAX_PILLS);

  const html = shown.map(e => {
    const key = entityKey(e);
    const sel = STATE.trajectory.selected.has(key) ? "selected" : "";
    const carHex = colorFor(STATE.series, e.car_number);
    const txt = contrastTextFor(carHex);
    const primaryDrv = e.primaryDriver || e.driver || "";
    const lastName = primaryDrv.split(/\s+/).slice(-1)[0];
    const coCount = (e.coDrivers || []).length;
    const label = coCount > 0 ? `${lastName} +${coCount}` : lastName;
    return `<div class="driver-pill ${sel}" data-key="${escapeHTML(key)}" title="${escapeHTML(displayName(e))}">
      <span class="dp-num" style="background:${carHex};color:${txt}">${e.car_number}</span>
      <span class="dp-name">${escapeHTML(label)}</span>
      ${renderCoDriverBadge(e)}
    </div>`;
  }).join("");

  host.innerHTML = `<div class="driver-grid">${html}</div>`;

  host.querySelectorAll(".driver-pill").forEach(el => {
    el.addEventListener("click", () => {
      const key = el.dataset.key;
      if (STATE.trajectory.selected.has(key)) STATE.trajectory.selected.delete(key);
      else STATE.trajectory.selected.add(key);
      renderTrajectory();
    });
  });

  wireCoDriverBadges(host);
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
  "SPI": "Spire Motorsports", "KR": "Kaulig Racing", "HAAS": "Haas Factory Team",
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

// Compact labels for the team pill row (smaller space). Falls back through
// GROUP_DISPLAY_NAMES → TEAM_FULL_NAMES → team code.
const TEAM_PILL_LABELS = {
  "PEN": "Penske + WBR",
  "FRM": "Front Row",
  "RCR": "Richard Childress",
  "HMS": "Hendrick",
  "THR": "Trackhouse",
  "LMC": "Legacy MC",
  "KR":  "Kaulig",
  "SPI": "Spire",
  "RFK": "RFK",
  "JGR": "Joe Gibbs",
  "23XI": "23XI",
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
      // Resolution: scraper field → owner parse (palette no longer stores team codes)
      const team = d.team_code
        || teamCodeFromName(d.team, SERIES_TO_KEY[STATE.series], d.car_number);
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
    // Team pill color is keyed by the group's team code directly.
    const orgHex = orgColorForTeam(grp) || "#9ca3af";
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
      const tmHref = `#/car/${d.car_number}`;
      return `<div class="tm-row${d.car_full_time ? "" : " part-time"}">
        <span class="tm-car" style="background:${carHex};color:${carTxt}">${d.car_number}</span>
        <div class="tm-name">
          <div class="tm-name-row">
            <a class="tm-name-primary profile-link" href="${tmHref}">${escapeHTML(d.primary_driver)}</a>${ptTag}
            ${isShared ? `<span class="tm-shared" data-car="${d.car_number}" title="Shared car — hover for details">i</span>` : ""}
            ${showWbrTag ? `<span class="tm-true-team">${escapeHTML(d.team)}</span>` : ""}
          </div>
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
  return `<svg class="tm-spk" data-series="${data}" data-color="${color}" data-metric="${metric}" data-car="${carLabel}" style="width:100%;height:26px;display:block;"></svg>`;
}

// Measure every .tm-spk SVG and draw it at its real pixel dimensions so circles stay round.
function tmPaintSparklines(root) {
  const svgs = (root || document).querySelectorAll("svg.tm-spk");
  svgs.forEach(svg => {
    const rect = svg.getBoundingClientRect();
    const W = Math.max(80, Math.floor(rect.width));
    const H = 26;
    const pad = { t: 4, b: 4, l: 3, r: 3 };
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
// Resolves a slug to a CAR entity from the current season's data.
// Returns null if not found.
//
// The app is car-centric — every profile route ultimately resolves to a car.
// Route kinds:
//   - kind "car":     slug is a car number (e.g. "#/car/45")
//   - kind "profile": slug is a driver-name slug (e.g. "#/profile/tyler-reddick").
//                     Backward-compat for old bookmarks — resolves to the car
//                     that driver drove most in the current season.
//
// After a successful "profile" resolution, we rewrite the URL hash to the
// canonical "#/car/<N>" form so subsequent copies of the URL are canonical.
function findEntityFromSlug() {
  if (!STATE.data || !STATE.profile.slug) return null;

  if (STATE.profile.kind === "car") {
    // Direct car lookup
    return allEntities().find(e => e.car_number === STATE.profile.slug) || null;
  }

  // Legacy driver-slug route — find the car where this driver drove the most.
  // Matches against the primary driver first, then falls back to any co-driver.
  const slug = STATE.profile.slug;
  const entities = allEntities();

  // Pass 1: primary driver match (most common case)
  const primaryHit = entities.find(e => slugify(e.primaryDriver || e.driver) === slug);
  if (primaryHit) {
    canonicalizeProfileURL(primaryHit);
    return primaryHit;
  }

  // Pass 2: any co-driver match. Pick the car where the matched driver has the
  // most starts (a driver-name slug could match two cars if they subbed in both).
  let bestHit = null;
  let bestStarts = -1;
  entities.forEach(e => {
    (e.driversByStarts || []).forEach(dc => {
      if (slugify(dc.name) === slug && dc.starts > bestStarts) {
        bestHit = e;
        bestStarts = dc.starts;
      }
    });
  });
  if (bestHit) {
    canonicalizeProfileURL(bestHit);
    return bestHit;
  }

  return null;
}

// Rewrites the URL to the canonical car-profile form without triggering a
// navigation event. Only called after a legacy slug route has been resolved.
function canonicalizeProfileURL(entity) {
  if (!entity || !entity.car_number) return;
  const canonical = `#/car/${entity.car_number}`;
  if (location.hash === canonical) return;
  // Update STATE so subsequent route reads reflect the canonical form
  STATE.profile.kind = "car";
  STATE.profile.slug = entity.car_number;
  // Rewrite history entry without firing hashchange
  try {
    history.replaceState(null, "", canonical);
  } catch (_) { /* no-op if replaceState unavailable */ }
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

  const myTeam = entity.team_code;
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
      const t = d.team_code
        || teamCodeFromName(d.team, SERIES_TO_KEY[STATE.series], d.car_number);
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
      if (!mates[key]) mates[key] = { driver: te.driver, car: te.car_number, beat: 0, lost: 0, tied: 0, deltaSum: 0, races: 0, series: [] };
      if (myEntry.finish_pos < te.finish_pos) mates[key].beat++;
      else if (myEntry.finish_pos > te.finish_pos) mates[key].lost++;
      else mates[key].tied++;
      // Note: tmSparkline expects v = my_delta (negative if I beat them), matching
      // the Teammate Delta tab convention where better-than-teammate sits ABOVE zero.
      // There, v = te.finish_pos - leader.finish_pos; leader always wins (v<=0).
      // For profile view the "leader" is the teammate, so we flip: v = my finish - theirs.
      // Negative v = I beat my teammate that race.
      const v = myEntry.finish_pos - te.finish_pos;
      mates[key].deltaSum += -v;  // positive avg = I beat them
      mates[key].series.push({ v, round: r.round, tl: false });
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

  // Car-centric app: every profile is a car profile. `kind` remains as "owner"
  // for any code paths downstream that still branch on it (will be cleaned up
  // incrementally).
  const kind = "owner";
  const summary = profileSummary(entity);
  const { rank, of } = profileRank(entity);
  const carHex = colorFor(STATE.series, entity.car_number);
  const carTxt = contrastTextFor(carHex);
  const teamCode = entity.team_code || "";
  const orgHex = orgColorForTeam(teamCode) || "#555";
  const orgTxt = contrastTextFor(orgHex);

  const primaryDrv = entity.primaryDriver || entity.driver;
  const coCount = (entity.coDrivers || []).length;
  const titleText = coCount > 0
    ? `#${entity.car_number} · ${primaryDrv} +${coCount}`
    : `#${entity.car_number} · ${primaryDrv}`;
  // Wrap with badge for display contexts that use innerHTML
  const displayTitle = titleText;
  const displayTitleHTML = `${escapeHTML(titleText)}${renderCoDriverBadge(entity)}`;

  const rows = profileRaceRows(entity);
  const mfr = { TYT: "Toyota", CHE: "Chevrolet", CHV: "Chevrolet", FRD: "Ford", FOR: "Ford" }[entity.manufacturer] || entity.manufacturer || "—";
  const teamName = TEAM_FULL_NAMES[teamCode] || teamCode;

  // Bio lookup — use the primary driver (car profile shows the primary driver's bio).
  const bioDriverName = primaryDrv;
  const bio = STATE.driverBios ? STATE.driverBios[slugify(bioDriverName)] : null;
  const bioParts = [];
  if (bio) {
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
    <div class="profile-hero" style="--driver-color:${carHex}">
      <div class="profile-hero-car" style="background:${carHex};color:${carTxt}">${entity.car_number}</div>
      <div class="profile-hero-info">
        <h1 class="profile-hero-name">${displayTitleHTML}</h1>
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
  wireCoDriverBadges(host);
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
      <span></span><span>Teammate</span><span>Per-race Δ</span><span style="text-align:right;">Avg ΔFin</span><span style="text-align:right;">Beat</span>
    </div>
    ${mates.map(m => {
      const c = colorFor(STATE.series, m.car);
      const t = contrastTextFor(c);
      const cls = m.avgDelta > 0.5 ? "beat" : m.avgDelta < -0.5 ? "lost" : "tied";
      const sign = m.avgDelta > 0 ? "+" : "";
      // tmSparkline expects series formatted for the Teammate Delta tab. The
      // convention there is: negative v drawn below zero (worse than teammate).
      // profileTeammates stores v = myFinish - theirFinish (negative = I beat them).
      // Flip sign so the sparkline reads "above zero = I beat them" visually.
      const sparkSeries = m.series.map(s => ({ v: -s.v, round: s.round, tl: s.tl }));
      const spark = tmSparkline(sparkSeries, c, "fin", m.car);
      return `<div class="profile-tm-row">
        <span class="tm-car" style="background:${c};color:${t}">${m.car}</span>
        <span class="tm-name"><a class="profile-link" href="#/car/${m.car}">${escapeHTML(m.driver)}</a></span>
        <span class="profile-tm-spark">${spark}</span>
        <span class="profile-tm-delta ${cls}">${sign}${m.avgDelta.toFixed(1)}</span>
        <span class="profile-tm-record">${m.beat}-${m.lost}${m.tied > 0 ? "-" + m.tied : ""}</span>
      </div>`;
    }).join("")}
  `;
  // Paint the sparkline SVGs after they're inserted into the DOM
  tmPaintSparklines(host);
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
  corner.textContent = "Car";
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
    label.innerHTML = `<span class="car-tag" style="background:${carHex};color:${txt}">${d.car_number}</span><span>${escapeHTML(displayName(d))}</span>${renderCoDriverBadge(d)}`;
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
  wireCoDriverBadges(grid);
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
    const teamPill = renderTeamPill(r.team_code);
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
    const profileSlug = r.car_number;
    const profileKind = "car";
    return `<tr data-car-key="${escapeHTML(r.key)}">
      <td class="rank-cell">${r.currRank}${pcPill}</td>
      <td><a class="driver-cell profile-link" href="#/${profileKind}/${profileSlug}">
        <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
        <span>${escapeHTML(r.displayLabel)}</span>
        ${renderCoDriverBadge(r)}
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

  wireCoDriverBadges(table);
  wireTableSplitSelection(table, "selected-car-svg-std", "selected-car-head-std");
}

function pointsMapThroughRound(maxRound) {
  const seriesKey = SERIES_TO_KEY[STATE.series];
  const map = new Map();
  (STATE.data?.races || []).forEach(r => {
    if (r.round > maxRound) return;
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      // Car-centric identity: key is always car number.
      const key = `#${d.car_number}`;
      // Same team-code resolution used in allEntities: scraper field → owner parse
      const teamCode = d.team_code
        || teamCodeFromName(d.team, seriesKey, d.car_number)
        || null;
      if (!map.has(key)) {
        map.set(key, {
          key, driver: d.driver, driversSet: new Set(),
          driverStarts: {},
          car_number: d.car_number, team: d.team, team_code: teamCode,
          total: 0, starts: 0, wins: 0, top5: 0, top10: 0,
          finishes: [],
          sumS1: 0, sumS2: 0, sumFin: 0, sumFL: 0,
        });
      }
      const e = map.get(key);
      e.driversSet.add(d.driver);
      e.driverStarts[d.driver] = (e.driverStarts[d.driver] || 0) + 1;
      e.driver = d.driver;
      e.team = d.team;
      if (teamCode) e.team_code = teamCode;
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
    // Primary = driver with most starts in this car; co-drivers = the rest.
    const driversByStarts = Object.entries(e.driverStarts || {})
      .sort((a, b) => b[1] - a[1])
      .map(([name, starts]) => ({ name, starts }));
    const primaryDriver = driversByStarts[0] ? driversByStarts[0].name : e.driver;
    const coDrivers = driversByStarts.slice(1);
    const coCount = coDrivers.length;
    const displayLabel = coCount > 0
      ? `#${e.car_number} · ${primaryDriver} +${coCount}`
      : `#${e.car_number} · ${primaryDriver}`;
    return { ...e, avgFinish, displayLabel, primaryDriver, coDrivers, driversByStarts, driver: displayLabel };
  });
  rows.sort((a, b) => b.total - a.total);
  return rows;
}

// ============================================================
// PLAYOFFS
// ------------------------------------------------------------
// Rules-engine driven view. Each (series, year) resolves to a format spec
// that determines which render function handles it. Supports all historical
// eras, with stubs ready for data back to 1949.
//
// Format types:
//   "championship"      — pre-playoff era (season-long points title)
//   "chase"             — 2004–2013 Cup, 10- or 12-driver Chase (no eliminations)
//   "chase-wildcard"    — 2011–2013 Cup variant with wildcard spots
//   "elimination"       — 2014+ bracket with rounds & eliminations
// ============================================================

// Rule entries are evaluated top-to-bottom per series. `end: null` means
// "current era, still active". Entries are CLOSED intervals on both ends.
const PLAYOFF_RULES = {
  NCS: [
    { start: 1949, end: 2003, format: "championship" },
    { start: 2004, end: 2006, format: "chase", field: 10, playoffRaces: 10, regSeasonEndRound: 26, resetBase: 5050, winBonus: 10 },
    { start: 2007, end: 2010, format: "chase", field: 12, playoffRaces: 10, regSeasonEndRound: 26, resetBase: 5000, winBonus: 10 },
    { start: 2011, end: 2013, format: "chase-wildcard", field: 12, wildcards: 2, playoffRaces: 10, regSeasonEndRound: 26, resetBase: 5000, winBonus: 10 },
    { start: 2014, end: 2016, format: "elimination", field: 16, regSeasonEndRound: 26,
      rounds: [ { name: "Round of 16", races: 3, cutTo: 12 }, { name: "Round of 12", races: 3, cutTo: 8 }, { name: "Round of 8", races: 3, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: false, regBonus: false, raceWinPP: 3, stageWinPP: 0 },
    { start: 2017, end: 2025, format: "elimination", field: 16, regSeasonEndRound: 26,
      rounds: [ { name: "Round of 16", races: 3, cutTo: 12 }, { name: "Round of 12", races: 3, cutTo: 8 }, { name: "Round of 8", races: 3, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: true, regBonus: true, raceWinPP: 5, stageWinPP: 1 },
    // 2026: NASCAR returned to a non-elimination Chase format. 16 drivers qualify
    // by points only (no "win and in"), all 16 race all 10 Chase races with a
    // single reseed after the regular season. Most points at season's end wins.
    // Source: NASCAR announcement, Oct 2025.
    { start: 2026, end: null, format: "chase-reseeded", field: 16, playoffRaces: 10, regSeasonEndRound: 26,
      reseedTable: [2100, 2075, 2065, 2060, 2055, 2050, 2045, 2040, 2035, 2030, 2025, 2020, 2015, 2010, 2005, 2000],
      raceWinPts: 55, raceWinPtsIncrease: 15 /* was 40 in 2017-2025 */ },
  ],
  NOS: [
    { start: 1982, end: 2015, format: "championship" },
    { start: 2016, end: 2016, format: "elimination", field: 12, regSeasonEndRound: 26,
      rounds: [ { name: "Round of 12", races: 3, cutTo: 8 }, { name: "Round of 8", races: 3, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: false, regBonus: false, raceWinPP: 3, stageWinPP: 0 },
    { start: 2017, end: 2025, format: "elimination", field: 12, regSeasonEndRound: 26,
      rounds: [ { name: "Round of 12", races: 3, cutTo: 8 }, { name: "Round of 8", races: 3, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: true, regBonus: true, raceWinPP: 5, stageWinPP: 1 },
    // 2026+: Chase format return. Top 12 by points only. All 12 race the 9 Chase
    // races. Single reseed — same descending table as Cup, truncated at 12.
    { start: 2026, end: null, format: "chase-reseeded", field: 12, playoffRaces: 9, regSeasonEndRound: 26,
      reseedTable: [2100, 2075, 2065, 2060, 2055, 2050, 2045, 2040, 2035, 2030, 2025, 2020],
      raceWinPts: 55 },
  ],
  NTS: [
    { start: 1995, end: 2015, format: "championship" },
    { start: 2016, end: 2016, format: "elimination", field: 8, regSeasonEndRound: 16,
      rounds: [ { name: "Round of 8", races: 3, cutTo: 6 }, { name: "Round of 6", races: 3, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: false, regBonus: false, raceWinPP: 3, stageWinPP: 0 },
    { start: 2017, end: 2021, format: "elimination", field: 8, regSeasonEndRound: 16,
      rounds: [ { name: "Round of 8", races: 3, cutTo: 6 }, { name: "Round of 6", races: 3, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: true, regBonus: true, raceWinPP: 5, stageWinPP: 1 },
    { start: 2022, end: 2025, format: "elimination", field: 10, regSeasonEndRound: 16,
      rounds: [ { name: "Round of 10", races: 3, cutTo: 8 }, { name: "Round of 8", races: 3, cutTo: 6 }, { name: "Round of 6", races: 1, cutTo: 4 }, { name: "Championship 4", races: 1, cutTo: 1 } ],
      stages: true, regBonus: true, raceWinPP: 5, stageWinPP: 1 },
    // 2026+: Chase format return. Top 10 by points only. All 10 race the 7 Chase
    // races. Single reseed — same table as Cup, truncated at 10.
    { start: 2026, end: null, format: "chase-reseeded", field: 10, playoffRaces: 7, regSeasonEndRound: 16,
      reseedTable: [2100, 2075, 2065, 2060, 2055, 2050, 2045, 2040, 2035, 2030],
      raceWinPts: 55 },
  ],
};

function resolvePlayoffRules(series, year) {
  const lineage = PLAYOFF_RULES[series] || [];
  for (const rule of lineage) {
    if (year >= rule.start && (rule.end === null || year <= rule.end)) return rule;
  }
  return null;
}

// Compute playoff points for every driver from per-race data.
// Returns Map<key, {raceWins, stageWins, regBonus, total, ...}>
// Only works for "elimination" format years (2014+). Returns empty Map otherwise.
function computePlayoffPoints(rule) {
  const result = new Map();
  if (!rule || rule.format !== "elimination") return result;

  const races = racesSorted();
  if (!races.length) return result;

  // Consider only races through the regular-season cutoff round for reg-season bonus.
  // But race wins + stage wins accumulate all year (playoff PP carry through rounds).
  const regSeasonRaces = races.filter(r => r.round <= rule.regSeasonEndRound);

  // Tally race + stage wins across every race in the season (PP accrue in regular
  // season only for the "entering the playoffs" total — but the same value is
  // what gets applied as the reset bonus after the R26 cutoff).
  regSeasonRaces.forEach(r => {
    (r.results || []).forEach(d => {
      if (d.ineligible) return;
      const key = `#${d.car_number}`;
      if (!result.has(key)) result.set(key, { key, raceWins: 0, stageWins: 0, regBonus: 0, total: 0 });
      const rec = result.get(key);
      if (d.finish_pos === 1) rec.raceWins += 1;
      // Stage wins: 10 stage-1 points = stage 1 winner; same for stage 2.
      if (rule.stages) {
        if ((d.stage_1_pts || 0) === 10) rec.stageWins += 1;
        if ((d.stage_2_pts || 0) === 10) rec.stageWins += 1;
      }
    });
  });

  // Apply PP values from the rule
  result.forEach(rec => {
    rec.total = rec.raceWins * rule.raceWinPP + rec.stageWins * rule.stageWinPP;
  });

  // Regular-season finish bonus (2017+): compute rank by regular-season points
  // through cutoff round, give 15/10/8/7/6/5/4/3/2/1 to top 10.
  // Only applies AFTER the cutoff race is complete — mid-season it's TBD.
  const racesDoneForBonus = racesSorted().length;
  if (rule.regBonus && racesDoneForBonus >= rule.regSeasonEndRound) {
    const regSeasonStandings = rankingRowsFrom(pointsMapThroughRound(rule.regSeasonEndRound));
    const BONUS = [15, 10, 8, 7, 6, 5, 4, 3, 2, 1];
    regSeasonStandings.slice(0, 10).forEach((r, i) => {
      const rec = result.get(r.key);
      if (rec) {
        rec.regBonus = BONUS[i];
        rec.total += BONUS[i];
      }
    });
  }

  return result;
}

// Determine the current "playoff phase" for the active season.
// Returns one of:
//   "pre-regular"  — season hasn't reached the regular-season cutoff yet
//   "regular"      — regular season in progress (same as pre-regular, just explicit naming)
//   "playoffs"     — cutoff has passed; in the elimination rounds
//   "complete"     — all scheduled races are done
function currentPlayoffPhase(rule) {
  const races = racesSorted();
  if (!races.length) return "pre-regular";
  const lastRun = races[races.length - 1].round;
  const totalScheduled = STATE.data?.schedule_length ||
    { NCS: 36, NOS: 33, NTS: 23 }[STATE.series] || lastRun;
  if (lastRun <= rule.regSeasonEndRound) return "regular";
  if (lastRun >= totalScheduled) return "complete";
  return "playoffs";
}

// Compute the elimination bracket round-by-round. Returns an array of rounds,
// each with { name, racesRange, entering, advancing, eliminated }. Each driver
// is a { key, car_number, primaryDriver, team_code, displayLabel, roundPts,
// raceWinsInRound, autoAdvanced }.
//
// The algorithm uses scraped race data to reconstruct who advanced:
//   - Starting field: the 16/12/10 qualifiers (wins + points)
//   - In each round, tally race wins + stage wins during those races
//   - Auto-advance anyone who won a race during the round
//   - Fill remaining advance slots by total points accumulated in that round
// Points-in-round = finish points + stage points (all scraped).
//
// Honest caveat: this doesn't model reset points between rounds. The real rules
// reset everyone to 3000/4000/5000 + their carried PP. For advancement, what
// matters is RELATIVE order in the round, so the reset is a constant we can
// ignore for determining who advanced. For displaying "points going in" we'd
// need the reset logic — that's not shown in this view.
function computeEliminationBracket(rule) {
  if (!rule || rule.format !== "elimination") return [];
  const allRaces = racesSorted();
  if (!allRaces.length) return [];

  // Determine the playoff field (same logic as renderEliminationView).
  const pp = computePlayoffPoints(rule);
  const standingsAtCutoff = rankingRowsFrom(pointsMapThroughRound(rule.regSeasonEndRound));
  const ftThreshold = rule.regSeasonEndRound < 5 ? 1 : Math.ceil(rule.regSeasonEndRound * 0.9);
  const eligibleAtCutoff = standingsAtCutoff.filter(r => r.starts >= ftThreshold);

  const enriched = eligibleAtCutoff.map(r => {
    const p = pp.get(r.key) || { raceWins: 0, stageWins: 0, regBonus: 0, total: 0 };
    return { ...r, playoffPts: p.total, raceWins: p.raceWins, stageWins: p.stageWins };
  });
  const winners = enriched.filter(r => r.raceWins > 0).sort((a, b) => b.raceWins - a.raceWins || b.total - a.total);
  const nonWinners = enriched.filter(r => r.raceWins === 0).sort((a, b) => b.total - a.total);
  const winnersIn = winners.slice(0, rule.field);
  const field = [...winnersIn];
  if (field.length < rule.field) field.push(...nonWinners.slice(0, rule.field - field.length));

  // Walk each round. Start of playoffs is rule.regSeasonEndRound + 1.
  const rounds = [];
  let inContention = field.map(r => ({ ...r }));
  let cursor = rule.regSeasonEndRound + 1;

  for (const rdDef of rule.rounds) {
    const roundRaces = allRaces.filter(r => r.round >= cursor && r.round < cursor + rdDef.races);
    const roundHappened = roundRaces.length === rdDef.races;

    // Tally points + wins for each in-contention driver during this round.
    // Explicitly reset per-round flags (roundPts, raceWinsInRound, stageWinsInRound,
    // autoAdvanced) so prior-round flags don't bleed through via object spread.
    const roundTally = new Map();
    inContention.forEach(r => roundTally.set(r.key, {
      ...r,
      roundPts: 0,
      raceWinsInRound: 0,
      stageWinsInRound: 0,
      autoAdvanced: false,
    }));

    roundRaces.forEach(rc => {
      (rc.results || []).forEach(d => {
        if (d.ineligible) return;
        const key = `#${d.car_number}`;
        const rec = roundTally.get(key);
        if (!rec) return;
        const s1 = d.stage_1_pts || 0, s2 = d.stage_2_pts || 0, fin = d.finish_pts || 0, fl = d.fastest_lap_pt || 0;
        rec.roundPts += s1 + s2 + fin + fl;
        if (d.finish_pos === 1) rec.raceWinsInRound += 1;
        if (rule.stages) {
          if (s1 === 10) rec.stageWinsInRound += 1;
          if (s2 === 10) rec.stageWinsInRound += 1;
        }
      });
    });

    const roundResults = Array.from(roundTally.values()).sort((a, b) => b.roundPts - a.roundPts);

    // Advancement: race winners in this round advance automatically, then
    // fill remaining slots by round points. If the round didn't actually
    // happen (future/current), skip the advance calc and just note who's in.
    let advancing, eliminated;
    if (roundHappened) {
      const autoAdvance = roundResults.filter(r => r.raceWinsInRound > 0);
      autoAdvance.forEach(r => r.autoAdvanced = true);
      const rest = roundResults.filter(r => r.raceWinsInRound === 0);
      const autoKeys = new Set(autoAdvance.map(r => r.key));
      const needed = Math.max(0, rdDef.cutTo - autoAdvance.length);
      const filledByPoints = rest.slice(0, needed);
      advancing = [...autoAdvance, ...filledByPoints];
      const advKeys = new Set(advancing.map(r => r.key));
      eliminated = roundResults.filter(r => !advKeys.has(r.key));
    } else {
      advancing = roundResults; // still in contention, round hasn't fully happened
      eliminated = [];
    }

    rounds.push({
      name: rdDef.name,
      races: rdDef.races,
      cutTo: rdDef.cutTo,
      racesRange: [cursor, cursor + rdDef.races - 1],
      roundHappened,
      entering: roundResults,
      advancing,
      eliminated,
    });

    inContention = advancing;
    cursor += rdDef.races;
  }

  return rounds;
}

// Render the bracket as a horizontal column-per-round layout with driver
// cards that show round points + elimination status.
function renderBracket(rule) {
  const rounds = computeEliminationBracket(rule);
  if (!rounds.length) return "";

  // Column width grows with round size; each card is fixed width.
  const columnsHTML = rounds.map((rd, rIdx) => {
    const cardsHTML = rd.entering.map(drv => {
      const advKeys = new Set(rd.advancing.map(x => x.key));
      const isAdvance = advKeys.has(drv.key);
      const cls = !rd.roundHappened ? "pending" : (isAdvance ? "advance" : "out");
      const autoTag = drv.autoAdvanced ? `<span class="bk-auto" title="Won a race in this round — auto-advanced">W</span>` : "";
      const carHex = colorFor(STATE.series, drv.car_number);
      const txt = contrastTextFor(carHex);
      const lastName = (drv.primaryDriver || drv.driver || "").split(/\s+/).slice(-1)[0];
      return `<a class="bk-card ${cls}" href="#/car/${drv.car_number}" title="${escapeHTML(drv.displayLabel)} — ${drv.roundPts} pts in round">
        <span class="bk-car" style="background:${carHex};color:${txt}">${drv.car_number}</span>
        <span class="bk-name">${escapeHTML(lastName)}</span>
        <span class="bk-pts">${drv.roundPts}</span>
        ${autoTag}
      </a>`;
    }).join("");

    const statusLine = !rd.roundHappened
      ? `<span class="bk-col-status pending">In progress / upcoming</span>`
      : `<span class="bk-col-status done">R${rd.racesRange[0]}–${rd.racesRange[1]} · cut to ${rd.cutTo}</span>`;

    return `<div class="bk-col">
      <div class="bk-col-head">
        <span class="bk-col-name">${rd.name}</span>
        ${statusLine}
      </div>
      <div class="bk-col-cards">${cardsHTML}</div>
    </div>`;
  }).join("");

  return `<div class="card po-card">
    <div class="po-card-head">
      <span class="po-card-title">Playoff Bracket</span>
      <span class="po-card-sub">green = advanced · red = eliminated · <span class="bk-auto-legend">W</span> = won a race in the round (auto-advanced)</span>
    </div>
    <div class="bk-scroll"><div class="bk-grid">${columnsHTML}</div></div>
  </div>`;
}
// Mini playoff panel for the dashboard aside — just the key numbers + top 3
// first-out drivers. Full bracket/field lives in the takeover view.
// ============================================================
// LEFT PANEL — compact standings with playoff cutoff line
// ============================================================
// Shows all cars in points order. During regular season, the cutoff line
// appears at position `rule.field` (16/12/10 depending on series). During
// playoffs, the cutoff shifts to the current round's advancing count. Below
// the cutoff, each row shows the deficit to the bubble instead of raw points.
// ============================================================
// TEAM FILTER — shared across Arc / Breakdown / Stage Analysis tabs
// ============================================================
// Renders a row of clickable team pills above the chart picker. Clicking a
// team filters which cars are selectable/shown. `stateKey` is one of
// "arc" | "breakdown" | "trajectory" — it must correspond to a STATE slot
// with a `teamFilter` field. `onChange` fires after the state mutates so the
// calling view can re-render itself.
function renderTeamFilter(hostId, stateKey, onChange) {
  const host = document.getElementById(hostId);
  if (!host || !STATE.data) { if (host) host.innerHTML = ""; return; }

  // Collect unique team codes present in the current dataset
  const teamCodes = new Set();
  allEntities().forEach(e => { if (e.team_code) teamCodes.add(e.team_code); });
  const codes = Array.from(teamCodes).sort();
  if (codes.length === 0) { host.innerHTML = ""; return; }

  const active = STATE[stateKey]?.teamFilter || null;

  const allPill = `<span class="tf-pill tf-all ${active == null ? "active" : "inactive"}" data-team="">All</span>`;
  const pills = codes.map(code => {
    const hex = orgColorForTeam(code) || "#9ca3af";
    const txt = contrastTextFor(hex);
    const cls = active == null ? "" : (active === code ? "active" : "inactive");
    return `<span class="tf-pill ${cls}" data-team="${escapeHTML(code)}" style="background:${hex};color:${txt}">${escapeHTML(code)}</span>`;
  }).join("");
  host.innerHTML = allPill + pills;

  host.querySelectorAll(".tf-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      const team = pill.dataset.team || null;
      const current = STATE[stateKey].teamFilter || null;
      STATE[stateKey].teamFilter = (team === current || team === null || team === "") ? null : team;
      if (onChange) onChange();
    });
  });
}

// Apply a team filter to a list of entities. If filter is null, return as-is.
function applyTeamFilter(entities, stateKey) {
  const f = STATE[stateKey]?.teamFilter;
  if (!f) return entities;
  return entities.filter(e => e.team_code === f);
}

function renderStandingsMini() {
  const host = document.getElementById("standings-mini-host");
  const subEl = document.getElementById("standings-mini-sub");
  if (!host) return;
  if (!STATE.data) { host.innerHTML = ""; return; }

  const races = racesSorted();
  const lastRound = races.length ? races[races.length - 1].round : 0;
  const rows = rankingRowsFrom(pointsMapThroughRound(lastRound));

  const rule = resolvePlayoffRules(STATE.series, STATE.season);
  // Determine cutoff position based on rule.field (during regular season)
  // or based on the current round's elimination target (during playoffs).
  let cutoffPos = null;
  let cutoffLabel = null;
  if (rule && (rule.format === "elimination" || rule.format === "chase-reseeded" || rule.format === "chase" || rule.format === "chase-wildcard")) {
    const phase = currentPlayoffPhase(rule);
    if (phase === "regular") {
      cutoffPos = rule.field;
      cutoffLabel = `Cutoff · ${rule.field} make it`;
    } else if (rule.format === "elimination" && phase === "playoffs") {
      // Find the current round (the one in progress). The cutoff is that
      // round's `cutTo` value. Earlier rounds are done; later haven't started.
      let cursor = rule.regSeasonEndRound + 1;
      for (const rdDef of rule.rounds) {
        const inThisRound = lastRound >= cursor && lastRound < cursor + rdDef.races;
        if (inThisRound) { cutoffPos = rdDef.cutTo; cutoffLabel = `${rdDef.name} · cuts to ${rdDef.cutTo}`; break; }
        cursor += rdDef.races;
      }
    }
  }

  if (subEl) subEl.textContent = cutoffPos ? `${cutoffPos} in` : `${rows.length} cars`;

  const cutoffPts = (cutoffPos && rows.length >= cutoffPos) ? rows[cutoffPos - 1].total : null;

  const html = rows.map((r, i) => {
    const pos = i + 1;
    const below = cutoffPos != null && pos > cutoffPos;
    const carHex = colorFor(STATE.series, r.car_number);
    const txt = contrastTextFor(carHex);
    const lastName = (r.primaryDriver || r.driver || "").split(/\s+/).slice(-1)[0];
    const valCell = below && cutoffPts != null
      ? `<span class="std-mini-val back">−${cutoffPts - r.total}</span>`
      : `<span class="std-mini-val">${r.total}</span>`;
    const cutoffDivider = (cutoffPos != null && pos === cutoffPos) ? `<div class="std-mini-cutoff"><span class="std-mini-cutoff-label">${escapeHTML(cutoffLabel || "Cutoff")}</span></div>` : "";
    return `<a class="std-mini-row profile-link${below ? " below" : ""}" href="#/car/${r.car_number}" title="${escapeHTML(r.displayLabel)}">
      <span class="std-mini-rank">${pos}</span>
      <span class="std-mini-car" style="background:${carHex};color:${txt}">${r.car_number}</span>
      <span class="std-mini-name">${escapeHTML(lastName)}</span>
      ${valCell}
    </a>${cutoffDivider}`;
  }).join("");

  host.innerHTML = html;
}

// ============================================================
// RIGHT PANEL — form vs. season
// ============================================================
// Sorted by (last-5 form rating) − (season rating), hottest to coldest.
// Only shows cars that have valid ratings (full-timers with enough starts).
function renderFormMini() {
  const host = document.getElementById("form-mini-host");
  if (!host) return;
  if (!STATE.data) { host.innerHTML = ""; return; }

  const entities = allEntities().filter(isFullTime);
  const rows = entities.map(d => {
    const f = formRatingFor(d.races, "5");
    const s = formRatingFor(d.races, "season");
    const delta = (f != null && s != null) ? f - s : null;
    return { ...d, f, s, delta };
  }).filter(d => d.delta != null)
    .sort((a, b) => b.delta - a.delta);

  // Build a tiny SVG sparkline of the last 5 finish positions (inverted: low
  // finish = high line) so hot recent form shows as an upward-trending line.
  host.innerHTML = rows.map(r => {
    const carHex = colorFor(STATE.series, r.car_number);
    const txt = contrastTextFor(carHex);
    const lastName = (r.primaryDriver || r.driver || "").split(/\s+/).slice(-1)[0];
    const cls = r.delta > 1 ? "hot" : r.delta < -1 ? "cold" : "flat";
    const sign = r.delta > 0 ? "+" : "";
    const lastFinishes = r.races.slice(-5).map(rc => rc.finish).filter(x => x != null);
    // Same sparkline helper as Trending table
    const spark = sparkSVG(lastFinishes, carHex, 58, 14);
    return `<a class="form-mini-row profile-link" href="#/car/${r.car_number}" title="${escapeHTML(r.displayLabel)} — form ${r.f.toFixed(1)} vs. season ${r.s.toFixed(1)}">
      <div class="form-mini-top">
        <span class="form-mini-car" style="background:${carHex};color:${txt}">${r.car_number}</span>
        <span class="form-mini-name">${escapeHTML(lastName)}</span>
        <span class="form-mini-delta ${cls}">${sign}${r.delta.toFixed(1)}</span>
      </div>
      <div class="form-mini-bottom">
        <span class="form-mini-rating">${r.f.toFixed(1)}</span>
        ${spark}
      </div>
    </a>`;
  }).join("");
}

// Paint the selected-car cumulative-points arc into any svg + head pair.
// Used by Trending + Standings tabs. Falls back to the leader if nothing selected.
function paintSelectedCarArc(svgId, headId) {
  const svg = document.getElementById(svgId);
  const head = document.getElementById(headId);
  if (!svg) return;

  const entities = allEntities();
  if (!entities.length) { svg.innerHTML = ""; if (head) head.textContent = "No data"; return; }

  // Resolve selected entity; default to points leader
  const totals = computeSeasonTotals();
  const fallback = totals[0];
  const selectedKey = STATE.selectedCar;
  let entity = selectedKey ? entities.find(e => entityKey(e) === selectedKey) : null;
  if (!entity) entity = fallback;
  if (!entity) { svg.innerHTML = ""; if (head) head.textContent = "No data"; return; }

  if (head) head.textContent = `${displayName(entity)} · cumulative points`;

  // Compute cumulative totals across sorted races
  const allRaces = racesSorted();
  const byRound = {};
  entity.races.forEach(r => { byRound[r.round] = r; });
  let running = 0;
  const pts = [];
  allRaces.forEach(r => {
    const mine = byRound[r.round];
    if (mine && mine.total != null) running += mine.total;
    pts.push({ round: r.round, y: running });
  });

  const w = svg.clientWidth || 400;
  const h = svg.clientHeight || 220;
  const padL = 30, padR = 14, padT = 10, padB = 22;
  const maxY = Math.max(1, ...pts.map(p => p.y));
  const xAt = (i) => padL + (i / Math.max(1, pts.length - 1)) * (w - padL - padR);
  const yAt = (y) => padT + (1 - y / maxY) * (h - padT - padB);

  const poly = pts.map((p, i) => `${xAt(i)},${yAt(p.y)}`).join(" ");
  const color = colorFor(STATE.series, entity.car_number);

  // Axes
  const yTicks = [0, maxY * 0.25, maxY * 0.5, maxY * 0.75, maxY].map(v => Math.round(v));
  const yTickLines = yTicks.map(v => {
    const y = yAt(v);
    return `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2,3"/>
            <text x="${padL - 4}" y="${y + 3}" fill="var(--dim)" font-size="9" font-family="var(--mono)" text-anchor="end">${v}</text>`;
  }).join("");

  // Round labels — only show every 5 or so
  const step = Math.max(1, Math.floor(pts.length / 6));
  const xLabels = pts.map((p, i) => {
    if (i % step !== 0 && i !== pts.length - 1) return "";
    return `<text x="${xAt(i)}" y="${h - 6}" fill="var(--dim)" font-size="9" font-family="var(--mono)" text-anchor="middle">R${p.round}</text>`;
  }).join("");

  svg.innerHTML = `
    ${yTickLines}
    <polyline points="${poly}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" />
    ${pts.length ? `<circle cx="${xAt(pts.length - 1)}" cy="${yAt(pts[pts.length - 1].y)}" r="3" fill="${color}" />` : ""}
    ${xLabels}
  `;
}

// Wire click handlers on every row in a given table to update STATE.selectedCar
// and repaint the adjacent arc. Rows are identified via a `data-car-key` attr.
function wireTableSplitSelection(tableHost, svgId, headId) {
  if (!tableHost) return;
  tableHost.querySelectorAll("[data-car-key]").forEach(row => {
    row.classList.toggle("row-selected", row.dataset.carKey === STATE.selectedCar);
    row.addEventListener("click", (e) => {
      // Don't hijack clicks on actual links within the row (profile links)
      if (e.target.closest("a")) return;
      STATE.selectedCar = row.dataset.carKey;
      // Update highlight
      tableHost.querySelectorAll("[data-car-key]").forEach(r =>
        r.classList.toggle("row-selected", r.dataset.carKey === STATE.selectedCar));
      paintSelectedCarArc(svgId, headId);
    });
  });
  // Always paint on initial wire-up
  paintSelectedCarArc(svgId, headId);
}

function renderPlayoffsMini() {
  const host = document.getElementById("playoffs-mini-host");
  const sub = document.getElementById("playoffs-sub");
  if (!host) return;
  if (!STATE.data) { host.innerHTML = ""; return; }

  const rule = resolvePlayoffRules(STATE.series, STATE.season);
  if (!rule) {
    host.innerHTML = `<div class="po-mini-empty">No playoff format for ${STATE.series} ${STATE.season}.</div>`;
    if (sub) sub.textContent = "—";
    return;
  }

  if (rule.format === "championship") {
    if (sub) sub.textContent = "season-long points";
    host.innerHTML = `<div class="po-mini-empty">Season-long championship · no playoff format this year.</div>`;
    return;
  }

  if (rule.format === "chase" || rule.format === "chase-wildcard") {
    if (sub) sub.textContent = `Chase · ${rule.field}-driver · ${rule.playoffRaces}-race`;
    host.innerHTML = `<div class="po-mini-empty">Chase-era format (${rule.playoffRaces} races, ${rule.field} drivers). Full view coming soon.</div>`;
    return;
  }

  // -------- chase-reseeded (2026+) --------
  if (rule.format === "chase-reseeded") {
    const standingsRound = STATE.throughRound != null
      ? Math.min(STATE.throughRound, rule.regSeasonEndRound)
      : Math.min(racesSorted().length, rule.regSeasonEndRound);
    const ftThreshold = standingsRound < 5 ? 1 : Math.ceil(standingsRound * 0.9);
    const standings = rankingRowsFrom(pointsMapThroughRound(standingsRound));
    const eligible = standings.filter(r => r.starts >= ftThreshold);
    const field = eligible.slice(0, rule.field);
    const fieldKeys = new Set(field.map(r => r.key));
    const firstOut = eligible.filter(r => !fieldKeys.has(r.key)).slice(0, 3);
    const cutoffPts = field.length ? field[field.length - 1].total : 0;

    const phase = currentPlayoffPhase(rule);
    const phaseLabel = phase === "regular" ? `R${standingsRound} of ${rule.regSeasonEndRound}`
                       : phase === "playoffs" ? "Chase in progress"
                       : "Season complete";
    if (sub) sub.textContent = `${rule.field}-driver Chase · ${phaseLabel}`;

    host.innerHTML = `
      <div class="po-mini-card">
        <div class="po-mini-stat"><span class="lbl">Field size</span><span class="val">${rule.field}</span></div>
        <div class="po-mini-stat"><span class="lbl">Cutoff</span><span class="val">${cutoffPts}<span class="unit">pts</span></span></div>
        <div class="po-mini-stat"><span class="lbl">Chase races</span><span class="val">${rule.playoffRaces}</span></div>
        <div class="po-mini-hint">No win-and-in · points only · no eliminations</div>
        ${firstOut.length ? `
          <div class="po-mini-sep">First out</div>
          <div class="po-mini-list">
            ${firstOut.map(r => {
              const carHex = colorFor(STATE.series, r.car_number);
              const txt = contrastTextFor(carHex);
              const back = cutoffPts - r.total;
              const lastName = (r.primaryDriver || r.driver || "").split(/\s+/).slice(-1)[0];
              return `<a class="po-mini-row profile-link" href="#/car/${r.car_number}">
                <span class="po-mini-num" style="background:${carHex};color:${txt}">${r.car_number}</span>
                <span class="po-mini-name">${escapeHTML(lastName)}</span>
                <span class="po-mini-back">−${back}</span>
              </a>`;
            }).join("")}
          </div>
        ` : ""}
      </div>
    `;
    wireCoDriverBadges(host);
    return;
  }

  // -------- elimination (2014–2025) --------
  if (rule.format === "elimination") {
    const pp = computePlayoffPoints(rule);
    const standingsCutoff = rule.regSeasonEndRound;
    const standings = rankingRowsFrom(pointsMapThroughRound(standingsCutoff));
    const enriched = standings.map(r => {
      const p = pp.get(r.key) || { raceWins: 0, stageWins: 0, regBonus: 0, total: 0 };
      return { ...r, playoffPts: p.total, raceWins: p.raceWins };
    });
    const ftThreshold = standingsCutoff < 5 ? 1 : Math.ceil(standingsCutoff * 0.9);
    const eligible = enriched.filter(r => r.starts >= ftThreshold);
    const winners = eligible.filter(r => r.raceWins > 0).sort((a, b) => b.raceWins - a.raceWins || b.total - a.total);
    const nonWinners = eligible.filter(r => r.raceWins === 0).sort((a, b) => b.total - a.total);
    const winnersIn = winners.slice(0, rule.field);
    const field = [...winnersIn];
    if (field.length < rule.field) field.push(...nonWinners.slice(0, rule.field - field.length));
    const fieldKeys = new Set(field.map(r => r.key));
    const sorted = [...eligible].sort((a, b) => b.total - a.total);
    const firstOut = sorted.filter(r => !fieldKeys.has(r.key)).slice(0, 3);
    const cutoffPts = field.filter(r => r.raceWins === 0).slice(-1)[0]?.total || 0;

    const phase = currentPlayoffPhase(rule);
    const racesRun = racesSorted().length;
    const phaseLabel = phase === "regular" ? `R${racesRun} of ${rule.regSeasonEndRound}`
                       : phase === "playoffs" ? "Playoffs in progress"
                       : "Season complete";
    if (sub) sub.textContent = `${rule.field}-driver elimination · ${phaseLabel}`;

    host.innerHTML = `
      <div class="po-mini-card">
        <div class="po-mini-stat"><span class="lbl">Locked on wins</span><span class="val hot">${winnersIn.length}</span></div>
        <div class="po-mini-stat"><span class="lbl">In on points</span><span class="val accent">${field.length - winnersIn.length}</span></div>
        <div class="po-mini-stat"><span class="lbl">Cutoff</span><span class="val">${cutoffPts}<span class="unit">pts</span></span></div>
        ${firstOut.length ? `
          <div class="po-mini-sep">First out</div>
          <div class="po-mini-list">
            ${firstOut.map(r => {
              const carHex = colorFor(STATE.series, r.car_number);
              const txt = contrastTextFor(carHex);
              const back = cutoffPts - r.total;
              const lastName = (r.primaryDriver || r.driver || "").split(/\s+/).slice(-1)[0];
              return `<a class="po-mini-row profile-link" href="#/car/${r.car_number}">
                <span class="po-mini-num" style="background:${carHex};color:${txt}">${r.car_number}</span>
                <span class="po-mini-name">${escapeHTML(lastName)}</span>
                <span class="po-mini-back">−${back}</span>
              </a>`;
            }).join("")}
          </div>
        ` : ""}
      </div>
    `;
    wireCoDriverBadges(host);
    return;
  }

  host.innerHTML = `<div class="po-mini-empty">No mini view for format: ${rule.format}</div>`;
}

function renderPlayoffs() {
  const host = document.getElementById("playoffs-host");
  const sub = document.getElementById("playoffs-sub");
  if (!host) return;
  if (!STATE.data) { host.innerHTML = `<div class="empty">No data loaded.</div>`; return; }

  const rule = resolvePlayoffRules(STATE.series, STATE.season);
  if (!rule) {
    host.innerHTML = `<div class="empty">No playoff rules defined for ${STATE.series} ${STATE.season}.</div>`;
    sub.textContent = "—";
    return;
  }

  if (rule.format === "championship") {
    sub.textContent = `${STATE.season} ${STATE.series} · season-long championship (no playoff format)`;
    host.innerHTML = renderChampionshipView(rule);
    return;
  }

  if (rule.format === "chase" || rule.format === "chase-wildcard") {
    sub.textContent = `${STATE.season} ${STATE.series} · Chase for the Cup (${rule.field}-driver, ${rule.playoffRaces}-race)`;
    host.innerHTML = renderChaseView(rule);
    return;
  }

  if (rule.format === "chase-reseeded") {
    const phase = currentPlayoffPhase(rule);
    const phaseLabel = { "regular": "regular season in progress", "playoffs": "Chase in progress", "complete": "season complete" }[phase] || phase;
    sub.textContent = `${STATE.season} ${STATE.series} · ${rule.field}-driver Chase · ${rule.playoffRaces} Chase races · ${phaseLabel}`;
    host.innerHTML = renderChaseReseededView(rule, phase);
    wireCoDriverBadges(host);
    return;
  }

  if (rule.format === "elimination") {
    const phase = currentPlayoffPhase(rule);
    const phaseLabel = { "regular": "regular season in progress", "playoffs": "playoffs in progress", "complete": "season complete" }[phase] || phase;
    sub.textContent = `${STATE.season} ${STATE.series} · ${rule.field}-driver elimination · ${phaseLabel}`;
    host.innerHTML = renderEliminationView(rule, phase);
    wireCoDriverBadges(host);
    return;
  }

  host.innerHTML = `<div class="empty">Unknown format: ${rule.format}</div>`;
}

function renderChampionshipView(rule) {
  return `<div class="card"><div class="po-note">
    The ${STATE.season} ${STATE.series} season used a season-long points championship — no playoff format.
    See <a href="#/standings">Standings</a> for the full points battle.
  </div></div>`;
}

function renderChaseView(rule) {
  // Placeholder — needs historical data that isn't loaded yet. Show a message
  // explaining the format so users know what they'd see if data were available.
  const wildcardNote = rule.format === "chase-wildcard"
    ? ` With ${rule.wildcards} wildcard spots for non-top-10 drivers with wins.`
    : "";
  return `<div class="card"><div class="po-note">
    The ${STATE.season} ${STATE.series} season used the Chase format: top ${rule.field} drivers after R${rule.regSeasonEndRound}
    reseeded for the final ${rule.playoffRaces} races, with a ${rule.winBonus}-point bonus per win from the regular season.${wildcardNote}
    Chase-era playoff points are not yet computed — currently just a placeholder.
    See <a href="#/standings">Standings</a> for final points.
  </div></div>`;
}

// Chase with reseeded points, no eliminations. 2026+ format.
// Qualification: top N by points at end of regular season (no "win and in").
// Seeding: fixed table (e.g. 2100/2075/2065/.../2000 for Cup, truncated for other series).
// Championship: most points after all Chase races wins it. Everyone stays in the field.
function renderChaseReseededView(rule, phase) {
  const racesRun = racesSorted().length;

  // Standings through "now" (or through cutoff if playoffs have started)
  const standingsRound = phase === "regular" ? racesRun : rule.regSeasonEndRound;
  const standings = rankingRowsFrom(pointsMapThroughRound(standingsRound));
  // Threshold scales with the standings cutoff (starts can't exceed it)
  const ftThreshold = standingsRound < 5 ? 1 : Math.ceil(standingsRound * 0.9);
  const eligible = standings.filter(r => r.starts >= ftThreshold);

  // Projected or actual field: top N eligible by regular-season points
  const field = eligible.slice(0, rule.field);
  const fieldKeys = new Set(field.map(r => r.key));
  const firstOut = eligible.filter(r => !fieldKeys.has(r.key)).slice(0, 4);
  const cutoffPts = field.length ? field[field.length - 1].total : 0;

  // Build reseed projection — if we're in or past playoffs, show actual reseed.
  // Mid-regular-season, show "projected reseed" (what the table would look like
  // if the season ended today).
  const reseedProjection = field.map((r, i) => ({
    ...r,
    seed: i + 1,
    reseedPts: rule.reseedTable[i] || 2000,
  }));

  const bannerText = phase === "regular"
    ? `Regular season · R${racesRun} of ${rule.regSeasonEndRound} complete · field + reseed projected from current standings`
    : phase === "playoffs"
      ? `Chase in progress · field locked after R${rule.regSeasonEndRound}`
      : `Season complete · final results below`;
  const banner = `<div class="po-banner ${phase !== 'complete' ? 'po-banner-live' : ''}">${bannerText}</div>`;

  const formatExplainer = `
    <div class="card po-card po-format-note">
      <div class="po-note">
        <strong>2026 Chase Format</strong> · Top ${rule.field} by points qualify
        (no "win and in") · all ${rule.field} race the ${rule.playoffRaces} Chase races
        with a single reseed · <strong>no eliminations</strong> · most points at season's end wins.
        Wins are worth ${rule.raceWinPts} points (up from 40 in the previous format).
      </div>
    </div>
  `;

  const fieldTable = `
    <div class="card po-card">
      <div class="po-card-head">
        <span class="po-card-title">Chase Field (${rule.field})</span>
        <span class="po-card-sub">${phase === 'regular' ? 'projected' : 'qualified'} by regular-season points · ${rule.playoffRaces} Chase races to decide the title</span>
      </div>
      <table class="data-table po-table">
        <thead><tr>
          <th class="num">Seed</th>
          <th>Driver</th>
          <th>Team</th>
          <th class="num">Reg. Wins</th>
          <th class="num">Reg. Pts</th>
          <th class="num">Reseed Pts</th>
          <th class="num">Gap to 1st</th>
        </tr></thead>
        <tbody>
          ${reseedProjection.map(r => {
            const carHex = colorFor(STATE.series, r.car_number);
            const txt = contrastTextFor(carHex);
            const teamPill = renderTeamPill(r.team_code);
            const gap = r.seed === 1 ? "—" : `-${rule.reseedTable[0] - r.reseedPts}`;
            const seedCell = r.seed === 1
              ? `<td class="num"><span class="po-seed-top">1</span></td>`
              : `<td class="num">${r.seed}</td>`;
            return `<tr>
              ${seedCell}
              <td><a class="driver-cell profile-link" href="#/car/${r.car_number}">
                <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
                <span>${escapeHTML(r.displayLabel)}</span>
                ${renderCoDriverBadge(r)}
              </a></td>
              <td>${teamPill}</td>
              <td class="num">${r.wins}</td>
              <td class="num">${r.total}</td>
              <td class="num total-col">${r.reseedPts}</td>
              <td class="num">${gap}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;

  const bubbleTable = firstOut.length ? `
    <div class="card po-card">
      <div class="po-card-head">
        <span class="po-card-title">${phase === 'regular' ? 'On the Bubble' : 'Missed the Chase'}</span>
        <span class="po-card-sub">Cutoff: ${cutoffPts} pts · ${phase === 'regular' ? 'would miss the Chase if season ended today' : 'first 4 drivers outside the field'}</span>
      </div>
      <table class="data-table po-table">
        <thead><tr>
          <th class="num">Rank</th>
          <th>Driver</th>
          <th>Team</th>
          <th class="num">Wins</th>
          <th class="num">Pts</th>
          <th class="num">Back</th>
        </tr></thead>
        <tbody>
          ${firstOut.map(r => {
            const carHex = colorFor(STATE.series, r.car_number);
            const txt = contrastTextFor(carHex);
            const teamPill = renderTeamPill(r.team_code);
            const rank = standings.findIndex(x => x.key === r.key) + 1;
            const back = cutoffPts - r.total;
            return `<tr>
              <td class="num">${rank}</td>
              <td><a class="driver-cell profile-link" href="#/car/${r.car_number}">
                <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
                <span>${escapeHTML(r.displayLabel)}</span>
                ${renderCoDriverBadge(r)}
              </a></td>
              <td>${teamPill}</td>
              <td class="num">${r.wins}</td>
              <td class="num">${r.total}</td>
              <td class="num neg">-${back}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  ` : "";

  const reseedExplainer = `
    <div class="card po-card">
      <div class="po-card-head">
        <span class="po-card-title">Reseed Table</span>
        <span class="po-card-sub">Points assigned to each seed after the regular season · regular-season champ gets a 25-pt cushion</span>
      </div>
      <div class="po-reseed-grid">
        ${rule.reseedTable.map((pts, i) => `
          <div class="po-reseed-row">
            <span class="po-reseed-seed">${i + 1}</span>
            <span class="po-reseed-pts">${pts}</span>
          </div>
        `).join("")}
      </div>
    </div>
  `;

  return banner + formatExplainer + fieldTable + bubbleTable + reseedExplainer;
}

function renderEliminationView(rule, phase) {
  const pp = computePlayoffPoints(rule);
  const standings = rankingRowsFrom(pointsMapThroughRound(
    phase === "regular" ? racesSorted().slice(-1)[0].round : rule.regSeasonEndRound
  ));

  // Enrich each standings row with playoff points
  const enriched = standings.map(r => {
    const p = pp.get(r.key) || { raceWins: 0, stageWins: 0, regBonus: 0, total: 0 };
    return { ...r, playoffPts: p.total, raceWins: p.raceWins, stageWins: p.stageWins, regBonus: p.regBonus };
  });

  // Determine playoff field. Rule: drivers with wins enter first (by points tiebreak),
  // then fill remaining spots by points. Drivers must be eligible (running for
  // championship in this series); we approximate with a "has run most races
  // through the cutoff" filter. Key detail: `standings` was built through the
  // regular-season cutoff round (R26 for Cup), so `r.starts` on each row is
  // counting starts through R26 — so the threshold must also be ≤ R26.
  const standingsCutoff = phase === "regular" ? racesSorted().slice(-1)[0].round : rule.regSeasonEndRound;
  const ftThreshold = standingsCutoff < 5 ? 1 : Math.ceil(standingsCutoff * 0.9);
  const eligible = enriched.filter(r => r.starts >= ftThreshold);

  const winners = eligible.filter(r => r.raceWins > 0).sort((a, b) => b.raceWins - a.raceWins || b.total - a.total);
  const nonWinners = eligible.filter(r => r.raceWins === 0).sort((a, b) => b.total - a.total);

  // Fill up to rule.field: winners first (up to field), then points
  let field = [];
  const winnersIn = winners.slice(0, rule.field);
  field = [...winnersIn];
  const remainingSlots = rule.field - field.length;
  if (remainingSlots > 0) {
    field = [...field, ...nonWinners.slice(0, remainingSlots)];
  }
  const fieldKeys = new Set(field.map(r => r.key));

  // Rank the cutoff bubble: 4 above and 4 below the line for context
  const sortedByPointsEligible = [...eligible].sort((a, b) => b.total - a.total);
  const bubbleUp = field.filter(r => !(r.raceWins > 0)).slice(-3);  // 3 on-points drivers closest to cutoff
  const cutoffPts = bubbleUp.length ? bubbleUp[bubbleUp.length - 1].total : 0;
  const outsideLooking = sortedByPointsEligible.filter(r => !fieldKeys.has(r.key)).slice(0, 4);

  // ---------- Build HTML ----------
  const phaseBanner = phase === "regular"
    ? `<div class="po-banner po-banner-live">Regular season · R${racesSorted().slice(-1)[0].round} of ${rule.regSeasonEndRound} complete · field projected from current standings</div>`
    : phase === "playoffs"
      ? `<div class="po-banner po-banner-live">Playoffs in progress · Round details below</div>`
      : `<div class="po-banner">Season complete · final playoff results below</div>`;

  const fieldTable = `
    <div class="card po-card">
      <div class="po-card-head">
        <span class="po-card-title">Playoff Field (${rule.field})</span>
        <span class="po-card-sub">${winnersIn.length} locked in on wins · ${field.length - winnersIn.length} in on points</span>
      </div>
      <table class="data-table po-table">
        <thead><tr>
          <th class="num">#</th>
          <th>Driver</th>
          <th>Team</th>
          <th class="num">Wins</th>
          ${rule.stages ? `<th class="num">Stage Wins</th>` : ""}
          ${rule.regBonus ? `<th class="num">Reg Bonus</th>` : ""}
          <th class="num">Playoff Pts</th>
          <th class="num">Pts</th>
          <th>Status</th>
        </tr></thead>
        <tbody>
          ${field.map((r, i) => {
            const carHex = colorFor(STATE.series, r.car_number);
            const txt = contrastTextFor(carHex);
            const teamPill = renderTeamPill(r.team_code);
            const status = r.raceWins > 0
              ? `<span class="po-status locked">Locked (Win)</span>`
              : `<span class="po-status in-pts">In on points</span>`;
            return `<tr>
              <td class="num">${i + 1}</td>
              <td><a class="driver-cell profile-link" href="#/car/${r.car_number}">
                <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
                <span>${escapeHTML(r.displayLabel)}</span>
                ${renderCoDriverBadge(r)}
              </a></td>
              <td>${teamPill}</td>
              <td class="num">${r.raceWins}</td>
              ${rule.stages ? `<td class="num">${r.stageWins}</td>` : ""}
              ${rule.regBonus ? `<td class="num">${r.regBonus || 0}</td>` : ""}
              <td class="num total-col">${r.playoffPts}</td>
              <td class="num">${r.total}</td>
              <td>${status}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;

  const bubbleTable = outsideLooking.length ? `
    <div class="card po-card">
      <div class="po-card-head">
        <span class="po-card-title">On the Bubble</span>
        <span class="po-card-sub">Cutoff line: ${cutoffPts} pts · first 4 drivers outside the field</span>
      </div>
      <table class="data-table po-table">
        <thead><tr>
          <th class="num">Rank</th>
          <th>Driver</th>
          <th>Team</th>
          <th class="num">Pts</th>
          <th class="num">Back</th>
        </tr></thead>
        <tbody>
          ${outsideLooking.map(r => {
            const carHex = colorFor(STATE.series, r.car_number);
            const txt = contrastTextFor(carHex);
            const teamPill = renderTeamPill(r.team_code);
            const rank = enriched.findIndex(x => x.key === r.key) + 1;
            const back = cutoffPts - r.total;
            return `<tr>
              <td class="num">${rank}</td>
              <td><a class="driver-cell profile-link" href="#/car/${r.car_number}">
                <span class="car-tag" style="background:${carHex};color:${txt}">${r.car_number}</span>
                <span>${escapeHTML(r.displayLabel)}</span>
                ${renderCoDriverBadge(r)}
              </a></td>
              <td>${teamPill}</td>
              <td class="num">${r.total}</td>
              <td class="num neg">-${back}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>
  ` : "";

  const roundsInfo = `
    <div class="card po-card">
      <div class="po-card-head">
        <span class="po-card-title">Elimination Rounds</span>
        <span class="po-card-sub">${rule.rounds.length} rounds · ${rule.field} → 1</span>
      </div>
      <div class="po-rounds">
        ${rule.rounds.map((rnd, i) => {
          const prev = i === 0 ? rule.field : rule.rounds[i - 1].cutTo;
          return `<div class="po-round">
            <div class="po-round-name">${rnd.name}</div>
            <div class="po-round-meta">${prev} → ${rnd.cutTo} · ${rnd.races} race${rnd.races === 1 ? "" : "s"}</div>
          </div>`;
        }).join("")}
      </div>
    </div>
  `;

  // Bracket only makes sense after playoffs have started (R27+ for Cup).
  // Mid-regular-season we just show the field table + bubble.
  const bracketHTML = (phase === "playoffs" || phase === "complete") ? renderBracket(rule) : "";

  return phaseBanner + bracketHTML + fieldTable + bubbleTable + roundsInfo;
}
function escapeHTML(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

boot();
