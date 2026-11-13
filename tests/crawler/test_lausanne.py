import unittest
from urllib.parse import parse_qsl, urlsplit

from jobseeker.crawler.sources.lausanne import LausanneSource, day

# Shaped like the city's search hits, with made-up content; the internal fields the
# real hits also carry (authors, comments) are represented by two of them
HITS = {"hits": {"total": {"value": 2}, "hits": [
    {"_id": "pj100", "_source": {
        "title": "cheffe ou chef de projets SI ", "ville": None, "label_full": "Service d'organisation et d'informatique",
        "pub_date": 1794524400, "post_date": 1796338800, "start_tbd": 1, "ratio_min": 80, "ratio_max": 100,
        "duration": "Contrat de durée indéterminée ", "ext_data": "Le service gère l'informatique.$Vous aimez <les> défis ?",
        "mission": "Piloter des projets$Coordonner les équipes", "profile": "Master en informatique$Esprit d'équipe",
        "author_name": "Internal Person", "author_comment": "internal note"}},
    {"_id": "pj101", "_source": {"title": "électricienne ou électricien de réseau", "ville": "Renens ",
                                 "pub_date": 1794438000, "ratio_min": 100, "ratio_max": 100, "immediate": 1}},
]}}


class FakeClient:
    def __init__(self):
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return HITS


class LausanneTests(unittest.TestCase):
    def test_listing(self):
        src = LausanneSource(FakeClient())
        refs = list(src.list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on) for r in refs],
                         [("pj100", "Cheffe ou chef de projets SI", "Lausanne", "2026-11-13"),
                          ("pj101", "Électricienne ou électricien de réseau", "Renens", "2026-11-12")])
        self.assertTrue(refs[0].url.endswith("/detail-offre-emploi/pj100.html"))
        query = parse_qsl(urlsplit(src.client.urls[0]).query)
        self.assertIn(("el_index", "emploi"), query)
        self.assertEqual([v for k, v in query if k == "values[]"], ["1", "2", "3"])

    def test_detail_is_built_from_the_listing_without_internal_fields(self):
        src = LausanneSource(FakeClient())
        refs = list(src.list_jobs())
        d = src.fetch_detail(refs[0])
        self.assertEqual(len(src.client.urls), 1)   # no detail request
        self.assertNotIn("author_name", d.raw)
        self.assertNotIn("author_comment", d.raw)
        self.assertIn("&lt;les&gt;", d.description_html)   # the site's text is escaped
        self.assertEqual(d.description.split("\n\n")[:3],
                         ["Service d'organisation et d'informatique", "Le service gère l'informatique.", "Vous aimez <les> défis ?"])
        self.assertIn("- Piloter des projets", d.description)
        self.assertIn("Taux : 80–100%", d.description)
        self.assertIn("Entrée en fonction : à convenir", d.description)
        self.assertIn("Délai de postulation : 2026-12-04", d.description)
        self.assertIn("Entrée en fonction : dès que possible", src.fetch_detail(refs[1]).description)

    def test_dates_are_local_days(self):
        self.assertEqual(day(1794524400), "2026-11-13")   # 2026-11-12 23:00 UTC = midnight in Lausanne
        self.assertEqual(day(None), "")

    def test_unexpected_response_is_an_error(self):
        src = LausanneSource(FakeClient())
        src.client.get_json = lambda url: {"error": "index not found"}
        with self.assertRaises(RuntimeError):
            list(src.list_jobs())
