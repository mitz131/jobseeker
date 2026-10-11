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
labels.toml              labelling question sets and backends (hand-edited)
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
  api/                   web API (FastAPI): app.py, refresh.py
  labeling/              question sets, /v1/systemone client, label runs, comparison
  config.py              config.toml and derived paths (shared)
tests/                   mirrors the package: tests/crawler/, tests/api/, test_places.py
frontend/
  src/                   index.html, style.css, app.js (page), lib.js (pure logic)
  tests/                 lib.test.js – `npm test` in frontend/ (Node 18+, no dependencies)
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
| Cisco        | Phenom (careers.cisco.com)        | JSON API            |
| Swisscom     | Workday                           | JSON API            |

Adding a company on a supported platform is just a config entry. Other
platforms need a new class in `jobseeker/crawler/sources/` with `list_jobs()`
and `fetch_detail()`.

## Usage

```bash
jobseeker run                    # all companies
jobseeker run salesforce         # just one
jobseeker facets salesforce      # Workday filter IDs (country, category, ...)
jobseeker list --since 2026-10-01 [--company nestle] [--full | --json]
pytest                           # Python tests
(cd frontend && npm test)        # JavaScript tests
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

## Labelling with decision models

`labels.toml` defines **question sets** (e.g. `v1`: seniority, job family,
computer engineering, employment type, required languages, work model...) and
**backends**: any server speaking the `/v1/systemone` API (KEV's own server,
llama.cpp / llama.app with a KEV GGUF, the Jev API).

```bash
jobseeker labels run kev4b                       # label all stored jobs
jobseeker labels run kev4b --company salt --note "salt only"
jobseeker labels import claude.json --model claude-opus-5-5   # answers without probabilities
jobseeker labels runs                            # list runs
jobseeker labels compare 3 1                     # agreement per question, run 3 vs run 1
jobseeker labels show 3 --company salt
```

Every run records the backend, a snapshot of the model it served (`/v1/models`),
the question set and the **input recipe** (`full`: title, location and the whole
description; a shortened text was tried and dropped, since requirements such as
languages usually come at the end of an ad). Runs are only compared
within the same question set. A question set is frozen once used: edit it under
a new name (`v2`), otherwise `labels run` refuses.

Answers are stored with their probabilities; "unknown" is decided when reading,
from a probability threshold, so it can change without relabelling. `compare`
also shows agreement for answers above probability thresholds (0.5 / 0.7 / 0.9).

## Web page and API

```bash
jobseeker serve                        # http://127.0.0.1:8090
jobseeker serve --host 0.0.0.0         # reachable from outside (e.g. from the sandbox host)
```

- **`/`** – the job list (plain JavaScript in `frontend/src/`, no build step).
  Filter by starting point and distance, location text, employer and closed
  jobs; sort by date or distance; click a row for the description. Filters are
  kept in the page URL. When the data is older than 24 h, opening the page starts
  the update in the background and the list reloads when it's done.
- **`/docs`** (Swagger UI) and `/redoc` – interactive API documentation.

From the sandbox host, publish the port first:
`sbx ports <sandbox-name> --publish 8090:8090`.

| Endpoint | |
|---|---|
| `GET /api/jobs` | Jobs, newest first. `home` (postcode or locality) adds `distance_km`; `max_km`, `sort=distance`, `company` (repeatable), `location` (text, ignores case/accents), `include_closed`, `limit`/`offset` |
| `GET /api/jobs/{company}/{job_id}` | One job with its description (URL-encode the id: Workday ids contain `/`) |
| `GET /api/status` | Last update, whether it's older than 24 h, refresh state, last run per company |
| `POST /api/refresh` | Start the batch in the background if the data is older than 24 h (`force=true`: always). One run at a time; returns immediately |

A job is **open** when it was seen in its company's latest successful run;
closed jobs stay in the database and are listed with `include_closed=true`.

Run a single server process: the refresh lock doesn't reach across several
workers.

## Daily schedule

```cron
0 7 * * * cd /path/to/jobseeker && .venv/bin/jobseeker run >> run.log 2>&1
```

`run` exits non-zero if any company failed; each run is also logged in the
`runs` table.

## Kubernetes (minikube in the sandbox)

The image (`Dockerfile`) runs `jobseeker serve`; the data (`jobs.db` and the swisstopo
register) lives on a volume at `/app/data`. One pod only: SQLite and the background
refresh allow no second copy. Manifests: `deploy/k8s/jobseeker.yaml`.

```bash
deploy/minikube-network.sh   # after every `minikube start`: lets pods out (see below)
deploy/minikube-deploy.sh    # build, load into minikube, apply; first time: seed from data/
deploy/minikube-deploy.sh --seed   # replace the pod's database with a copy of data/jobs.db
deploy/minikube-backup.sh          # copy the pod's database to data/backups/jobs-<time>.db
deploy/minikube-backup.sh --update-local   # ... and make it data/jobs.db (old one kept in data/backups/)
```

The page is then on sandbox port 8090 (on the host: `sbx ports <sandbox> --publish
8090:8090`, http://localhost:8090). The Service has the fixed node port 30090, and
`minikube-network.sh` relays sandbox port 8090 to it, so the page stays reachable
across pod restarts and redeploys. `JOBSEEKER_PORT=8091 deploy/minikube-network.sh`
picks another port, e.g. while a local `jobseeker serve` has 8090.

Networking in the sandbox needs two fixes (besides the web relay), all lost when minikube restarts:
the node's `FORWARD` chain defaults to `DROP` (left by Docker in minikube's node
image), which blocks every connection out of a pod, DNS included; and pods can't
reach the sandbox proxy. `minikube-network.sh` sets the policy to `ACCEPT` and
relays the proxy on `192.168.49.1:3128` (socat), which the pod uses as
`HTTPS_PROXY`/`HTTP_PROXY`, for the career sites and for KEV.

The pod's database is its own copy: crawls and labels there don't reach `data/jobs.db`.
When the pod is where jobseeker runs, its volume holds the only current data (`minikube
delete` erases it): back it up with `minikube-backup.sh`, and don't `--seed` from a stale
`data/jobs.db`.

## Storage

`data/jobs.db` (SQLite):

- `jobs` – keyed by `(company, job_id)`; title, location, url, description
  (text + HTML), raw API payload, `first_seen`, `last_seen`.
- `runs` – one row per company per run with counts and errors.

A job whose `last_seen` stops advancing has been taken down (or no longer
matches your filter).
