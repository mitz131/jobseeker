import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_STATE, QUICK_FILTERS, availableQuickFilters, employerGroups, employersSummary, filtersSummary, formatAge, formatDate,
  formatKm, groupState, jobPath, jobsQuery, labelTags, quickFilterActive, runtimeText, shortLocation, sortEmployers,
  stateFromSearch, stateToSearch, toggleCompany, toggleGroup, toggleLabel, toggleQuickFilter, webLink,
} from "../src/lib.js";

test("state survives a round trip through the URL", () => {
  const state = { home: "1020", maxKm: "15", location: "Lausanne", sort: "distance",
                  companies: ["bcv", "salt"], categories: ["trading"], includeClosed: true,
                  labels: ["seniority:junior", "german_required:no"] };
  assert.deepEqual(stateFromSearch(stateToSearch(state)), state);
});

test("default state gives an empty query", () => {
  assert.equal(stateToSearch(DEFAULT_STATE), "");
  assert.deepEqual(stateFromSearch(""), { ...DEFAULT_STATE, companies: [], categories: [], labels: [] });
});

test("distance options stay out of the URL without a starting point", () => {
  assert.equal(stateToSearch({ ...DEFAULT_STATE, maxKm: "3", sort: "distance", companies: ["salt"] }),
               "?company=salt");
});

test("unknown sort falls back to date", () => {
  assert.equal(stateFromSearch("?sort=random").sort, "date");
});

test("distance options are only sent with a starting point", () => {
  const noHome = jobsQuery({ ...DEFAULT_STATE, maxKm: "10", sort: "distance" });
  assert.equal(noHome, "limit=1000");
  const withHome = new URLSearchParams(jobsQuery({ ...DEFAULT_STATE, home: " 1020 ", maxKm: "10", sort: "distance" }));
  assert.equal(withHome.get("home"), "1020");
  assert.equal(withHome.get("max_km"), "10");
  assert.equal(withHome.get("sort"), "distance");
});

test("companies are repeated parameters", () => {
  const q = new URLSearchParams(jobsQuery({ ...DEFAULT_STATE, companies: ["bcv", "salt"] }));
  assert.deepEqual(q.getAll("company"), ["bcv", "salt"]);
});

test("job ids with slashes are encoded as one path segment", () => {
  assert.equal(jobPath("logitech", "/job/Lausanne/Engineer_R1"),
               "/api/jobs/logitech/%2Fjob%2FLausanne%2FEngineer_R1");
});

test("dates and ages", () => {
  assert.equal(formatDate("2026-10-03T14:39:46+00:00"), "3 Oct 2026");
  assert.equal(formatDate(""), "");
  const now = new Date("2026-10-03T15:00:00Z");
  assert.equal(formatAge("2026-10-03T14:59:40Z", now), "just now");
  assert.equal(formatAge("2026-10-03T14:40:00Z", now), "20 min ago");
  assert.equal(formatAge("2026-10-02T15:00:00Z", now), "24 h ago");
  assert.equal(formatAge("2026-09-30T15:00:00Z", now), "3 days ago");
  assert.equal(formatAge(null, now), "never");
});

test("distances", () => {
  assert.equal(formatKm(0), "0.0 km");
  assert.equal(formatKm(12.34), "12.3 km");
  assert.equal(formatKm(null), "");
});

test("label filters go to the API as repeated label=question:answer", () => {
  const q = jobsQuery({ ...DEFAULT_STATE, labels: ["work_model:hybrid", "work_model:remote"] });
  assert.equal(q, "limit=1000&label=work_model%3Ahybrid&label=work_model%3Aremote");
});

test("quick filters toggle their own labels and combine", () => {
  const it = QUICK_FILTERS.find((f) => f.name === "IT jobs");
  const noGerman = QUICK_FILTERS.find((f) => f.name === "No German needed");
  let labels = toggleQuickFilter([], it);
  labels = toggleQuickFilter(labels, noGerman);
  assert.deepEqual(labels, ["computer_engineering:yes", "german_required:no"]);
  assert.ok(quickFilterActive(labels, it) && quickFilterActive(labels, noGerman));
  assert.deepEqual(toggleQuickFilter(labels, it), ["german_required:no"]);
  const hybrid = QUICK_FILTERS.find((f) => f.name === "Hybrid or remote");
  assert.ok(!quickFilterActive(["work_model:hybrid"], hybrid));          // only half of it
  assert.deepEqual(toggleQuickFilter(["work_model:hybrid"], hybrid), ["work_model:hybrid", "work_model:remote"]);
});

