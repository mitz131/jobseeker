// Page logic: filters <-> URL, job list, background refresh and labelling. Job data
// is always inserted with textContent, never as HTML.

import {
  availableQuickFilters, debounce, formatAge, formatDate, formatKm, jobPath, jobsQuery, labelTags, optionName,
  questionName, quickFilterActive, runtimeText, shortLocation, stateFromSearch, stateToSearch, toggleLabel,
  toggleQuickFilter,
} from "./lib.js";

const POLL_MS = 5000;
const $ = (id) => document.getElementById(id);

let state = stateFromSearch(window.location.search);
let lastStatus = null;
let jobsRequest = 0; // number of the latest /api/jobs request; older answers are dropped
let pollTimer = null;
let labelQuestions = []; // from /api/labels; empty when labels are not configured

async function api(path, options) {
  const resp = await fetch(path, options);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (HTTP ${resp.status})`);
  }
  return body;
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

// --- filters ---------------------------------------------------------------------

function showControls() {
  $("home").value = state.home;
  $("max-km").value = state.maxKm;
  $("location").value = state.location;
  $("sort").value = state.sort;
  $("include-closed").checked = state.includeClosed;
  updateDistanceControls();
}

function readControls() {
  state = {
    home: $("home").value,
    maxKm: $("max-km").value,
    location: $("location").value,
    sort: $("sort").value,
    companies: [...document.querySelectorAll("#companies input:checked")].map((i) => i.value),
    includeClosed: $("include-closed").checked,
    labels: state.labels, // kept in sync by the label controls themselves
  };
}

/** Distance and "nearest first" only make sense with a starting point. */
function updateDistanceControls() {
  const hasHome = $("home").value.trim() !== "";
  $("max-km").disabled = !hasHome;
  $("sort").querySelector('option[value="distance"]').disabled = !hasHome;
  if (!hasHome && $("sort").value === "distance") $("sort").value = "date";
}

function onFiltersChanged() {
  updateDistanceControls();
  readControls();
  window.history.replaceState(null, "", window.location.pathname + stateToSearch(state));
  loadJobs();
}

function buildCompanyFilter(names) {
  const box = $("companies");
  box.querySelectorAll("label").forEach((l) => l.remove());
  const all = [...new Set([...names, ...state.companies])].sort();
  for (const name of all) {
    const input = el("input", { type: "checkbox", value: name, checked: state.companies.includes(name) });
    input.addEventListener("change", onFiltersChanged);
    box.append(el("label", { className: "check" }, input, ` ${name}`));
  }
}

// --- label filters ---------------------------------------------------------------

/** Checkboxes for choice questions, any/yes/no for yes/no questions, and the quick
 *  filters; built from /api/labels so they follow labels.toml. */
function buildLabelFilters(questions) {
  labelQuestions = questions;
  const groups = questions.map((q) => {
    if (q.type === "noul") {
      const select = el("select", { name: q.key },
        el("option", { value: "", textContent: "any" }),
        el("option", { value: `${q.key}:yes`, textContent: "yes" }),
        el("option", { value: `${q.key}:no`, textContent: "no" }));
      select.addEventListener("change", () => {
        let labels = state.labels.filter((l) => !l.startsWith(`${q.key}:`));
        if (select.value) labels = [...labels, select.value];
        setLabels(labels);
      });
      return el("label", { title: q.instructions }, `${questionName(q.key)} `, select);
    }
    const box = el("fieldset", { className: "label-group" }, el("legend", { textContent: questionName(q.key), title: q.instructions }));
    for (const o of q.options) {
      const value = `${q.key}:${o.key}`;
      const input = el("input", { type: "checkbox", value });
      input.addEventListener("change", () => setLabels(toggleLabel(state.labels, value, input.checked)));
      box.append(el("label", { className: "check", title: o.description }, input, ` ${optionName(o.key)}`));
    }
    return box;
  });
  $("label-groups").replaceChildren(...groups);

  const quick = $("quick");
  quick.querySelectorAll("button.quick-filter").forEach((b) => b.remove());
  for (const f of availableQuickFilters(questions)) {
    const button = el("button", { type: "button", className: "quick-filter", textContent: f.name, title: f.labels.join(", ") });
    button.dataset.labels = JSON.stringify(f.labels);
    button.addEventListener("click", () => setLabels(toggleQuickFilter(state.labels, f)));
    $("clear-labels").before(button);
  }
  quick.hidden = $("label-filters").hidden = questions.length === 0;
  showLabelControls();
}

/** Controls follow state.labels (after a quick filter, a URL, a checkbox). */
function showLabelControls() {
  document.querySelectorAll("#label-groups input[type=checkbox]").forEach((i) => { i.checked = state.labels.includes(i.value); });
  document.querySelectorAll("#label-groups select").forEach((s) => {
    s.value = state.labels.find((l) => l.startsWith(`${s.name}:`)) ?? "";
  });
  document.querySelectorAll("#quick button.quick-filter").forEach((b) => {
    b.classList.toggle("active", quickFilterActive(state.labels, { labels: JSON.parse(b.dataset.labels) }));
  });
  $("clear-labels").hidden = state.labels.length === 0;
  $("label-count").textContent = state.labels.length ? `(${state.labels.length} active)` : "";
}

function setLabels(labels) {
  state.labels = labels;
  showLabelControls();
  onFiltersChanged();
}

function showFilterError(message) {
  $("filter-error").textContent = message;
  $("filter-error").hidden = !message;
}

// --- job list --------------------------------------------------------------------

async function loadJobs() {
  const request = ++jobsRequest;
  let data;
  try {
    data = await api(`/api/jobs?${jobsQuery(state)}`);
  } catch (e) {
    if (request === jobsRequest) showFilterError(e.message);
    return;
  }
  if (request !== jobsRequest) return; // a newer filter change is already on its way
  showFilterError("");
  renderJobs(data);
}

function renderJobs(data) {
  const shown = data.items.length;
  let count = `${data.total} job${data.total === 1 ? "" : "s"}`;
  if (shown < data.total) count += ` (showing ${shown})`;
  const unlabelled = labelQuestions.length ? data.items.filter((j) => !j.labels).length : 0;
  if (unlabelled) count += ` · ${unlabelled} not labelled yet`;
  if (data.home) count += ` · distances from ${data.home}`;
  $("count").textContent = count;

  const rows = data.items.map((job) => {
    const title = el("a", { href: job.url, target: "_blank", rel: "noopener", textContent: job.title || "(no title)" });
    title.addEventListener("click", (e) => e.stopPropagation()); // open the ad, don't toggle the row
    const distance = el("td", { className: "col-distance" });
    if (data.home) {
      if (job.distance_km === null || job.distance_km === undefined) {
        distance.append(el("span", { className: "via", textContent: "location unknown" }));
      } else {
        distance.append(formatKm(job.distance_km), el("span", { className: "via", textContent: job.nearest || "" }));
      }
    }
    const row = el("tr", { className: job.open ? "job" : "job closed" },
      el("td", { className: "col-date", textContent: formatDate(job.first_seen) }),
      el("td", { className: "col-company", textContent: job.company }),
      el("td", {}, title, el("span", { className: "badge", textContent: "closed" }), tagsFor(job)),
      locationCell(job.location),
      distance);
    row.addEventListener("click", () => toggleDescription(row, job));
    return row;
  });
  $("jobs").querySelector("tbody").replaceChildren(...rows);
}

function locationCell(location) {
  const { text, full } = shortLocation(location);
  return el("td", { className: "col-location", textContent: text, title: full });
}

function tagsFor(job) {
  const box = el("div", { className: "tags" });
  if (!labelQuestions.length) return box;
  for (const t of labelTags(job.labels)) {
    box.append(el("span", { className: t.unsure ? "tag unsure" : "tag", textContent: t.text, title: t.title }));
  }
  return box;
}

async function toggleDescription(row, job) {
  if (row.nextElementSibling?.classList.contains("detail")) {
    row.nextElementSibling.remove();
    return;
  }
  const text = el("div", { className: "description", textContent: "Loading…" });
  row.after(el("tr", { className: "detail" }, el("td", { colSpan: 5 }, text)));
  try {
    const full = await api(jobPath(job.company, job.job_id));
    text.textContent = full.description || "(no description stored)";
  } catch (e) {
    text.textContent = `Could not load the description: ${e.message}`;
  }
}

// --- status and background refresh -----------------------------------------------

function renderStatus(s) {
  lastStatus = s;
  $("status-text").textContent = s.last_update
    ? `Updated ${formatAge(s.last_update)}` : "Not updated yet";
  $("status-text").title = s.last_update ? new Date(s.last_update).toLocaleString() : "";
  if (s.running) {
    $("runtime").textContent = runtimeText(s.running.where);
    $("runtime").title = s.running.detail;
    $("runtime").className = `runtime ${s.running.where}`;
    $("runtime").hidden = false;
  }
  $("refresh").disabled = s.refresh_running;

  const banner = $("banner");
  const failed = s.companies.filter((c) => c.error);
  if (s.refresh_running && s.refresh_phase === "labelling") {
    const progress = s.refresh_total ? ` ${s.refresh_done ?? 0} of ${s.refresh_total}` : "";
    banner.textContent = `Labelling new jobs in the background:${progress}. The list updates when it's done.`;
  } else if (s.refresh_running) {
    banner.textContent = `Fetching new jobs from all employers in the background (started ${formatAge(s.refresh_started_at)}). New jobs are labelled afterwards; the list updates when it's done.`;
  } else if (s.refresh_error) {
    banner.textContent = `The last update failed: ${s.refresh_error}`;
  } else if (failed.length) {
    banner.textContent = `Last update failed for ${failed.map((c) => `${c.company} (${c.error})`).join(", ")}.`;
  } else {
    banner.textContent = "";
  }
  banner.hidden = !banner.textContent;
}

