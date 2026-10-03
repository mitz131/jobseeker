# jobseeker

Fetches job postings from company career-site APIs once a day, keeps only the
ones not seen before, and stores their descriptions in SQLite. Jobs can be
searched by straight-line distance from a postcode.

## Setup

Python 3.11+.

```bash
python -m venv .venv            # in this sandbox: python3 -m venv --copies .venv
.venv/bin/pip install -e ".[dev]"
```

This installs the `jobseeker` command (`python -m jobseeker` works too) and pytest.

`data/` is not in git. `data/jobs.db` is created on the first `jobseeker run`.
For distance search, download swisstopo's official locality register
(*Amtliches Ortschaftenverzeichnis*, CSV, LV95) from
[swisstopo](https://www.swisstopo.admin.ch/de/amtliches-ortschaftenverzeichnis)
and save it as `data/AMTOVZ_CSV_LV95.csv`.

## Layout

```
config.toml              employers and settings (hand-edited)
places.toml              location aliases and regions (hand-edited)
data/                    generated / downloaded files
  jobs.db                the job database
  AMTOVZ_CSV_LV95.csv    swisstopo locality register
jobseeker/
  __main__.py            CLI
  db.py                  storage (shared)
  places.py              locations and distance (shared)
  crawler/               fetching jobs
    runner.py            list -> diff -> fetch new, per employer
    http.py, html_text.py
    sources/             one module per career-site platform
tests/                   mirrors the package: tests/crawler/, test_places.py
```

## How it works

1. **List** – query each site's search API with the configured filter
   (cheap: titles + IDs only, paginated).
2. **Diff** – compare listing IDs with `data/jobs.db`; known jobs just get `last_seen` bumped.
3. **Fetch** – download the full description only for new jobs, and store them.

| Company      | Platform                          | Access              |
|--------------|-----------------------------------|---------------------|
| Salesforce   | Workday                           | JSON API            |
| Philip Morris| Phenom (join.pmicareers.com)      | JSON API            |
| Nestlé       | SAP SuccessFactors Career Site    | HTML (no JSON API)  |
| Logitech     | Workday                           | JSON API            |
| Vaudoise     | vaudoise.ch list + Softgarden     | HTML + JSON-LD      |
| État de Vaud | Oracle Recruiting Cloud           | JSON API            |
| BCV          | SAP SuccessFactors (newer site)   | JSON API + HTML     |
| Salt         | JobCloud company list             | embedded JSON + HTML|

Adding a company on a supported platform is just a config entry. Other
platforms need a new class in `jobseeker/crawler/sources/` with `list_jobs()`
and `fetch_detail()`.

## Usage

```bash
jobseeker run                    # all companies
jobseeker run salesforce         # just one
jobseeker facets salesforce      # Workday filter IDs (country, category, ...)
jobseeker list --since 2026-10-01 [--company nestle] [--full | --json]
pytest                           # tests
```

Filters live in `config.toml`: `search` (server-side), `facet_filters` such as
`{ Country = ["Switzerland"] }` (Workday, server-side, matched by display name
on each run; an unknown name aborts that company's run rather than fetching
everything), and `[company.filter]` include/exclude keywords (client-side,
whole words, also matching plural/feminine endings -e, -s, -es).

## Searching by distance

```bash
jobseeker near 1020                   # all jobs, nearest first, from postcode 1020
jobseeker near "Renens VD" --max-km 15
jobseeker places --unresolved         # location strings that need places.toml
```

Job locations are turned into points with swisstopo's official locality
register (`data/AMTOVZ_CSV_LV95.csv`, LV95 coordinates in metres) and the
hand-edited `places.toml`:

- **Towns** are looked up by name, ignoring case, accents and ü/ue
  (Zürich = Zurich = Zuerich). Canton codes, postcodes and country words in the
  string are hints. A locality that spills into a neighbouring municipality goes
  to the one with most of its addresses.
- **Municipality names** are only used together with a canton code ("Oron, VD"):
  on its own, "Riviera" would match the Ticino municipality.
- **Aliases** in `places.toml` cover other names ("Thoune" = Thun) and true
  ambiguities ("Romont" = Romont FR, "Biel" = Biel/Bienne).
- **Regions** in `places.toml` are lists of member localities ("Riviera").
- **Cantons**: a canton code ("VS"), a list of canton names in any national
  language or English ("Berne, Argovie, Soleure"), or a lone canton name that
  is not also a town ("Graubünden") stands for all localities of those cantons.
  A lone name that is also a town ("Zurich") is the town.
- **Country-only** strings ("Suisse") and the `ignore` list have no point and
  are shown as "location unknown".

A job's distance is the straight-line distance to its nearest location, so a
region or canton is at 0 km when the starting point is one of its localities;
`near` then shows the match as e.g. `[Zürich, via cantons BE, AG, SO, ZH]`.
`run` reports new location strings that don't resolve.

The register is updated monthly by swisstopo; refreshing it about once a year
is enough (municipality mergers).

## Daily schedule

```cron
0 7 * * * cd /path/to/jobseeker && .venv/bin/jobseeker run >> run.log 2>&1
```

`run` exits non-zero if any company failed; each run is also logged in the
`runs` table.

## Storage

`data/jobs.db` (SQLite):

- `jobs` – keyed by `(company, job_id)`; title, location, url, description
  (text + HTML), raw API payload, `first_seen`, `last_seen`.
- `runs` – one row per company per run with counts and errors.

A job whose `last_seen` stops advancing has been taken down (or no longer
matches your filter).
