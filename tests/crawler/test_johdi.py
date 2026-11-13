import unittest

from jobseeker.crawler.sources.johdi import JohdiSource

OFFERS = [{"id": 4876, "title": " Senior Compliance Officer ", "city": "Genève", "work_place": "Genève",
           "publication_date": "2026-11-09", "introduction": "<p>Generic intro</p>"},
          {"id": 4591, "title": "Data Analyst", "city": None, "work_place": "Nyon", "publication_date": "2026-09-16"}]
DETAIL = {"id": 4876, "title": "Senior Compliance Officer", "description": "<p>Votre mission</p><ul><li>A</li></ul>",
          "publication_date": "2026-11-09", "country_code": "ch"}


class FakeClient:
    def __init__(self):
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return OFFERS if url.endswith("/offers/fr") else DETAIL


class JohdiTests(unittest.TestCase):
    def source(self):
        return JohdiSource(FakeClient(), "https://ats.example/api/company/TOKEN/publicationFlows/web/",
                           job_url="https://bank.example/offre-emploi?offer={id}")

    def test_listing(self):
        refs = list(self.source().list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on, r.url) for r in refs],
                         [("4876", "Senior Compliance Officer", "Genève", "2026-11-09", "https://bank.example/offre-emploi?offer=4876"),
                          ("4591", "Data Analyst", "Nyon", "2026-09-16", "https://bank.example/offre-emploi?offer=4591")])

    def test_detail(self):
        src = self.source()
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual(d.description, "Votre mission\n\n- A")
        self.assertEqual(src.client.urls[-1], "https://ats.example/api/company/TOKEN/publicationFlows/web/offer/4876/fr")

    def test_unexpected_response_is_an_error(self):
        src = self.source()
        src.client.get_json = lambda url: {"message": "Server Error"}
        with self.assertRaises(RuntimeError):
            list(src.list_jobs())