async function loadStatus() {
  const s = await api("/api/status");
  renderStatus(s);
  return s;
}

function pollUntilDone() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    let s;
    try {
      s = await loadStatus();
    } catch {
      return; // server briefly unreachable: try again next tick
    }
    if (s.refresh_running) return;
    clearInterval(pollTimer);
    pollTimer = null;
    await loadJobs();
    if (!s.refresh_error && !s.companies.some((c) => c.error)) {
      let text;
      if (pollingFor === "label") {
        text = "Labelling finished.";
      } else {
        const fresh = s.companies.reduce((sum, c) => sum + (c.new || 0), 0);
        text = `Update finished: ${fresh} new job${fresh === 1 ? "" : "s"}.`;
      }
      if (s.refresh_note) text += ` ${s.refresh_note}.`;
      $("banner").textContent = text;
      $("banner").hidden = false;
    }
  }, POLL_MS);
}

let pollingFor = "refresh"; // what the running background job is: "refresh" or "label"

/** Label the jobs that have no labels yet, in the background (e.g. KEV was not running
 *  during the last refresh). */
async function labelNow() {
  try {
    const result = await api("/api/label", { method: "POST" });
    if (result.started) pollingFor = "label";
    const s = await loadStatus();
    if (result.started || s.refresh_running) pollUntilDone();
  } catch {
    // labels not configured or server busy: the list works without
  }
}

