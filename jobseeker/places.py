"""Turn job location strings into points, using swisstopo's official locality
register (AMTOVZ_CSV_LV95.csv) plus a small hand-edited places.toml.

Coordinates are Swiss LV95 (metres), so distance is plain Pythagoras.

A location string resolves to a list of places:
  - a town                 -> one place
  - a region (places.toml) -> its member towns
  - a canton code only     -> every locality in that canton
  - a list of canton names -> every locality in those cantons ("Berne, Argovie")
  - country only / ignored -> nothing ("location unknown")
The distance to a job is the distance to its nearest place, so a region or
canton is at distance 0 when the starting point is one of its localities.
"""

import csv
import math
import re
import tomllib
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

CANTONS = {"AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW",
           "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH"}
# Canton names in German, French, Italian and English, for strings that list
# cantons by name ("Berne, Argovie, Soleure") rather than by code.
CANTON_NAMES_BY_CODE = {
    "AG": ["Aargau", "Argovie", "Argovia"],
    "AI": ["Appenzell Innerrhoden", "Appenzell Rhodes-Intérieures", "Appenzello Interno"],
    "AR": ["Appenzell Ausserrhoden", "Appenzell Rhodes-Extérieures", "Appenzello Esterno"],
    "BE": ["Bern", "Berne", "Berna"],
    "BL": ["Basel-Landschaft", "Basel-Land", "Bâle-Campagne", "Basilea Campagna"],
    "BS": ["Basel-Stadt", "Bâle-Ville", "Basilea Città"],
    "FR": ["Freiburg", "Fribourg", "Friburgo"],
    "GE": ["Genf", "Genève", "Geneva", "Ginevra"],
    "GL": ["Glarus", "Glaris", "Glarona"],
    "GR": ["Graubünden", "Grisons", "Grigioni", "Grischun"],
    "JU": ["Jura", "Giura"],
    "LU": ["Luzern", "Lucerne", "Lucerna"],
    "NE": ["Neuenburg", "Neuchâtel"],
    "NW": ["Nidwalden", "Nidwald", "Nidvaldo"],
    "OW": ["Obwalden", "Obwald", "Obvaldo"],
    "SG": ["St. Gallen", "Sankt Gallen", "Saint-Gall", "San Gallo"],
    "SH": ["Schaffhausen", "Schaffhouse", "Sciaffusa"],
    "SO": ["Solothurn", "Soleure", "Soletta"],
    "SZ": ["Schwyz", "Schwytz", "Svitto"],
    "TG": ["Thurgau", "Thurgovie", "Turgovia"],
    "TI": ["Tessin", "Ticino"],
    "UR": ["Uri"],
    "VD": ["Waadt", "Vaud"],
    "VS": ["Wallis", "Valais", "Vallese"],
    "ZG": ["Zug", "Zoug", "Zugo"],
    "ZH": ["Zürich", "Zurich", "Zurigo"],
}
COUNTRY_WORDS = {"suisse", "switzerland", "schweiz", "svizzera", "ch", "non defini"}
# A locality may spill into a neighbouring municipality or canton (Avenches: 99% VD,
# 1% FR). The candidate holding at least this share of the addresses wins.
MAJORITY = 0.8


def canton_code(name: str) -> str | None:
    return _CANTON_NAMES.get(norm(name))


def norm(text: str) -> str:
    """Spelling-insensitive key: Zürich, Zurich and Zuerich all give "zurich"."""
    s = text.lower()
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ae", "a"), ("oe", "o"), ("ue", "u")):
        s = s.replace(a, b)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\bsainte\b", "ste", s)
    return re.sub(r"\bsaint\b", "st", s)


_CANTON_NAMES = {norm(n): code for code, names in CANTON_NAMES_BY_CODE.items() for n in names}


@dataclass(frozen=True)
class Place:
    name: str
    canton: str
    e: float
    n: float

    def km_to(self, other: "Place") -> float:
        return math.dist((self.e, self.n), (other.e, other.n)) / 1000


