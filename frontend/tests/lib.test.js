import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_STATE, QUICK_FILTERS, availableQuickFilters, formatAge, formatDate, formatKm, jobPath, jobsQuery, labelTags,
  quickFilterActive, runtimeText, shortLocation, stateFromSearch, stateToSearch, toggleLabel, toggleQuickFilter,
} from "../src/lib.js";

test("state survives a round trip through the URL", () => {
  const state = { home: "1020", maxKm: "15", location: "Lausanne", sort: "distance",
                  companies: ["bcv", "salt"], includeClosed: true,
                  labels: ["seniority:junior", "german_required:no"] };
  assert.deepEqual(stateFromSearch(stateToSearch(state)), state);
});

test("default state gives an empty query", () => {
  assert.equal(stateToSearch(DEFAULT_STATE), "");
  assert.deepEqual(stateFromSearch(""), { ...DEFAULT_STATE, companies: [], labels: [] });
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
