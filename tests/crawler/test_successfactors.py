import unittest

from jobseeker.crawler.html_text import html_to_text
from jobseeker.crawler.sources.successfactors import SuccessFactorsSource, extract_description, page_locations


SF_LISTING = """
<span class="paginationLabel">Results <b>1 &ndash; 2</b> of <b>2</b></span>
<tr class="data-row">
  <a href="/job/Vevey-Data-Engineer/1111111/" class="jobTitle-link">Data Engineer</a>
  <span class="jobLocation">Vevey, CH</span><span class="jobDate">Sep 30, 2026</span>
</tr>
<tr class="data-row">
  <a href="/job/York-QA-Lead/2222222/" class="jobTitle-link">QA &amp; Test Lead</a>
  <span class="jobLocation">York, GB</span>
</tr>
"""

SF_DETAIL = """<html><body><div class="header">x</div>
<span class="jobdescription"><p>About the role</p><ul><li>Python</li><li>SQL</li></ul>
<div><br/>Nested</div></span><footer>Footer</footer></body></html>"""


class FakeSFClient:
    def get_text(self, url):
        return SF_LISTING if "/search/" in url else SF_DETAIL


class SuccessFactorsTests(unittest.TestCase):
    def test_listing(self):
        src = SuccessFactorsSource(FakeSFClient(), "https://jobs.example.com")
        refs = list(src.list_jobs())
        self.assertEqual([r.job_id for r in refs], ["1111111", "2222222"])
        self.assertEqual(refs[1].title, "QA & Test Lead")
        self.assertEqual(refs[0].location, "Vevey, CH")
        self.assertEqual(refs[0].url, "https://jobs.example.com/job/Vevey-Data-Engineer/1111111/")

    def test_description_stops_at_its_own_closing_tag(self):
        html = extract_description(SF_DETAIL)
        self.assertIn("Nested", html)
        self.assertNotIn("Footer", html)
        self.assertEqual(html_to_text(html), "About the role\n\n- Python\n- SQL\n\nNested")

    def test_all_locations_from_job_page(self):
        block = ('<p id="job-location" class="jobLocation"> <span class="jobGeoLocation">La Tour-de-Peilz, CH </span> '
                 '<span class="jobGeoLocation"> <span class="jobGeoLocationPin glyphicon"></span>Zürich, CH </span> '
                 '<span class="jobGeoLocation">Basel, CH</span></p>')
        self.assertEqual(page_locations(block * 2), "La Tour-de-Peilz, CH / Zürich, CH / Basel, CH")
        self.assertEqual(page_locations("<p>no locations</p>"), "")

    def test_page_without_description_is_an_error(self):
        class Withdrawn:
            def get_text(self, url):
                return SF_LISTING if "/search/" in url else "<html><title>Job Details</title></html>"
        src = SuccessFactorsSource(Withdrawn(), "https://jobs.example.com")
        with self.assertRaises(ValueError):
            src.fetch_detail(next(src.list_jobs()))

    def test_duplicate_description_copies_are_stored_once(self):
        page = '<span itemprop="description"><p>Same</p></span>' * 2
        self.assertEqual(html_to_text(extract_description(page)), "Same")

    def test_description_blocks_with_unclosed_br_are_kept(self):
        page = ('<span itemprop="description"><p>Intro</p></span>'
                '<span itemprop="description"><div><p>Role<br><br>Details</p></div></span>'
                '<span itemprop="description">Profil</span><footer>x</footer>')
        self.assertEqual(html_to_text(extract_description(page)), "Intro\n\nRole\n\nDetails\n\nProfil")
