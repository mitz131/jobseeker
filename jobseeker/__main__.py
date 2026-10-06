"""CLI entry point: python -m jobseeker {run,facets,list,near,places,labels,serve}"""

import argparse
import json
import logging
import sys
from collections import Counter

from .config import Config
from .crawler.http import HttpClient
from .crawler.runner import run_all
from .crawler.sources import build_source
from .crawler.sources.workday import iter_facets
from .db import JobStore, now
from .labeling.compare import compare_runs
from .labeling.questions import load_question_set, load_thresholds
from .labeling.runner import INPUT_RECIPES, client_for, import_labels, label_jobs, select_jobs
from .labeling.store import LabelStore
from .places import distance_to_job, location_strings


def companies_or_exit(config: Config, names: list[str] | None) -> list[dict]:
    try:
        return config.companies(names)
    except ValueError as e:
        sys.exit(str(e))


def places_or_exit(config: Config):
    if not config.places:
        sys.exit("Locality register not found; see places_register in config.toml")
    return config.places


def cmd_run(args, config, store, client):
    started = now()
    results = run_all(store, client, companies_or_exit(config, args.company), config.max_new_per_company)
    print()
    for r in results:
        status = f"ERROR: {r.error}" if r.error else "ok"
        print(f"{r.company:<15} matched={r.listed:<5} new={r.new:<5} {status}")
    places = config.places
    if places:
        unresolved = sorted({s for row in store.jobs_since(started) for s in location_strings(row["location"])
                             if places.resolve(s).status == "unresolved"})
        if unresolved:
            print(f"\nNew location(s) not resolved: {'; '.join(unresolved)}"
                  "\n  -> add them to places.toml (see `jobseeker places --unresolved`)")
    return 1 if any(r.error for r in results) else 0


def cmd_facets(args, config, store, client):
    for company in companies_or_exit(config, [args.company]):
        source = build_source(client, company)
        if not hasattr(source, "available_facets"):
            sys.exit(f"{company['name']}: facets are only supported for Workday sources")
        for facet in iter_facets(source.available_facets()):
            print(f"\n[{facet['facetParameter']}] {facet.get('descriptor', '')}")
            for v in facet.get("values", []):
                if v.get("id"):
                    print(f"  {v['id']:<34} {v.get('descriptor', '')} ({v.get('count', '?')})")
    return 0


def cmd_list(args, config, store, client):
    rows = store.jobs_since(args.since, args.company)
    if args.json:
        print(json.dumps([dict(r) | {"raw_json": None} for r in rows], indent=2))
        return 0
    for r in rows:
        print(f"{r['first_seen'][:10]}  {r['company']:<15} {r['title']}  [{r['location']}]")
        print(f"            {r['url']}")
        if args.full:
            print("\n" + (r["description"] or "") + "\n" + "-" * 80)
    print(f"\n{len(rows)} job(s)")
    return 0


def cmd_places(args, config, store, client):
    places = places_or_exit(config)
    counts = Counter(s for row in store.jobs_since("0000") for s in location_strings(row["location"]))
    order = {"unresolved": 0, "unknown": 1, "ok": 2}
    shown = 0
    for raw, n in sorted(counts.items(), key=lambda kv: (order[places.resolve(kv[0]).status], kv[0])):
        res = places.resolve(raw)
        if args.unresolved and res.status != "unresolved":
            continue
        shown += 1
        names = ", ".join(f"{p.name} ({p.canton})" for p in res.places[:3])
        if len(res.places) > 3:
            names += f" +{len(res.places) - 3} more"
        print(f"{res.status:<10} {n:>3}x  {raw:<45} {names}  {res.note}".rstrip())
    print(f"\n{shown} location string(s)")
    return 0


def cmd_near(args, config, store, client):
    places = places_or_exit(config)
    try:
        home = places.resolve_home(args.home)
    except ValueError as e:
        sys.exit(str(e))
    found, unknown = [], []
    for row in store.jobs_since(args.since, args.company):
        match = distance_to_job(places, home, row["location"])
        if match is None:
            unknown.append(row)
        elif args.max_km is None or match.km <= args.max_km:
            found.append((match, row))
    found.sort(key=lambda f: (f[0].km, f[1]["company"], f[1]["title"]))
    print(f"From {home.name} ({home.canton})\n")
    for match, row in found:
        print(f"{match.km:6.1f} km  {row['company']:<13} {row['title']}  [{match.label}]")
        print(f"            {row['url']}")
    print(f"\n{len(found)} job(s)" + (f" within {args.max_km:g} km" if args.max_km is not None else ""))
    if unknown and not args.hide_unknown:
        print(f"\nLocation unknown ({len(unknown)}):")
        for row in unknown:
            print(f"            {row['company']:<13} {row['title']}  [{row['location']}]")
    return 0


