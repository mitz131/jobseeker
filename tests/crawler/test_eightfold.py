import unittest

from jobseeker.crawler.sources.eightfold import EightfoldSource, place

BASE = "https://careers.example.test"
SEARCH = BASE + "/api/pcsx/search?domain=example.com&query=&location=Switzerland&start={}"
CAREERS = BASE + "/careers?location=Switzerland"
DETAIL = BASE + "/api/pcsx/position_details?position_id={}&domain=example.com&hl=en"


def position(pid, name, locations, standardized, ts=1794936234):
    """A position shaped like Eightfold's, with made-up content."""
    return {"id": pid, "displayJobId": f"D{pid}", "name": f" {name} ", "locations": locations,
            "standardizedLocations": standardized, "postedTs": ts, "department": "Fictional dept",
            "workLocationOption": "onsite", "positionUrl": f"/careers/job/{pid}"}


def page(positions, count):
    return {"status": 200, "data": {"positions": positions, "count": count}}


ZURICH = position(101, "Ingénieur fictif", ["Switzerland, Zürich, Zürich"], ["Zürich, ZH, CH"])
ANYWHERE_CH = position(102, "Conseiller fictif", ["Switzerland, Multiple Locations, Multiple Locations"], ["CH"])
GERMANY = position(103, "Analyst fictif", ["Germany, Berlin, Berlin"], ["Berlin, BE, DE"])
BOTH = position(104, "Architecte fictif", ["Germany, Multiple Locations, Multiple Locations",
                                           "Switzerland, Geneva, Geneva"], ["DE", "Geneva, GE, CH"])


class FakeClient:
    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def get_text(self, url):
        self.urls.append(url)
        assert url == CAREERS, url
        return "<html>career site</html>"

    def get_json(self, url):
        self.urls.append(url)
        return self.answers[url]


def source(client):
    return EightfoldSource(client, base_url=BASE + "/", domain="example.com")


class EightfoldTests(unittest.TestCase):
    def test_place(self):
        self.assertEqual(place("Switzerland, Zürich, Zürich"), "Zürich, Switzerland")
        self.assertEqual(place("Switzerland, Multiple Locations, Multiple Locations"), "Switzerland")
        self.assertEqual(place("Switzerland"), "Switzerland")

    def test_listing_pages_and_keeps_only_swiss_jobs(self):
        client = FakeClient({SEARCH.format(0): page([ZURICH, GERMANY], 3), SEARCH.format(2): page([BOTH], 3)})
        refs = list(source(client).list_jobs())
        # the career page first: it sets the visitor cookies the search expects
        self.assertEqual(client.urls, [CAREERS, SEARCH.format(0), SEARCH.format(2)])
        self.assertEqual([(r.job_id, r.title, r.location, r.url, r.posted_on) for r in refs], [
            ("101", "Ingénieur fictif", "Zürich, Switzerland", BASE + "/careers/job/101", "2026-11-17"),
            ("104", "Architecte fictif", "Geneva, Switzerland / Germany", BASE + "/careers/job/104", "2026-11-17"),
        ])   # 103 is only in Germany

    def test_no_results(self):
        self.assertEqual(list(source(FakeClient({SEARCH.format(0): page([], 0)})).list_jobs()), [])

    def test_detail_has_the_ad_and_the_facts(self):
        client = FakeClient({SEARCH.format(0): page([ANYWHERE_CH], 1), DETAIL.format(102): {"data": {
            **ANYWHERE_CH, "jobDescription": "<b>Overview</b><p>Conseiller <i>fictif</i>.</p><ul><li>Rigueur</li></ul>",
            "publicUrl": BASE + "/careers/job/102",
            "efcustomTextWorkSite": ["2 days / week in-office"], "efcustomTextRequiredTravel": ["Less than 25%"],
            "efcustomTextEmploymentType": ["Full-Time"], "efcustomTextEmpty": []}}})
        src = source(client)
        ref = next(src.list_jobs())
        self.assertEqual(ref.location, "Switzerland")
        d = src.fetch_detail(ref)
        self.assertIn("Conseiller fictif.", d.description)
        self.assertIn("- Rigueur", d.description)
        self.assertEqual(d.raw["facts"], {"WorkSite": "2 days / week in-office", "RequiredTravel": "Less than 25%",
                                          "EmploymentType": "Full-Time"})
        self.assertEqual((d.title, d.location, d.url), ("Conseiller fictif", "Switzerland", BASE + "/careers/job/102"))

    def test_detail_without_a_description_is_an_error(self):
        client = FakeClient({SEARCH.format(0): page([ZURICH], 1), DETAIL.format(101): {"data": {**ZURICH}}})
        src = source(client)
        with self.assertRaises(RuntimeError):
            src.fetch_detail(next(src.list_jobs()))
