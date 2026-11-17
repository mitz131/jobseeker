import unittest

from jobseeker.crawler.sources.umantis import UmantisSource, location

BASE = "https://portal.example.test"


def row(job_id, title, online, dept, places, cls="tableaslist_contentrow1"):
    """A list row shaped like the portal's, with made-up content."""
    return f'''<tr class="{cls}"><td class="tableaslist_cell"><div class="tableaslist_cell">
 <span class="tableaslist_text tableaslist_element_11">Online since: {online}<br/> </span>
 <span class="tableaslist_subtitle tableaslist_element_12"><a class="HSTableLinkSubTitle"
   href="/Vacancies/{job_id}/Description/2">{title}</a></span>
 <span class="tableaslist_subtitle tableaslist_element_13">Type: Full-time</span>
 <span class="tableaslist_subtitle tableaslist_element_14"> |\xa0{dept}</span>
 <span class="tableaslist_subtitle tableaslist_element_15"> |\xa0{places}</span>
 <span class="tableaslist_text"><a class="HSTableLink" href="/Vacancies/{job_id}/Application/CheckLogin/2">Apply</a></span>
</div></td></tr>'''


def page(rows, next_href="?tc1=p2&amp;_search_token1=99#connectortable_1"):
    nav = f'<span class="tableaslist_paging_top" data-pagination-next-href="{next_href}"></span>' if next_href else ""
    return f"<html><body>{nav}<table>{''.join(rows)}</table></body></html>"


PAGE_1 = page([row("901", "Analyste fictif", "16.11.2026", "Fonds fictifs", "Basel, CH; Zurich, CH"),
               row("902", "Ingénieur fictif", "3.9.2026", "IT", "Geneva, CH", cls="tableaslist_contentrow2")])
PAGE_2 = page([])   # the portal links a second page even when everything fits on the first

DETAIL = '''<html><body><header>Menu</header><main class="page-content">
<div class="content-box">
  <div>
    <h1>
        Analyste fictif
    </h1>
    <ul class="icon-box">
      <li>
        <img alt="Basel, CH" src="/x"/>
        <span>Basel, CH</span>
      </li>
      <li>
        <span>Full-time</span>
      </li>
    </ul>
    <div class="text-box"><h3>Your Role</h3><p>Analyser des <b>fonds</b> fictifs.</p></div>
  </div>
</div>
<div class="content-box bg-grey"><div class="text-box"><h3>Your Profile</h3>
  <ul>
    <li>Rigueur</li>
    <li>Curiosité</li>
  </ul></div></div>
<div class="content-box bg-grey"><div class="apply-btn-box">Apply</div>
  <ul class="info-list"><li>Not the perfect fit?</li></ul>
  <div class="share-container">Share this role</div></div>
</main><footer>Footer</footer></body></html>'''


class FakeClient:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


LIST_URL = BASE + "/Jobs/All"
PAGE_2_URL = BASE + "/Jobs/All?tc1=p2&_search_token1=99"


class UmantisTests(unittest.TestCase):
    def test_location(self):
        self.assertEqual(location("|\xa0Basel, CH; Zurich, CH"), "Basel / Zurich")
        self.assertEqual(location("| Geneva, CH"), "Geneva")

    def test_listing_follows_the_next_page_until_no_new_job(self):
        client = FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_2})
        refs = list(UmantisSource(client, base_url=BASE + "/").list_jobs())
        self.assertEqual(client.urls, [LIST_URL, PAGE_2_URL])
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on, r.url, r.extra) for r in refs], [
            ("901", "Analyste fictif", "Basel / Zurich", "2026-11-16", BASE + "/Vacancies/901/Description/2",
             {"department": "Fonds fictifs"}),
            ("902", "Ingénieur fictif", "Geneva", "2026-09-03", BASE + "/Vacancies/902/Description/2",
             {"department": "IT"}),
        ])

    def test_a_page_repeating_known_jobs_ends_the_listing(self):
        client = FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_1})
        self.assertEqual(len(list(UmantisSource(client, base_url=BASE).list_jobs())), 2)
        self.assertEqual(len(client.urls), 2)

    def test_empty_list_is_an_error(self):
        client = FakeClient({LIST_URL: page([], next_href=None)})
        with self.assertRaises(RuntimeError):
            list(UmantisSource(client, base_url=BASE).list_jobs())

    def test_detail_is_the_ad_without_apply_and_share_boxes(self):
        client = FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_2,
                             BASE + "/Vacancies/901/Description/2": DETAIL})
        src = UmantisSource(client, base_url=BASE)
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertTrue(d.description.startswith("Analyste fictif\n"))
        self.assertIn("- Basel, CH\n- Full-time", d.description)   # one line per item
        self.assertIn("Analyser des fonds fictifs.", d.description)
        self.assertIn("- Rigueur\n- Curiosité", d.description)
        for gone in ("Apply", "Not the perfect fit", "Share this role", "Menu", "Footer"):
            self.assertNotIn(gone, d.description)
        self.assertEqual(d.raw["department"], "Fonds fictifs")

    def test_detail_without_the_expected_layout_is_an_error(self):
        client = FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_2,
                             BASE + "/Vacancies/901/Description/2": "<html><body>Maintenance</body></html>"})
        src = UmantisSource(client, base_url=BASE)
        with self.assertRaises(RuntimeError):
            src.fetch_detail(next(src.list_jobs()))
