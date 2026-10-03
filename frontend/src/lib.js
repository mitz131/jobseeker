// Pure helpers (no DOM, no fetch), unit-tested with `node --test`.

export const DEFAULT_STATE = Object.freeze({
  home: "",            // postcode or locality, the distance starting point
  maxKm: "",           // only jobs within this distance of home
  location: "",        // text in the job location
  sort: "date",        // "date" (newest first) or "distance" (nearest first)
  companies: [],       // empty = all
  includeClosed: false,
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
