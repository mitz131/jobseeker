import json
import unittest

from jobseeker.crawler.sources.radancy import RadancySource, swiss_locations

LOCATION_URL = "https://careers.example.test/en/location/switzerland-jobs/1/2658434/2"


def item(job_id, title, place):
    return (f'<li><a data-job-id="{job_id}" href="/en/job/geneva/{title.lower().replace(" ", "-")}/1/{job_id}">'
            f'<h3>{title}</h3><span class="job-location">{place}</span></a></li>')


def location_page(items, pages=1):
    """Shaped like the site's location page, with made-up jobs."""
    return (f'<html><body><nav><a data-job-id="x" href="/en/saved-jobs">Saved</a></nav>'
            f'<section id="search-results" data-total-pages="{pages}" data-total-results="{len(items)}">'
            f'<ul>{"".join(items)}</ul></section></body></html>')


PAGE = location_page([
    item("901", "Trader fictif", "Geneva, Switzerland"),
    item("902", "Analyste fictif", "Geneva, Switzerland |  Schiphol, Netherlands"),
])
DETAIL = ('<html><head><script type="application/ld+json">' + json.dumps({
    "@context": "https://schema.org", "@type": "JobPosting", "title": "Trader fictif ",
    "datePosted": "2026-10-05", "description": "<div class='description'><p>Négocier.</p><ul><li>Pétrole</li></ul></div>",
    "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Geneva", "addressCountry": "Switzerland"}}],
}) + '</script></head><body></body></html>')


class FakeClient:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


class RadancyTests(unittest.TestCase):
    def test_swiss_locations(self):
        self.assertEqual(swiss_locations("Geneva, Switzerland |  Schiphol, Netherlands"), "Geneva")
        self.assertEqual(swiss_locations("Geneva, Switzerland | Zug, Switzerland"), "Geneva / Zug")
        self.assertEqual(swiss_locations("Schiphol, Netherlands"), "")

    def test_listing(self):
        refs = list(RadancySource(FakeClient({LOCATION_URL: PAGE}), location_url=LOCATION_URL).list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location, r.url) for r in refs], [
            ("901", "Trader fictif", "Geneva", "https://careers.example.test/en/job/geneva/trader-fictif/1/901"),
            ("902", "Analyste fictif", "Geneva", "https://careers.example.test/en/job/geneva/analyste-fictif/1/902"),
        ])   # the "Saved" link outside the results block isn't a job

    def test_no_jobs_is_not_an_error(self):
        client = FakeClient({LOCATION_URL: location_page([], pages=0)})
        self.assertEqual(list(RadancySource(client, location_url=LOCATION_URL).list_jobs()), [])

    def test_several_pages_fail_loudly(self):
        client = FakeClient({LOCATION_URL: location_page([item("901", "Trader fictif", "Geneva, Switzerland")], pages=2)})
        with self.assertRaisesRegex(RuntimeError, "2 pages"):
            list(RadancySource(client, location_url=LOCATION_URL).list_jobs())

    def test_changed_layout_is_an_error(self):
        client = FakeClient({LOCATION_URL: "<html><body>Maintenance</body></html>"})
        with self.assertRaises(RuntimeError):
            list(RadancySource(client, location_url=LOCATION_URL).list_jobs())

    def test_detail_from_json_ld(self):
        job_url = "https://careers.example.test/en/job/geneva/trader-fictif/1/901"
        src = RadancySource(FakeClient({LOCATION_URL: PAGE, job_url: DETAIL}), location_url=LOCATION_URL)
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual((d.title, d.posted_on), ("Trader fictif", "2026-10-05"))
        self.assertIn("Négocier.", d.description)
        self.assertIn("- Pétrole", d.description)
