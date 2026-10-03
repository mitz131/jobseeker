import unittest

from jobseeker.crawler.sources.vaudoise import VaudoiseSource


VAUDOISE_LISTING = """
<a href="https://vaudoise.softgarden.io/job/111"
   data-shared-job-id="111" data-static-filter-list-lang="DE"
   class="link--job-item" data-tui="job-1">
  <div class="col-9 h5">Publi&#233; le : 28 septembre 2026</div>
  <h2 class="h3 title-class" data-tui="job-title"> Brokerbetreuer/in (m/w/d) 100%</h2>
  <td data-tui="location"> Bern, BE </td>
</a>
<a href="https://vaudoise.softgarden.io/job/222" data-shared-job-id="222" data-tui="job-2">
  <h2 data-tui="job-title">Gestionnaire &amp; Analyste</h2><td data-tui="location">Lausanne, VD</td>
</a>
"""

VAUDOISE_DETAIL = """<script type="application/ld+json">{"@type": "JobPosting", "title": " Brokerbetreuer/in ",
"datePosted": "2026-09-28T16:14:56.836+02:00", "description": "<p>Hallo</p><ul><li>A</li></ul>"}</script>"""


class FakeVaudoiseClient:
    def get_text(self, url):
        return VAUDOISE_DETAIL if "softgarden" in url else VAUDOISE_LISTING


class VaudoiseTests(unittest.TestCase):
    def test_listing_with_multiline_attributes(self):
        refs = list(VaudoiseSource(FakeVaudoiseClient(), "https://www.vaudoise.ch/jobs").list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location) for r in refs],
                         [("111", "Brokerbetreuer/in (m/w/d) 100%", "Bern, BE"),
                          ("222", "Gestionnaire & Analyste", "Lausanne, VD")])
        self.assertEqual(refs[0].posted_on, "28 septembre 2026")

    def test_detail_from_json_ld(self):
        src = VaudoiseSource(FakeVaudoiseClient(), "https://www.vaudoise.ch/jobs")
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual((d.title, d.posted_on, d.description), ("Brokerbetreuer/in", "2026-09-28", "Hallo\n\n- A"))

    def test_empty_listing_is_an_error(self):
        class Empty:
            def get_text(self, url):
                return "<html>redesigned</html>"
        with self.assertRaises(RuntimeError):
            list(VaudoiseSource(Empty(), "https://www.vaudoise.ch/jobs").list_jobs())
