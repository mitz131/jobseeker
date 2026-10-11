// Pure helpers (no DOM, no fetch), unit-tested with `node --test`.

export const DEFAULT_STATE = Object.freeze({
  home: "",            // postcode or locality, the distance starting point
  maxKm: "",           // only jobs within this distance of home
  location: "",        // text in the job location
  sort: "date",        // "date" (newest first) or "distance" (nearest first)
  companies: [],       // empty = all
  includeClosed: false,
  labels: [],          // label filters "question:answer"; jobs not labelled yet always show
});

/** Page state from the URL query, so a reload or a shared link keeps the filters. */
export function stateFromSearch(search) {
  const p = new URLSearchParams(search);
  const sort = p.get("sort") === "distance" ? "distance" : "date";
  return {
    home: p.get("home") ?? "",
    maxKm: p.get("max_km") ?? "",
    location: p.get("location") ?? "",
    sort,
    companies: p.getAll("company"),
    includeClosed: p.get("include_closed") === "true",
    labels: p.getAll("label"),
  };
}

/** URL query for the page; defaults are left out to keep links short. Like the API
 *  query, distance options only count when there is a starting point. */
export function stateToSearch(state) {
  const p = new URLSearchParams();
  const home = state.home.trim();
  if (home) {
    p.set("home", home);
    if (String(state.maxKm).trim()) p.set("max_km", String(state.maxKm).trim());
    if (state.sort !== "date") p.set("sort", state.sort);
  }
  if (state.location.trim()) p.set("location", state.location.trim());
  for (const c of state.companies) p.append("company", c);
  if (state.includeClosed) p.set("include_closed", "true");
  for (const l of state.labels) p.append("label", l);
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Query for GET /api/jobs. Distance options are only sent with a starting point,
 *  since the API rejects them otherwise. */
export function jobsQuery(state, limit = 1000) {
  const p = new URLSearchParams({ limit: String(limit) });
  const home = state.home.trim();
  if (home) {
    p.set("home", home);
    if (String(state.maxKm).trim()) p.set("max_km", String(state.maxKm).trim());
    if (state.sort === "distance") p.set("sort", "distance");
  }
  if (state.location.trim()) p.set("location", state.location.trim());
  for (const c of state.companies) p.append("company", c);
  if (state.includeClosed) p.set("include_closed", "true");
  for (const l of state.labels) p.append("label", l);
  return p.toString();
}

/** API path of one job. Ids are encoded as a whole: Workday ids contain "/". */
export function jobPath(company, jobId) {
  return `/api/jobs/${encodeURIComponent(company)}/${encodeURIComponent(jobId)}`;
}

/** "3 Oct 2026" */
export function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** "just now", "5 min ago", "3 h ago", "2 days ago" */
export function formatAge(iso, now = new Date()) {
  if (!iso) return "never";
  const minutes = Math.round((now - new Date(iso)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function formatKm(km) {
  return km === null || km === undefined ? "" : `${km.toFixed(1)} km`;
}

export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// --- labels ----------------------------------------------------------------------

/** Names shown for the label questions; unknown questions fall back to their key. */
export const QUESTION_NAMES = {
  seniority: "Seniority",
  people_management: "Manages people",
  job_family: "Job family",
  computer_engineering: "Computer engineering",
  employment_type: "Contract",
  french_required: "Requires French",
  german_required: "Requires German",
  english_required: "Requires English",
  work_model: "Work model",
};

const OPTION_NAMES = {
  software_it: "software / IT", data_ai: "data / AI", engineering_technical: "engineering",
  science_research: "science / research", health_social: "health / social", customer_service: "customer service",
  marketing_design: "marketing / design", corporate_functions: "corporate functions",
  production_supply_chain: "production / supply chain", fixed_term: "fixed term", on_site: "on site",
  not_stated: "not stated",
};

export function questionName(key) {
  return QUESTION_NAMES[key] ?? key.replaceAll("_", " ");
}

export function optionName(key) {
  return OPTION_NAMES[key] ?? key.replaceAll("_", " ");
}

/** One-click combinations of label filters. Each toggles its own filters on or off,
 *  so several can be combined ("IT jobs" + "No German needed"). */
export const QUICK_FILTERS = [
  { name: "IT jobs", labels: ["computer_engineering:yes"] },
  { name: "Entry level", labels: ["seniority:junior"] },
  { name: "No German needed", labels: ["german_required:no"] },
  { name: "Permanent", labels: ["employment_type:permanent"] },
  { name: "Hybrid or remote", labels: ["work_model:hybrid", "work_model:remote"] },
  { name: "Team lead roles", labels: ["people_management:yes"] },
];

/** Quick filters whose questions and answers all exist in the current question set
 *  (questions as in GET /api/labels). */
export function availableQuickFilters(questions) {
  const known = new Set(questions.flatMap((q) => q.options.map((o) => `${q.key}:${o.key}`)));
  return QUICK_FILTERS.filter((f) => f.labels.every((l) => known.has(l)));
}

export function quickFilterActive(labels, filter) {
  return filter.labels.every((l) => labels.includes(l));
}

/** The label filters after clicking a quick filter: off if it was on, else on. */
export function toggleQuickFilter(labels, filter) {
  if (quickFilterActive(labels, filter)) return labels.filter((l) => !filter.labels.includes(l));
  return [...labels, ...filter.labels.filter((l) => !labels.includes(l))];
}

/** The label filters with one question:answer switched on or off. */
export function toggleLabel(labels, value, on) {
  const rest = labels.filter((l) => l !== value);
  return on ? [...rest, value] : rest;
}

export const UNSURE_BELOW = 0.6; // answers less likely than this are shown as unsure

/** Short tags for a job row: the answers that tell jobs apart, not the common defaults
 *  (permanent contract, work model not stated, "no"). null labels: not labelled yet. */
export function labelTags(labels) {
  if (!labels) return [{ text: "not labelled yet", unsure: true, title: "Labelled at the next refresh" }];
  const tags = [];
  const add = (key, text) => {
    const l = labels[key];
    if (!l) return;
    const p = l.probability;
    tags.push({ text, unsure: p !== null && p !== undefined && p < UNSURE_BELOW,
                title: `${questionName(key)}: ${optionName(l.answer)}${p === null || p === undefined ? "" : ` (${Math.round(p * 100)}%)`}` });
  };
  const answer = (key) => labels[key]?.answer;
  if (answer("seniority")) add("seniority", optionName(answer("seniority")));
  if (answer("job_family")) add("job_family", optionName(answer("job_family")));
  if (answer("computer_engineering") === "yes") add("computer_engineering", "computer engineering");
  if (answer("people_management") === "yes") add("people_management", "manages people");
  const contract = answer("employment_type");
  if (contract && contract !== "permanent") add("employment_type", optionName(contract));
  const model = answer("work_model");
  if (model && model !== "not_stated") add("work_model", optionName(model));
  for (const [key, code] of [["french_required", "FR"], ["german_required", "DE"], ["english_required", "EN"]]) {
    if (answer(key) === "yes") add(key, code);
  }
  return tags;
}

/** The status line's "where it runs", from /api/status `running.where`. */
export function runtimeText(where) {
  return { kubernetes: "on Kubernetes", container: "in a container", local: "running locally" }[where] ?? where;
}
