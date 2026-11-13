import unittest

from jobseeker.crawler.sources.sfcareer import SFCareerSource, job_place

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<Job-Listing>
 <Job><JobTitle><![CDATA[Equity Analyst]]></JobTitle><Job-Description><![CDATA[<p>Hello</p>]]></Job-Description>
  <ReqId><![CDATA[1]]></ReqId><filter1><![CDATA[]]></filter1></Job>
 <Job><JobTitle><![CDATA[Internal Auditor (m/f/d)]]></JobTitle><Job-Description><![CDATA[<p>Hallo</p>]]></Job-Description>
  <ReqId><![CDATA[2]]></ReqId></Job>
 <Job><JobTitle><![CDATA[Safekeeping &amp; Cash Desk]]></JobTitle><Job-Description><![CDATA[<p>Grüezi</p>]]></Job-Description>
  <ReqId><![CDATA[3]]></ReqId></Job>
</Job-Listing>"""


def header(req_id, country, city):
    return (f"<div tabindex=\"0\">Requisition ID&nbsp;<b>{req_id}</b>&nbsp;-&nbsp;Posted&nbsp;<b id='postedOnDate'></b>"
            f"&nbsp;-&nbsp;<b>{country}</b>&nbsp;-&nbsp;<b>{city}</b>&nbsp;-&nbsp;(Area)&nbsp;-&nbsp;<b>Experienced</b></div>")


PAGES = {"1": header(1, "Switzerland", "Geneva"), "2": header(2, "Germany", "Frankfurt"),
         "3": header(3, "Switzerland", "Zurich")}


class FakeClient:
    def __init__(self, pages=PAGES):
        self.pages = pages

    def get_text(self, url):
        if "resultType=XML" in url:
            return FEED
        return self.pages.get(url.rsplit("=", 1)[1], "<html>no header</html>")


class SFCareerTests(unittest.TestCase):
    def source(self, client=None):
        return SFCareerSource(client or FakeClient(), "https://career012.example/", "acme", country="Switzerland")

    def test_keeps_the_country_from_the_job_pages(self):
        refs = list(self.source().list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location) for r in refs],
                         [("1", "Equity Analyst", "Geneva, Switzerland"), ("3", "Safekeeping & Cash Desk", "Zurich, Switzerland")])
        self.assertEqual(refs[0].url, "https://career012.example/career?company=acme&career_ns=job_listing&career_job_req_id=1")

    def test_detail_comes_from_the_feed(self):
        src = self.source()
        d = src.fetch_detail(list(src.list_jobs())[1])
        self.assertEqual((d.description, d.raw["ReqId"]), ("Grüezi", "3"))

    def test_a_page_without_location_is_skipped(self):
        refs = list(self.source(FakeClient({"1": header(1, "Switzerland", "Geneva")})).list_jobs())
        self.assertEqual([r.job_id for r in refs], ["1"])

    def test_no_page_with_a_location_is_an_error(self):
        with self.assertRaises(RuntimeError):
            list(self.source(FakeClient({})).list_jobs())

    def test_job_place(self):
        self.assertEqual(job_place(header(9, "Hong Kong", "Hong Kong")), ("Hong Kong", "Hong Kong"))