def read_job_keys(path: str) -> list[tuple[str, str]]:
    """One job per line: company, whitespace, job id (ids may contain "/")."""
    keys = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                company, job_id = line.strip().split(None, 1)
                keys.append((company, job_id))
    return keys


def cmd_labels(args, config, store, client):
    labels = LabelStore(store.conn)
    try:
        if args.labels_cmd == "run":
            return labels_run(args, config, store, labels)
        if args.labels_cmd == "import":
            return labels_import(args, config, store, labels)
        if args.labels_cmd == "runs":
            return labels_runs(labels)
        if args.labels_cmd == "compare":
            return labels_compare(args, config, labels)
        if args.labels_cmd == "show":
            return labels_show(args, config, store, labels)
    except ValueError as e:
        sys.exit(str(e))
    return 0


def labels_run(args, config, store, labels):
    try:
        client_ = client_for(config.labels, args.backend)
    except ValueError as e:
        sys.exit(str(e))
    qs = load_question_set(config.labels, args.questions)
    keys = read_job_keys(args.jobs) if args.jobs else None
    jobs = select_jobs(store.conn, args.company, keys, args.limit)
    if not jobs:
        sys.exit("No jobs selected")
    print(f"Labelling {len(jobs)} job(s) with {args.backend} ({client_.url}), questions {qs.name}, input {args.input}")
    progress = lambda i, n: print(f"  {i}/{n}", flush=True) if i % 25 == 0 or i == n else None
    result = label_jobs(labels, client_, qs, args.input, jobs, args.backend, args.note, progress)
    print(f"Run {result.run_id}: {result.labeled} labelled, {result.failed} failed"
          + (f" ({result.error})" if result.error else ""))
    return 1 if result.error or not result.labeled else 0


def labels_import(args, config, store, labels):
    qs = load_question_set(config.labels, args.questions)
    with open(args.file, encoding="utf-8") as f:
        items = json.load(f)
    items = items.get("labels", items) if isinstance(items, dict) else items
    result = import_labels(labels, store.conn, qs, items, args.backend, args.model, args.input, args.note)
    print(f"Run {result.run_id}: {result.labeled} imported, {result.failed} rejected")
    return 0 if result.labeled else 1


def labels_runs(labels):
    runs = labels.runs()
    for r in runs:
        print(f"{r['id']:>4}  {r['started_at'][:16]}  {r['backend']:<10} {(r['model'] or ''):<28} "
              f"{r['question_set']:<5} {r['input_recipe']:<9} {r['status']:<8} "
              f"{r['labeled']:>4} ok {r['failed']:>3} failed  {r['note'] or ''}".rstrip())
    print(f"\n{len(runs)} run(s)")
    return 0


def run_thresholds(config, run, raw: bool) -> dict[str, float]:
    """The labels.toml thresholds for this run's backend and question set ({} with --raw)."""
    if raw or run["question_set"] not in config.labels.get("question_sets", {}):
        return {}
    return load_thresholds(config.labels, run["backend"], load_question_set(config.labels, run["question_set"]))


def describe_thresholds(run_id: int, thresholds: dict[str, float]) -> str:
    return f"run {run_id} yes if p >= " + ", ".join(f"{q} {t:g}" for q, t in thresholds.items())


def labels_compare(args, config, labels):
    a, b = labels.run(args.run_a), labels.run(args.run_b)
    thresholds = {run_id: run_thresholds(config, run, args.raw)
                  for run_id, run in ((args.run_a, a), (args.run_b, b)) if run is not None}
    results = compare_runs(labels, args.run_a, args.run_b, thresholds=thresholds)  # raises for unknown or mismatched runs
    print(f"Run {args.run_a} ({a['backend']}, {a['model']}) vs run {args.run_b} ({b['backend']}, {b['model']}), "
          f"question set {a['question_set']}")
    for run_id, t in thresholds.items():
        if t:
            print(describe_thresholds(run_id, t))
    print()
    for r in results:
        agree = f"{r.agreement:6.0%}" if r.agreement is not None else "     -"
        diffs = ", ".join(f"{x}->{y} ({n})" for (x, y), n in r.differences)
        print(f"{r.question:<22} {agree} of {r.common:<4} {diffs}")
        for t, (n, ok) in r.by_confidence.items():
            if n:
                print(f"{'':<22}   run {args.run_a} p >= {t:.1f}: {ok / n:4.0%} agree on {n} ({n / r.common:.0%} of jobs)")
    return 0


