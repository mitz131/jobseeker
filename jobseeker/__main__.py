"""CLI entry point: python -m jobseeker {run,facets,list,near,places}"""

import argparse
import json
import logging
import sys
import tomllib
from collections import Counter
from pathlib import Path

from .crawler.http import HttpClient
from .crawler.runner import run_company
from .crawler.sources import build_source
from .crawler.sources.workday import iter_facets
from .db import JobStore, now
from .places import Places, nearest


def load_config(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def select_companies(config: dict, names: list[str] | None) -> list[dict]:
    companies = [c for c in config.get("company", []) if c.get("enabled", True) or names]
    if names:
        companies = [c for c in companies if c["name"] in names]
        missing = set(names) - {c["name"] for c in companies}
        if missing:
            sys.exit(f"Unknown company: {', '.join(sorted(missing))}")
    return companies


def load_places(args, config) -> Places | None:
    settings = config.get("settings", {})
    base = Path(args.config).parent
    register = base / settings.get("places_register", "AMTOVZ_CSV_LV95.csv")
    if not register.exists():
        return None
    places_file = base / settings.get("places_file", "places.toml")
    return Places(str(register), str(places_file) if places_file.exists() else None)


def location_strings(row) -> list[str]:
    return [s.strip() for s in (row["location"] or "").split(" / ") if s.strip()]


def cmd_run(args, config, store, client):
    max_new = config.get("settings", {}).get("max_new_per_company", 200)
    started = now()
    results = [run_company(store, client, c, max_new)
               for c in select_companies(config, args.company)]
    print()
    for r in results:
        status = f"ERROR: {r.error}" if r.error else "ok"
        print(f"{r.company:<15} matched={r.listed:<5} new={r.new:<5} {status}")
    places = load_places(args, config)
    if places:
        unresolved = sorted({s for row in store.jobs_since(started) for s in location_strings(row)
                             if places.resolve(s).status == "unresolved"})
        if unresolved:
            print(f"\nNew location(s) not resolved: {'; '.join(unresolved)}"
                  "\n  -> add them to places.toml (see `jobseeker places --unresolved`)")
    return 1 if any(r.error for r in results) else 0


def cmd_facets(args, config, store, client):
    for company in select_companies(config, [args.company]):
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
    places = load_places(args, config)
    if not places:
        sys.exit("Locality register not found; see places_register in config.toml")
    counts = Counter(s for row in store.jobs_since("0000") for s in location_strings(row))
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
    places = load_places(args, config)
    if not places:
        sys.exit("Locality register not found; see places_register in config.toml")
    try:
        home = places.resolve_home(args.home)
    except ValueError as e:
        sys.exit(str(e))
    found, unknown = [], []
    for row in store.jobs_since(args.since, args.company):
        # Remember which location string each place came from, so a canton- or
        # region-wide match is shown as such rather than as a specific town
        origin = {}
        for s in location_strings(row):
            res = places.resolve(s)
            for p in res.places:
                origin.setdefault(p, res.note if len(res.places) > 1 else "")
        hit = nearest(home, list(origin))
        if hit is None:
            unknown.append(row)
        elif args.max_km is None or hit[0] <= args.max_km:
            found.append((hit[0], hit[1], origin[hit[1]], row))
    found.sort(key=lambda f: (f[0], f[3]["company"], f[3]["title"]))
    print(f"From {home.name} ({home.canton})\n")
    for km, place, via, row in found:
        where = f"{place.name}, via {via}" if via else place.name
        print(f"{km:6.1f} km  {row['company']:<13} {row['title']}  [{where}]")
        print(f"            {row['url']}")
    print(f"\n{len(found)} job(s)" + (f" within {args.max_km:g} km" if args.max_km is not None else ""))
    if unknown and not args.hide_unknown:
        print(f"\nLocation unknown ({len(unknown)}):")
        for row in unknown:
            print(f"            {row['company']:<13} {row['title']}  [{row['location']}]")
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

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    config = load_config(args.config)
    settings = config.get("settings", {})
    db_path = Path(args.config).parent / settings.get("db_path", "jobs.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)  # data/ is not in git
    store = JobStore(str(db_path))
    client = HttpClient(delay=settings.get("request_delay", 0.5))
    try:
        commands = {"run": cmd_run, "facets": cmd_facets, "list": cmd_list,
                    "near": cmd_near, "places": cmd_places}
        return commands[args.cmd](
            args, config, store, client)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
