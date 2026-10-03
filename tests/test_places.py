import os
import tempfile
import unittest

from jobseeker.places import Places, nearest, norm

HEADER = "Ortschaftsname;PLZ4;Zusatzziffer;ZIP_ID;Gemeindename;BFS-Nr;Kantonskürzel;Adressenanteil;E;N;Sprache;Validity"
ROWS = [
    # name, plz, municipality, canton, share, E, N
    ("Lausanne 25", "1000", "Lausanne", "VD", "100 %", 2538000, 1152000),
    ("Lausanne", "1004", "Lausanne", "VD", "100 %", 2538000, 1154000),
    ("Renens VD", "1020", "Renens (VD)", "VD", "100 %", 2534000, 1154000),
    ("Vevey", "1800", "Vevey", "VD", "100 %", 2554000, 1146000),
    ("Montreux", "1820", "Montreux", "VD", "100 %", 2560000, 1143000),
    ("Avenches", "1580", "Avenches", "VD", "98.984 %", 2570000, 1192000),
    ("Avenches", "1580", "Belmont-Broye", "FR", "1.016 %", 2571000, 1191000),
    ("Romont FR", "1680", "Romont (FR)", "FR", "100 %", 2560000, 1172000),
    ("Romont BE", "2538", "Romont (BE)", "BE", "100 %", 2595000, 1226000),
    ("Lodrino", "6527", "Riviera", "TI", "100 %", 2719000, 1129000),
    ("Palézieux", "1607", "Oron", "VD", "100 %", 2556000, 1155000),
    ("Zürich", "8001", "Zürich", "ZH", "100 %", 2683000, 1248000),
    ("Sion", "1950", "Sion", "VS", "100 %", 2594000, 1120000),
    ("Bern", "3011", "Bern", "BE", "100 %", 2600000, 1199000),
    ("Thun", "3600", "Thun", "BE", "100 %", 2614000, 1178000),
    ("Sierre", "3960", "Sierre", "VS", "100 %", 2607000, 1127000),
]
PLACES_TOML = '''
ignore = ["Cork, Ireland"]
[aliases]
"Berne" = "Bern"
"Romont" = "Romont FR"
[regions]
"Riviera" = ["Vevey", "Montreux"]
"Broken" = ["Vevey", "Nowhere"]
'''


class PlacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        reg, cfg = os.path.join(cls.tmp, "reg.csv"), os.path.join(cls.tmp, "places.toml")
        with open(reg, "w", encoding="utf-8-sig") as f:
            f.write(HEADER + "\n")
            for name, plz, muni, canton, share, e, n in ROWS:
                f.write(f"{name};{plz};0;0;{muni};0;{canton};{share};{e};{n};fr;2008-07-01\n")
        with open(cfg, "w") as f:
            f.write(PLACES_TOML)
        cls.p = Places(reg, cfg)

    def names(self, raw):
        return [(x.name, x.canton) for x in self.p.resolve(raw).places]

    def test_spelling_variants(self):
        self.assertEqual(norm("Zürich"), norm("Zurich"))
        self.assertEqual(norm("Zuerich"), norm("ZURICH"))
        for raw in ("Zürich", "Switzerland - Zurich", "Zuerich, ZH"):
            self.assertEqual(self.names(raw), [("Zürich", "ZH")], raw)

    def test_country_canton_postcode_and_district_parts_are_hints(self):
        self.assertEqual(self.names("Lausanne, Lausanne, Suisse"), [("Lausanne", "VD")])
        self.assertEqual(self.names("Vevey, VD, CH, 1800"), [("Vevey", "VD")])

    def test_majority_share_settles_spillover(self):
        self.assertEqual(self.names("Avenches, CH"), [("Avenches", "VD")])

    def test_genuinely_ambiguous_needs_alias(self):
        self.assertEqual(self.names("Romont, CH"), [("Romont FR", "FR")])  # via alias
        p = Places(os.path.join(self.tmp, "reg.csv"))  # without places.toml
        res = p.resolve("Romont, CH")
        self.assertEqual(res.status, "unresolved")
        self.assertIn("ambiguous", res.note)

    def test_municipality_only_with_canton_hint(self):
        # "Riviera" is also a Ticino municipality; without a region entry it must not match it
        p = Places(os.path.join(self.tmp, "reg.csv"))
        self.assertEqual(p.resolve("Riviera").status, "unresolved")
        self.assertEqual(p.resolve("Oron, VD").places[0].canton, "VD")

    def test_region_is_its_member_localities(self):
        self.assertEqual(self.names("Riviera"), [("Vevey", "VD"), ("Montreux", "VD")])
        res = self.p.resolve("Broken")
        self.assertEqual(res.status, "unresolved")
        self.assertIn("Nowhere", res.note)

    def test_canton_only_and_unknown(self):
        self.assertEqual(sorted(self.names("VS")), [("Sierre", "VS"), ("Sion", "VS")])
        self.assertEqual(self.p.resolve("Suisse").status, "unknown")
        self.assertEqual(self.p.resolve("Non-défini").status, "unknown")
        self.assertEqual(self.p.resolve("Cork, Ireland").status, "unknown")
        self.assertEqual(self.p.resolve("Weinsteinjoch, VD").status, "unresolved")

    def test_list_of_canton_names_is_those_cantons(self):
        self.assertEqual(sorted(self.names("Berne, Valais")),
                         [("Bern", "BE"), ("Romont BE", "BE"), ("Sierre", "VS"), ("Sion", "VS"), ("Thun", "BE")])
        self.assertEqual(self.p.resolve("Berne, Valais").note, "cantons BE, VS")
        self.assertEqual(sorted(self.names("Wallis")), [("Sierre", "VS"), ("Sion", "VS")])  # lone canton, not a town
        self.assertEqual(self.names("Zürich"), [("Zürich", "ZH")])   # lone name that is a town: the town
        self.assertEqual(self.names("Bern, Switzerland"), [("Bern", "BE")])
        self.assertEqual(self.names("Vevey, VD, CH, 1800"), [("Vevey", "VD")])

    def test_distance_is_to_nearest_place_and_zero_inside_region_or_canton(self):
        vevey, lausanne, sion = (self.p.resolve_home(h) for h in ("1800", "Lausanne", "Sion"))
        self.assertEqual(nearest(vevey, self.p.resolve("Riviera").places)[0], 0.0)
        self.assertEqual(nearest(sion, self.p.resolve("VS").places)[0], 0.0)
        km, place = nearest(lausanne, self.p.resolve("Riviera").places)
        self.assertEqual(place.name, "Vevey")
        # Lausanne = mean of its 2 rows (2538000, 1153000); Vevey (2554000, 1146000): sqrt(16² + 7²)
        self.assertAlmostEqual(km, 17.46, places=2)

    def test_home_lookup(self):
        self.assertEqual(self.p.resolve_home("1020").name, "Renens VD")
        with self.assertRaises(ValueError):
            self.p.resolve_home("Weinsteinjoch")


if __name__ == "__main__":
    unittest.main()
