import unittest

from jobseeker.crawler.sources.cornerstone import CornerstoneSource, iso_date, page_context

BASE = "https://portal.example.test"
CLOUD = "https://xx.api.example.test/"
HOME = BASE + "/ux/ats/careersite/1/home?c=acme"
SEARCH = CLOUD + "rec-job-search/external/jobs"
DETAIL = BASE + "/services/x/job-requisition/v2/requisitions/{}/jobDetails?cultureId=2"
PAGE = ('<html><script>if (!csod.context  || !csod.context.token)  csod.context={"corp":"acme","token":"TKN",'
        '"endpoints":{"cloud":"' + CLOUD + '","api":"/"},"nested":{"a":{"b":1}}};</script></html>')


def req(rid, title, *places, date="19/11/2026"):
    """A requisition shaped like Cornerstone's, with made-up content."""
    return {"requisitionId": rid, "displayJobTitle": title, "postingEffectiveDate": date,
            "locations": [{"city": c, "state": None, "country": cc} for c, cc in places],
            "externalDescription": "plain text"}


def results(reqs, total):
    return {"status": "Success", "data": {"totalCount": total, "requisitions": reqs}}


class FakeClient:
    def __init__(self, pages, searches):
        self.pages, self.searches, self.calls = pages, list(searches), []

    def get_text(self, url):
        self.calls.append(("GET", url, None))
        return self.pages[url]

    def get_json(self, url, headers=None):
        self.calls.append(("GET", url, headers))
        return self.pages[url]

    def post_json(self, url, payload, headers=None):
        self.calls.append(("POST", url, headers, payload["pageNumber"], payload["countryCodes"]))
        assert url == SEARCH
        return self.searches.pop(0)


def source(client):
    return CornerstoneSource(client, base_url=BASE + "/", corp="acme", crawl_delay=0)


class CornerstoneTests(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(iso_date("19/11/2026"), "2026-11-19")
        self.assertEqual(iso_date("3/9/2026"), "2026-09-03")
        self.assertEqual(iso_date("-"), "")

    def test_page_context(self):
        self.assertEqual(page_context(PAGE)["endpoints"]["cloud"], CLOUD)
        with self.assertRaises(RuntimeError):
            page_context("<html>Maintenance</html>")

    def test_listing_uses_the_token_pages_and_checks_the_country(self):
        page_1 = [req(i, f"Poste fictif {i}", ("Genève", "CH")) for i in range(1, 25)] + \
                 [req(25, "Analyste fictif", ("Madrid", "ES"))]   # despite the filter
        client = FakeClient({HOME: PAGE}, [results(page_1, 27),
                                           results([req(26, "​ Chef  fictif ", ("Madrid", "ES"), ("Genève", "CH")),
                                                    req(27, "Expert fictif", ("Genève", "CH"), date="3/9/2026")], 27)])
        refs = list(source(client).list_jobs())
        self.assertEqual([c[:5] for c in client.calls], [
            ("GET", HOME, None),
            ("POST", SEARCH, {"Authorization": "Bearer TKN"}, 1, ["ch"]),
            ("POST", SEARCH, {"Authorization": "Bearer TKN"}, 2, ["ch"]),
        ])
        self.assertEqual(len(refs), 26)
        self.assertNotIn("25", [r.job_id for r in refs])
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on, r.url) for r in refs[-2:]], [
            ("26", "Chef fictif", "Genève, CH / Madrid, ES", "2026-11-19", BASE + "/ux/ats/careersite/1/home/requisition/26?c=acme"),
            ("27", "Expert fictif", "Genève, CH", "2026-09-03", BASE + "/ux/ats/careersite/1/home/requisition/27?c=acme"),
        ])

    def test_no_results(self):
        self.assertEqual(list(source(FakeClient({HOME: PAGE}, [results([], 0)])).list_jobs()), [])

    def test_detail_has_the_ad(self):
        client = FakeClient({HOME: PAGE, DETAIL.format(7): {"data": [{
            "displayTitle": "Expert  fictif", "ref": "req7", "openDate": "2026-11-17T14:52:23",
            "externalDescription": "<h2>Votre équipe</h2><p>Analyser des <b>données</b> fictives.</p><ul><li>Rigueur</li></ul>",
            "primaryLocation": {"title": "Genève", "city": "Genève", "country": "CH", "postalCode": "1215", "geocode": {}},
            "companyApplyUrl": BASE + "/ux/ats/careersite/1/home/requisition/7?c=acme"}]}},
            [results([req(7, "Expert fictif", ("Genève", "CH"))], 1)])
        src = source(client)
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual(client.calls[-1], ("GET", DETAIL.format(7), {"Authorization": "Bearer TKN"}))
        self.assertIn("Analyser des données fictives.", d.description)
        self.assertIn("- Rigueur", d.description)
        self.assertEqual((d.title, d.url), ("Expert fictif", BASE + "/ux/ats/careersite/1/home/requisition/7?c=acme"))
        self.assertEqual(d.raw["primary_location"], {"title": "Genève", "city": "Genève", "country": "CH", "postalCode": "1215"})

    def test_detail_without_a_description_is_an_error(self):
        client = FakeClient({HOME: PAGE, DETAIL.format(7): {"data": [{"displayTitle": "Expert fictif"}]}},
                            [results([req(7, "Expert fictif", ("Genève", "CH"))], 1)])
        src = source(client)
        with self.assertRaises(RuntimeError):
            src.fetch_detail(next(src.list_jobs()))

    def test_requests_to_the_site_are_spaced(self):
        client = FakeClient({HOME: PAGE, DETAIL.format(7): {"data": [{"externalDescription": "<p>x</p>"}]}},
                            [results([req(7, "Expert fictif", ("Genève", "CH"))], 1)])
        src = CornerstoneSource(client, base_url=BASE, corp="acme", crawl_delay=0.2)
        import time
        started = time.monotonic()
        src.fetch_detail(next(src.list_jobs()))
        self.assertGreaterEqual(time.monotonic() - started, 0.2)   # home page, then the detail
