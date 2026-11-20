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

SF_TILES = """
<span class="paginationLabel">Results <b>1 &ndash; 2</b> of <b>2</b></span>
<ul class="job-list">
<li class="job-tile" data-url="/job/Geneva-Risk-Oversight/1376710157/">
  <div class="sub-section-desktop">
    <a href="/job/Geneva-Risk-Oversight/1376710157/" class="jobTitle-link">Risk Oversight</a>
    <div class="section-field location"><span class="section-label">Location</span>
      <div>Geneva, Geneva, CH, CH 1211</div></div>
  </div>
  <div class="sub-section-mobile">
    <a href="/job/Geneva-Risk-Oversight/1376710157/" class="jobTitle-link">Risk Oversight</a>
    <div class="section-field location"><span class="section-label">Location</span>
      <div>Geneva, Geneva, CH, CH 1211</div></div>
  </div>
</li>
<li class="job-tile" data-url="/job/Zurich-Head-of-Compliance/1376709057/">
  <div class="sub-section-desktop">
    <a href="/job/Zurich-Head-of-Compliance/1376709057/" class="jobTitle-link">Head of Compliance</a>
    <div class="section-field location"><span class="section-label">Location</span>
      <div>Zurich, Zurich, CH, CH 8002</div></div>
  </div>
</li>
</ul>
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

    def test_listing_with_tiles(self):
        class TileClient:
            def get_text(self, url):
                return SF_TILES

        refs = list(SuccessFactorsSource(TileClient(), "https://jobs.example.com").list_jobs())
        self.assertEqual([r.job_id for r in refs], ["1376710157", "1376709057"])
        self.assertEqual([r.location for r in refs], ["Geneva, Geneva, CH, CH 1211", "Zurich, Zurich, CH, CH 8002"])
        self.assertEqual(refs[1].title, "Head of Compliance")

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


SITEMAP_BASE = "https://portal.example.test"
SITEMAP = f"""<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.google.com/schemas/sitemap/0.9">
<url><loc>{SITEMAP_BASE}/job/Lausanne-Stagiaire-fictif-VD/2001/</loc><lastmod>2026-11-14</lastmod></url>
<url><loc>{SITEMAP_BASE}/job/Lausanne-Stagiaire-fictif-VD/2002/</loc><lastmod>2026-11-14</lastmod></url>
<url><loc>{SITEMAP_BASE}/job/Lausanne-Fictional-Analyst-VD/2003/</loc><lastmod>2026-11-14</lastmod></url>
<url><loc>{SITEMAP_BASE}/content/About-us/?locale=en_GB</loc></url>
</urlset>"""


def sitemap_page(slug, req, locale, title, location="Lausanne, Switzerland"):
    """A job page shaped like the newer SuccessFactors sites', with made-up content."""
    return f"""<html><head><link rel="canonical" href="{SITEMAP_BASE}/job/{slug}/{req}-{locale}/" /></head>
<body><h1><span itemprop="title">{title}</span></h1><span itemprop="description">
<p>Department: Département fictif</p><p>Location: {location}</p><p>Une annonce <b>fictive</b>.</p></span></body></html>"""


class SitemapClient:
    def __init__(self, sitemap=SITEMAP):
        self.urls, self.sitemap = [], sitemap
        self.pages = {
            f"{SITEMAP_BASE}/sitemap.xml": sitemap,
            f"{SITEMAP_BASE}/job/Lausanne-Stagiaire-fictif-VD/2001/": sitemap_page("Stagiaire-fictif", 77, "fr_FR", "Stagiaire fictif"),
            f"{SITEMAP_BASE}/job/Lausanne-Stagiaire-fictif-VD/2002/": sitemap_page("Stagiaire-fictif", 77, "en_GB", "Fictional trainee"),
            f"{SITEMAP_BASE}/job/Lausanne-Fictional-Analyst-VD/2003/": sitemap_page("Fictional-Analyst", 78, "fr_FR", "Analyste fictif", "Lausanne, Suisse"),
        }

    def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


class SitemapListingTests(unittest.TestCase):
    def source(self, client):
        return SuccessFactorsSource(client, base_url=SITEMAP_BASE, listing="sitemap", locale="en_GB")

    def test_one_job_per_requisition_in_the_preferred_language(self):
        refs = list(self.source(SitemapClient()).list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location, r.url, r.extra) for r in refs], [
            ("77", "Fictional trainee", "Lausanne, Switzerland", f"{SITEMAP_BASE}/job/Stagiaire-fictif/77-en_GB/", {"locale": "en_GB"}),
            ("78", "Analyste fictif", "Lausanne, Suisse", f"{SITEMAP_BASE}/job/Fictional-Analyst/78-fr_FR/", {"locale": "fr_FR"}),
        ])   # 78 has no English page; the /content/ page is not a job

    def test_detail_reuses_the_page_read_for_the_listing(self):
        client = SitemapClient()
        src = self.source(client)
        ref = next(src.list_jobs())
        read = len(client.urls)
        d = src.fetch_detail(ref)
        self.assertEqual(len(client.urls), read)
        self.assertIn("Une annonce fictive.", d.description)
        self.assertEqual((d.location, d.raw), ("Lausanne, Switzerland", {"url": ref.url, "locale": "en_GB"}))

    def test_job_page_without_canonical_requisition_is_an_error(self):
        client = SitemapClient()
        client.pages[f"{SITEMAP_BASE}/job/Lausanne-Fictional-Analyst-VD/2003/"] = "<html>Maintenance</html>"
        with self.assertRaises(RuntimeError):
            list(self.source(client).list_jobs())

    def test_empty_sitemap_and_changed_layout(self):
        empty = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
        self.assertEqual(list(self.source(SitemapClient(empty)).list_jobs()), [])
        with self.assertRaises(RuntimeError):
            list(self.source(SitemapClient("<?xml version='1.0'?><html/>")).list_jobs())
