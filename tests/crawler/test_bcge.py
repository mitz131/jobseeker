import unittest

from jobseeker.crawler.sources.bcge import BCGESource

# Shaped like the portal's JSON response, with made-up content; the internal fields the real offers also carry are some of them
OFFERS = {"nbOfOffersPerPage": 6, "filters": [], "offers": [
    {"id": 901, "requisitionId": 5, "reference": "5-internal", "title": "Analyste fictif ",
     "content": '<?xml encoding="UTF-8"><div><p>Rejoignez l&rsquo;&eacute;quipe.</p><h2>Vos missions</h2>'
                "<ul><li>Analyser</li><li>Rapporter</li></ul></div>",
     "uri": "https://jobs.example.test/en/our-offers/analyste-fictif-901", "dateFrom": "2026-11-11T00:00:00+01:00",
     "job": {"id": 3}, "similarOffers": [],
     "information": [{"id": "lieu-travail", "value": "Geneva"}, {"id": "taux-occupation", "value": "80 %"}],
     "googleJobsJson": '{"jobLocation": {"address": {"addressLocality": "Gen\\u00e8ve"}}}'},
    {"id": 902, "title": "Spécialiste fictif", "content": "<p>Texte</p>", "uri": "https://jobs.example.test/902",
     "dateFrom": "2026-10-19T00:00:00+02:00", "googleJobsJson": "",
     "information": [{"id": "lieu-travail", "value": "Lausanne", "filterValue": "lausanne"}]},
    {"id": 903, "title": "Foreign one", "content": "<p>x</p>", "uri": "u3", "dateFrom": "2026-10-19T00:00:00+02:00",
     "googleJobsJson": "", "information": [{"id": "lieu-travail", "value": "Dubai", "filterValue": "dubai"}]},
    {"id": 904, "title": "Foreign two", "content": "<p>x</p>", "uri": "u4", "dateFrom": "2026-10-19T00:00:00+02:00",
     "googleJobsJson": '{"jobLocation": {"address": {"addressLocality": "Somewhere", "addressCountry": "AE"}}}',
     "information": []},
]}


class FakeClient:
    def __init__(self, data=OFFERS):
        self.urls, self.data = [], data

    def get_json(self, url):
        self.urls.append(url)
        return self.data


class BCGETests(unittest.TestCase):
    def test_listing_is_swiss_only(self):   # Foreign one/two (Dubai, AE) are skipped
        self.assertEqual([r.job_id for r in BCGESource(FakeClient()).list_jobs()], ["901", "902"])

    def test_listing(self):
        src = BCGESource(FakeClient())
        refs = list(src.list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on, r.url) for r in refs],
                         [("901", "Analyste fictif", "Genève", "2026-11-11",
                           "https://jobs.example.test/en/our-offers/analyste-fictif-901"),
                          ("902", "Spécialiste fictif", "Lausanne", "2026-10-19", "https://jobs.example.test/902")])

    def test_detail_is_built_from_the_listing_without_internal_fields(self):
        src = BCGESource(FakeClient())
        refs = list(src.list_jobs())
        d = src.fetch_detail(refs[0])
        self.assertEqual(len(src.client.urls), 1)   # no detail request
        for internal in ("requisitionId", "reference", "job", "similarOffers"):
            self.assertNotIn(internal, d.raw)
        self.assertFalse(d.description_html.startswith("<?xml"))
        self.assertTrue(d.description.startswith("Rejoignez l’équipe."))
        self.assertIn("- Analyser", d.description)

    def test_unexpected_response_is_an_error(self):
        src = BCGESource(FakeClient({"error": "nope"}))
        with self.assertRaises(RuntimeError):
            list(src.list_jobs())
