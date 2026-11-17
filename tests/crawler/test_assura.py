import unittest
from datetime import date

from jobseeker.crawler.sources.assura import API, AssuraSource

TODAY = date(2026, 11, 17)

# Shaped like the CMS's jobAds response, with made-up content
ADS = [
    {"_id": "a1", "title": "Analyste fictif 80-100% ", "slug": "analyste-fictif-ls", "locations": ["Lausanne"],
     "region": "romande", "department": "informatique", "type": "employe", "rate_min": "80", "rate_max": "100",
     "publishStartDate": "2026-10-01", "publishEndDate": "2026-12-31"},
    {"_id": "a2", "title": "Gestionnaire fictif", "slug": "gestionnaire-fictif", "locations": ["Pully", "Zürich"],
     "publishStartDate": "2026-11-17", "publishEndDate": None},
    {"_id": "a3", "title": "Not yet", "slug": "later", "locations": ["Bern"],
     "publishStartDate": "2026-11-18", "publishEndDate": "2027-01-31"},
    {"_id": "a4", "title": "Expired", "slug": "gone", "locations": ["Basel"],
     "publishStartDate": "2026-01-01", "publishEndDate": "2026-11-16"},
]
DESCRIPTION = ("**Rejoindre l'équipe fictive.**\n<br>Alors, bienvenue!\n\n"
               "### Ce que tu fais\n\n- Analyser\n\n- Rapporter\n")   # blank line: a "loose" list


class FakeClient:
    def __init__(self, entries=ADS, detail=None):
        self.entries, self.detail, self.calls = entries, detail, []

    def post_json(self, url, payload, headers=None):
        self.calls.append((url, payload))
        if "_id" in payload["filter"]:
            return {"entries": [self.detail] if self.detail else [], "total": int(bool(self.detail))}
        return {"fields": {}, "entries": self.entries, "total": len(self.entries)}


class AssuraTests(unittest.TestCase):
    def test_listing_keeps_ads_inside_their_publish_window(self):
        refs = list(AssuraSource(FakeClient()).list_jobs(TODAY))
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on, r.url) for r in refs], [
            ("a1", "Analyste fictif 80-100%", "Lausanne", "2026-10-01",
             "https://www.assura.ch/fr/carriere/postes-a-pourvoir/analyste-fictif-ls"),
            ("a2", "Gestionnaire fictif", "Pully / Zürich", "2026-11-17",
             "https://www.assura.ch/fr/carriere/postes-a-pourvoir/gestionnaire-fictif"),
        ])

    def test_listing_asks_for_active_ads_without_descriptions(self):
        client = FakeClient()
        list(AssuraSource(client).list_jobs(TODAY))
        url, payload = client.calls[0]
        self.assertEqual(url, API)
        self.assertEqual(payload["filter"], {"active": True})
        self.assertNotIn("description", payload["fields"])

    def test_detail_renders_the_markdown(self):
        client = FakeClient(detail={"_id": "a1", "title": "Analyste fictif", "description": DESCRIPTION})
        src = AssuraSource(client)
        ref = next(src.list_jobs(TODAY))
        d = src.fetch_detail(ref)
        self.assertEqual(client.calls[1][1]["filter"], {"active": True, "_id": "a1"})
        self.assertIn("<strong>Rejoindre l'équipe fictive.</strong>", d.description_html)
        self.assertIn("<h3>Ce que tu fais</h3>", d.description_html)
        self.assertTrue(d.description.startswith("Rejoindre l'équipe fictive."))
        self.assertIn("Alors, bienvenue!", d.description)
        self.assertIn("- Analyser\n- Rapporter", d.description)   # one line per item
        self.assertNotIn("<p>", d.description_html.split("<ul>")[1])
        self.assertNotIn("**", d.description)

    def test_ad_gone_by_the_detail_request_is_an_error(self):
        src = AssuraSource(FakeClient())
        ref = next(src.list_jobs(TODAY))
        with self.assertRaises(RuntimeError):
            src.fetch_detail(ref)

    def test_unexpected_response_is_an_error(self):
        class Broken(FakeClient):
            def post_json(self, url, payload, headers=None):
                return {"error": "nope"}
        with self.assertRaises(RuntimeError):
            list(AssuraSource(Broken()).list_jobs(TODAY))