async function refresh(force) {
  try {
    const result = await api(`/api/refresh${force ? "?force=true" : ""}`, { method: "POST" });
    if (result.started) pollingFor = "refresh";
    const s = await loadStatus();
    if (result.started || s.refresh_running) pollUntilDone();
  } catch (e) {
    $("banner").textContent = `Could not start the update: ${e.message}`;
    $("banner").hidden = false;
  }
}

// --- start -----------------------------------------------------------------------

async function start() {
  showControls();
  const typed = debounce(onFiltersChanged, 350);
  for (const id of ["home", "max-km", "location"]) $(id).addEventListener("input", typed);
  for (const id of ["sort", "include-closed"]) $(id).addEventListener("change", onFiltersChanged);
  $("filters").addEventListener("submit", (e) => e.preventDefault());
  $("refresh").addEventListener("click", () => refresh(true));
  $("clear-labels").addEventListener("click", () => setLabels([]));

  try {
    buildLabelFilters((await api("/api/labels")).questions);
  } catch {
    buildLabelFilters([]); // labels not configured: no label filters
  }
  loadJobs();
  try {
    const s = await loadStatus();
    buildCompanyFilter(s.companies.map((c) => c.company));
    if (s.refresh_running) pollUntilDone();
    else if (s.stale) await refresh(false); // older than 24 h: update (and label) in the background
    else if (s.unlabelled) await labelNow(); // up to date, but some jobs have no labels yet
  } catch (e) {
    $("status-text").textContent = `Status unavailable: ${e.message}`;
  }
  // keep "Updated 5 min ago" current
  setInterval(() => lastStatus && renderStatus(lastStatus), 60000);
}

start();
