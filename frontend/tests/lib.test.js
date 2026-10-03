import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_STATE, formatAge, formatDate, formatKm, jobPath, jobsQuery, stateFromSearch, stateToSearch,
} from "../src/lib.js";

test("state survives a round trip through the URL", () => {
  const state = { home: "1020", maxKm: "15", location: "Lausanne", sort: "distance",
                  companies: ["bcv", "salt"], includeClosed: true };
  assert.deepEqual(stateFromSearch(stateToSearch(state)), state);
});

test("default state gives an empty query", () => {
  assert.equal(stateToSearch(DEFAULT_STATE), "");
  assert.deepEqual(stateFromSearch(""), { ...DEFAULT_STATE, companies: [] });
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