test("quick filters need their questions and answers", () => {
  const questions = [{ key: "seniority", options: [{ key: "junior" }, { key: "experienced" }] },
                     { key: "german_required", options: [{ key: "yes" }, { key: "no" }] }];
  assert.deepEqual(availableQuickFilters(questions).map((f) => f.name), ["Entry level", "No German needed"]);
});

test("toggleLabel adds and removes one filter", () => {
  assert.deepEqual(toggleLabel(["a:1"], "b:2", true), ["a:1", "b:2"]);
  assert.deepEqual(toggleLabel(["a:1", "b:2"], "a:1", false), ["b:2"]);
});

test("row tags skip common defaults and mark unsure answers", () => {
  const l = (answer, probability = 0.9) => ({ answer, probability });
  const tags = labelTags({
    seniority: l("experienced"), job_family: l("software_it", 0.45), computer_engineering: l("yes"),
    people_management: l("no"), employment_type: l("permanent"), work_model: l("not_stated"),
    french_required: l("yes"), german_required: l("no"), english_required: l("yes", 0.55),
  });
  assert.deepEqual(tags.map((t) => [t.text, t.unsure]), [
    ["experienced", false], ["software / IT", true], ["computer engineering", false], ["FR", false], ["EN", true],
  ]);
  assert.equal(tags[1].title, "Job family: software / IT (45%)");
  assert.deepEqual(labelTags(null).map((t) => t.text), ["not labelled yet"]);
  assert.equal(labelTags({ seniority: l("junior", null) })[0].title, "Seniority: junior");  // imported labels
});

test("runtime text for the status line", () => {
  assert.equal(runtimeText("kubernetes"), "on Kubernetes");
  assert.equal(runtimeText("local"), "running locally");
  assert.equal(runtimeText("elsewhere"), "elsewhere");
});

test("long location lists are cut to two places, Swiss first", () => {
  const cisco = "Brussels, Belgium / Amsterdam, Netherlands / Bern, Switzerland / Zurich, Switzerland / Slovakia";
  assert.deepEqual(shortLocation(cisco), {
    text: "Bern, Switzerland / Zurich, Switzerland +3 more",
    full: cisco.split(" / ").join("\n"),
  });
  assert.deepEqual(shortLocation("Kriens / Bern / Zurich").text, "Kriens / Bern +1 more");
  assert.deepEqual(shortLocation("Lausanne / Vevey"), { text: "Lausanne / Vevey", full: "" });
  assert.deepEqual(shortLocation(""), { text: "", full: "" });
});

test("employers sort by display name, ignoring accents", () => {
  const sorted = sortEmployers([{ company: "salt", label: "Salt" }, { company: "etatdevaud", label: "État de Vaud" },
                                { company: "bcv", label: "BCV" }, { company: "lombardodier", label: "Lombard Odier" }]);
  assert.deepEqual(sorted.map((e) => e.company), ["bcv", "etatdevaud", "lombardodier", "salt"]);
});

const CATEGORIES = [{ category: "bank", label: "Banks" }, { category: "trading", label: "Trading houses" }];
const COMPANIES = [
  { company: "pictet", label: "Pictet", category: "bank" },
  { company: "bcv", label: "BCV", category: "bank" },
  { company: "vitol", label: "Vitol", category: "trading" },
  { company: "gunvor", label: "Gunvor", category: "trading" },
  { company: "salt", label: "Salt", category: null },
  { company: "odd", label: "Odd", category: "typo" },
];
const GROUPS = employerGroups(COMPANIES, CATEGORIES);
const none = { companies: [], categories: [] };

test("employers grouped by category in config order, the rest under Other", () => {
  assert.deepEqual(GROUPS.map((g) => [g.category, g.label, g.companies.map((c) => c.company)]), [
    ["bank", "Banks", ["bcv", "pictet"]],
    ["trading", "Trading houses", ["gunvor", "vitol"]],
    [null, "Other", ["odd", "salt"]],
  ]);
  // a category only in the URL keeps an (empty) group, so it can be unticked
  assert.deepEqual(employerGroups(COMPANIES, CATEGORIES, ["gone"]).map((g) => g.category),
                   ["bank", "trading", "gone", null]);
});