@dataclass
class Resolution:
    status: str  # "ok", "unknown" (deliberately no point) or "unresolved" (needs a mapping)
    places: list[Place] = field(default_factory=list)
    note: str = ""


def _strip_canton_suffix(name: str) -> str:
    """'Romont FR' / 'Romont (FR)' -> 'Romont'."""
    return re.sub(r"\s*\(?\b(%s)\)?$" % "|".join(CANTONS), "", name).strip()


class Places:
    def __init__(self, register_path: str, places_path: str | None = None):
        self._localities: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
        self._municipalities: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
        self._postcodes: dict[str, list] = defaultdict(list)
        self._by_canton: dict[str, set] = defaultdict(set)
        with open(register_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                row = (float(r["E"]), float(r["N"]), _share(r["Adressenanteil"]))
                locality = re.sub(r"\s+\d+$", "", r["Ortschaftsname"])  # "Lausanne 25" -> "Lausanne"
                key = (locality, r["Kantonskürzel"])
                for k in {norm(locality), norm(_strip_canton_suffix(locality))}:
                    self._localities[k][key].append(row)
                muni = (r["Gemeindename"], r["Kantonskürzel"])
                self._municipalities[norm(_strip_canton_suffix(r["Gemeindename"]))][muni].append(row)
                self._postcodes[r["PLZ4"]].append((key, row[2]))
                self._by_canton[r["Kantonskürzel"]].add(key)
        self._points: dict[tuple, Place] = {}

        cfg = {}
        if places_path:
            with open(places_path, "rb") as f:
                cfg = tomllib.load(f)
        self.aliases = {norm(k): v for k, v in cfg.get("aliases", {}).items()}
        self.regions = {norm(k): v for k, v in cfg.get("regions", {}).items()}
        self.ignore = {norm(s) for s in cfg.get("ignore", [])}
        self._cache: dict[str, Resolution] = {}

    # --- register lookups -------------------------------------------------------------

    def _place(self, key: tuple, rows: list) -> Place:
        if key not in self._points:
            self._points[key] = Place(key[0], key[1], sum(r[0] for r in rows) / len(rows),
                                      sum(r[1] for r in rows) / len(rows))
        return self._points[key]

    def _pick(self, candidates: dict[tuple, list], canton: str | None) -> tuple[Place | None, str]:
        if canton:
            candidates = {k: v for k, v in candidates.items() if k[1] == canton}
        if not candidates:
            return None, "not in register"
        shares = {k: sum(r[2] for r in rows) for k, rows in candidates.items()}
        best = max(shares, key=shares.get)
        if len(candidates) > 1 and shares[best] < MAJORITY * sum(shares.values()):
            names = ", ".join(sorted(f"{k[0]} ({k[1]})" for k in candidates))
            return None, f"ambiguous: {names}"
        return self._place(best, candidates[best]), ""

    def locality(self, name: str, canton: str | None = None) -> tuple[Place | None, str]:
        """A single named locality. Municipality names are only used together with a
        canton code: on its own, "Riviera" would match the Ticino municipality."""
        key = norm(name)
        if key in self._localities:
            return self._pick(self._localities[key], canton)
        if canton and key in self._municipalities:
            return self._pick(self._municipalities[key], canton)
        return None, "not in register"

    def canton(self, code: str) -> list[Place]:
        return [self._place(k, self._localities[norm(k[0])][k]) for k in sorted(self._by_canton[code])]

    def postcode(self, plz: str) -> Place | None:
        entries = self._postcodes.get(plz)
        if not entries:
            return None
        key = max(entries, key=lambda e: e[1])[0]  # the locality holding most of the postcode
        return self._place(key, self._localities[norm(key[0])][key])

    # --- job location strings -----------------------------------------------------------

    def resolve(self, raw: str) -> Resolution:
        if raw not in self._cache:
            self._cache[raw] = self._resolve(raw)
        return self._cache[raw]

    def _resolve(self, raw: str) -> Resolution:
        if norm(raw) in self.ignore:
            return Resolution("unknown", note="ignored in places.toml")
        parts = [p.strip() for p in re.split(r",| - ", raw) if p.strip()]
        canton = next((p.upper() for p in parts if p.upper() in CANTONS), None)
        names = [p for p in parts if not p.isdigit() and p.upper() not in CANTONS
                 and norm(p) not in COUNTRY_WORDS]
        if not names:
            if canton:
                return Resolution("ok", self.canton(canton), f"canton {canton}")
            return Resolution("unknown", note="country only")
        codes = [canton_code(n) for n in names]
        mapped = norm(raw) in self.regions or norm(raw) in self.aliases
        if len(names) > 1 and all(codes) and not mapped:
            # Several parts, all canton names: "Berne, Argovie, Soleure, Zurich"
            return self._cantons(codes)
        # The first remaining part is the place; later ones are districts ("Vevey,
        # Riviera-Pays-d'Enhaut, Suisse") and are ignored.
        res = self._resolve_name(names[0], canton, raw)
        if res.status == "unresolved" and len(names) == 1 and codes[0]:
            # A lone canton name that is not also a town: "Graubünden", "Jura"
            return self._cantons(codes)
        return res

    def _cantons(self, codes: list[str]) -> Resolution:
        unique = list(dict.fromkeys(codes))
        places = [p for code in unique for p in self.canton(code)]
        return Resolution("ok", places, f"canton{'s' if len(unique) > 1 else ''} {', '.join(unique)}")

    def _resolve_name(self, name: str, canton: str | None, raw: str) -> Resolution:
        for key in (norm(raw), norm(name)):  # a full-string mapping beats a name mapping
            if key in self.regions:
                return self._region(name, self.regions[key])
            if key in self.aliases:
                place, why = self.locality(self.aliases[key], canton)
                if place:
                    return Resolution("ok", [place], f"alias for {self.aliases[key]}")
                return Resolution("unresolved", note=f"alias target {self.aliases[key]!r}: {why}")
        place, why = self.locality(name, canton)
        if place:
            return Resolution("ok", [place])
        return Resolution("unresolved", note=why)

    def _region(self, name: str, members: list[str]) -> Resolution:
        places, bad = [], []
        for m in members:
            place, why = self.locality(m)
            if place:
                places.append(place)
            else:
                bad.append(f"{m} ({why})")
        if bad:
            return Resolution("unresolved", places, f"region {name}: unknown members {', '.join(bad)}")
        return Resolution("ok", places, f"region {name} ({len(places)} localities)")

    def resolve_home(self, text: str) -> Place:
        """Starting point: a postcode ("1020") or a locality ("Renens VD")."""
        text = text.strip()
        place = self.postcode(text) if text.isdigit() else self.locality(text)[0]
        if not place:
            raise ValueError(f"Starting point {text!r} not found in the register")
        return place


def _share(value: str) -> float:
    try:
        return float(value.replace("%", "").strip())
    except ValueError:
        return 0.0


def nearest(home: Place, places: list[Place]) -> tuple[float, Place] | None:
    if not places:
        return None
    best = min(places, key=home.km_to)
    return home.km_to(best), best


def location_strings(location: str | None) -> list[str]:
    """A job's location field, split into its locations ("A / B")."""
    return [s.strip() for s in (location or "").split(" / ") if s.strip()]


@dataclass(frozen=True)
class Match:
    km: float
    place: Place
    via: str  # e.g. "cantons BE, AG" when the place stands for a wider area, else ""

    @property
    def label(self) -> str:
        return f"{self.place.name}, via {self.via}" if self.via else self.place.name


def distance_to_job(places: "Places", home: Place, location: str | None) -> Match | None:
    """Nearest of the job's locations, or None when none of them has a point."""
    # Remember which location string each place came from, so a canton- or
    # region-wide match is shown as such rather than as a specific town
    origin: dict[Place, str] = {}
    for raw in location_strings(location):
        res = places.resolve(raw)
        for place in res.places:
            origin.setdefault(place, res.note if len(res.places) > 1 else "")
    hit = nearest(home, list(origin))
    return Match(hit[0], hit[1], origin[hit[1]]) if hit else None