def labels_show(args, config, store, labels):
    run = labels.run(args.run)
    if run is None:
        sys.exit(f"No label run {args.run}")
    thresholds = run_thresholds(config, run, args.raw)
    if thresholds:
        print(describe_thresholds(args.run, thresholds) + "  (* = differs from the stored answer)\n")
    titles = {(r["company"], r["job_id"]): r["title"] for r in store.conn.execute("SELECT company, job_id, title FROM jobs")}
    shown = 0
    for (company, job_id), answers in sorted(labels.labels(args.run, thresholds).items()):
        if args.company and company != args.company:
            continue
        print(f"{company:<13} {titles.get((company, job_id), '?')}")
        for q, row in answers.items():
            p = f" ({row['probability']:.2f})" if row["probability"] is not None else ""
            moved = " *" if row["answer"] != row["stored_answer"] else ""
            print(f"{'':<15}{q:<22} {row['answer']}{p}{moved}")
        shown += 1
        if args.limit and shown >= args.limit:
            break
    return 0


def cmd_serve(args, config):
    import uvicorn

    from .api.app import create_app
    uvicorn.run(create_app(config), host=args.host, port=args.port)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jobseeker")
    p.add_argument("-c", "--config", default="config.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fetch new jobs (the daily job)")
    r.add_argument("company", nargs="*", help="limit to these companies")

    f = sub.add_parser("facets", help="show Workday filter facets and their IDs")
    f.add_argument("company")

    ls = sub.add_parser("list", help="show stored jobs")
    ls.add_argument("--since", default="0000", help="ISO date, e.g. 2026-10-01")
    ls.add_argument("--company")
    ls.add_argument("--full", action="store_true", help="include descriptions")
    ls.add_argument("--json", action="store_true")

    nr = sub.add_parser("near", help="jobs sorted by distance from a postcode or locality")
    nr.add_argument("home", help='postcode ("1020") or locality ("Renens VD")')
    nr.add_argument("--max-km", type=float, help="only jobs within this distance")
    nr.add_argument("--since", default="0000", help="first seen on/after this ISO date")
    nr.add_argument("--company")
    nr.add_argument("--hide-unknown", action="store_true", help="omit jobs without a known location")

    pl = sub.add_parser("places", help="show how job locations resolve to places")
    pl.add_argument("--unresolved", action="store_true", help="only strings that need places.toml")

    lb = sub.add_parser("labels", help="label jobs with a decision model; compare label runs")
    lsub = lb.add_subparsers(dest="labels_cmd", required=True)
    lr = lsub.add_parser("run", help="label jobs with a backend from labels.toml")
    lr.add_argument("backend")
    lr.add_argument("--questions", default="v1", help="question set (default: v1)")
    lr.add_argument("--input", default="full", choices=list(INPUT_RECIPES), help="what the model reads (default: full)")
    lr.add_argument("--company", action="append", help="only this company (repeatable)")
    lr.add_argument("--jobs", help="file with one 'company job_id' per line")
    lr.add_argument("--limit", type=int, help="at most this many jobs")
    lr.add_argument("--note")
    li = lsub.add_parser("import", help="import answers without probabilities (Claude, human)")
    li.add_argument("file", help='JSON: [{"company", "job_id", "answers": {question: answer}}]')
    li.add_argument("--backend", default="claude")
    li.add_argument("--model", required=True, help='e.g. "claude-opus-5-5"')
    li.add_argument("--questions", default="v1")
    li.add_argument("--input", default="full", help="what the labeller read (default: full)")
    li.add_argument("--note")
    lsub.add_parser("runs", help="list label runs")
    lc = lsub.add_parser("compare", help="agreement between two runs, per question")
    lc.add_argument("run_a", type=int)
    lc.add_argument("run_b", type=int)
    lc.add_argument("--raw", action="store_true", help="stored answers, without labels.toml thresholds")
    lw = lsub.add_parser("show", help="show the labels of a run")
    lw.add_argument("run", type=int)
    lw.add_argument("--company")
    lw.add_argument("--limit", type=int)
    lw.add_argument("--raw", action="store_true", help="stored answers, without labels.toml thresholds")

    sv = sub.add_parser("serve", help="start the web API (and, later, the web page)")
    sv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to accept connections from outside")
    sv.add_argument("--port", type=int, default=8090, help="default: 8090")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    config = Config.load(args.config)
    if args.cmd == "serve":
        return cmd_serve(args, config)
    store = JobStore(str(config.db_path))
    client = HttpClient(delay=config.request_delay)
    try:
        commands = {"run": cmd_run, "facets": cmd_facets, "list": cmd_list,
                    "near": cmd_near, "places": cmd_places, "labels": cmd_labels}
        return commands[args.cmd](args, config, store, client)
    finally:
        store.close()

if __name__ == "__main__":
    sys.exit(main())