test("ticking a group keeps it as a category, replacing its single employers", () => {
  const state = toggleGroup({ companies: ["pictet", "salt"], categories: [] }, GROUPS[0], true);
  assert.deepEqual(state, { companies: ["salt"], categories: ["bank"] });
  assert.equal(groupState(state, GROUPS[0]), "all");
  assert.deepEqual(toggleGroup(state, GROUPS[0], false), { companies: ["salt"], categories: [] });
});

test("Other is ticked employer by employer", () => {
  const state = toggleGroup(none, GROUPS[2], true);
  assert.deepEqual(state, { companies: ["odd", "salt"], categories: [] });
  assert.equal(groupState(state, GROUPS[2]), "all");
  assert.deepEqual(toggleGroup(state, GROUPS[2], false), none);
});

test("group checkbox state", () => {
  assert.equal(groupState(none, GROUPS[0]), "none");
  assert.equal(groupState({ companies: ["bcv"], categories: [] }, GROUPS[0]), "some");
  assert.equal(groupState({ companies: ["salt"], categories: [] }, GROUPS[2]), "some");
});

test("unticking one employer of a ticked group keeps the others", () => {
  const state = toggleCompany({ companies: ["salt"], categories: ["bank", "trading"] }, GROUPS, "vitol", false);
  assert.deepEqual(state, { companies: ["salt", "gunvor"], categories: ["bank"] });
});

test("ticking the last employer of a group turns it into the group", () => {
  let state = toggleCompany(none, GROUPS, "vitol", true);
  assert.deepEqual(state, { companies: ["vitol"], categories: [] });
  state = toggleCompany(state, GROUPS, "gunvor", true);
  assert.deepEqual(state, { companies: [], categories: ["trading"] });
  // but not for Other, which has no category
  assert.deepEqual(toggleCompany({ companies: ["odd"], categories: [] }, GROUPS, "salt", true),
                   { companies: ["odd", "salt"], categories: [] });
  assert.deepEqual(toggleCompany(state, GROUPS, "salt", false), state); // not ticked: no change
});

test("employer dropdown summary", () => {
  assert.equal(employersSummary(none, GROUPS), "All");
  assert.equal(employersSummary({ companies: ["vitol"], categories: ["bank"] }, GROUPS), "Banks, Vitol");
  assert.equal(employersSummary({ companies: ["pictet", "gone"], categories: [] }, GROUPS), "Pictet, gone"); // unknown: its name
  assert.equal(employersSummary({ companies: ["salt", "odd"], categories: ["bank", "trading"] }, GROUPS),
               "Banks, Trading houses +2 more");
});

test("categories go to the API query", () => {
  assert.equal(jobsQuery({ ...DEFAULT_STATE, companies: ["salt"], categories: ["bank"] }, 10),
               "limit=10&company=salt&category=bank");
});

test("only web addresses become links", () => {
  assert.equal(webLink("https://jobs.example/1"), "https://jobs.example/1");
  for (const bad of ["javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "/relative", "", null]) {
    assert.equal(webLink(bad), null, String(bad));
  }
});

test("folded filters summary", () => {
  assert.equal(filtersSummary(DEFAULT_STATE), "none");
  const state = { ...DEFAULT_STATE, home: "1020", maxKm: "60", labels: ["computer_engineering:yes"] };
  assert.equal(filtersSummary(state), "1020 · 60 km · IT jobs");
  assert.equal(filtersSummary({ ...state, maxKm: "", labels: ["computer_engineering:yes", "seniority:junior", "employment_type:fixed_term"] }),
               "1020 · IT jobs · Entry level · 1 label filter");
  assert.equal(filtersSummary({ ...DEFAULT_STATE, location: "Lausanne", labels: ["a:b", "c:d"], includeClosed: true, sort: "distance" }, "Banks"),
               "in Lausanne · Banks · 2 label filters · incl. closed · nearest first");
  assert.equal(filtersSummary(DEFAULT_STATE, "All"), "none");
});
