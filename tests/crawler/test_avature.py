import unittest

from jobseeker.crawler.sources.avature import AvatureSource, iso_date

BASE = "https://portal.example.test/en_US/careers"
LIST_URL = BASE + "/SearchJobs/?77%5B%5D=123&listFilterMode=1"
PAGE_2_URL = BASE + "/SearchJobs/?77=%5B123%5D&listFilterMode=1&jobRecordsPerPage=20&jobOffset=20"


def result(job_id, title, country, date="16-11-2026", kind="Regular position"):
    """A result shaped like the portal's, with made-up content."""
    slug = title.replace(" ", "-")
    return f'''<div class="article article--result"><div class="article__header"><div class="article__header__text">
 <h3 class="article__header__text__title"><a class="link" href="{BASE}/JobDetail/{slug}/{job_id}"> {title} </a></h3>
 <ul class="list article__header__text__subtitle">
  <li class="list-item list-item-jobCreationDate">{date}</li>
  <li class="list-item list-item-jobCountry">{country}</li>
  <li class="list-item list-item-employmentType">{kind}</li>
  <li class="list-item list-item-jobEmployerCompany">Société fictive SA</li>
 </ul></div></div>
 <div class="article__footer"><a class="button" href="{BASE}/JobDetail/{slug}/{job_id}">Apply</a></div></div>'''


def page(results, total, next_href=None):
    nxt = f'<a class="paginationNextLink" href="{next_href}">Next</a>' if next_href else ""
    return (f'<html><body><div class="list-controls__text__legend" aria-label="{total} results">…</div>'
            f'{"".join(results)}<nav>{nxt}</nav></body></html>')


PAGE_1 = page([result("901", "Trader fictif", "Switzerland"),
               result("902", "Analyste fictif", "France", date="3-9-2026")],   # not Switzerland, despite the filter
              3, next_href=PAGE_2_URL.replace("&", "&amp;"))
PAGE_2 = page([result("903", "Opérateur fictif", "Switzerland", kind="Fixed term position")], 3)

DETAIL = '''<html><body><header>Menu</header><div class="article__content__view">
<dl class="article__content__view__field"><dt class="article__content__view__field__label">Country</dt>
 <dd class="article__content__view__field__value">Switzerland</dd></dl>
<dl class="article__content__view__field"><dt class="article__content__view__field__label">City</dt>
 <dd class="article__content__view__field__value"> GENEVE </dd></dl>
<dl class="article__content__view__field"><dt class="article__content__view__field__label">Domain</dt>
 <dd class="article__content__view__field__value">Trading</dd></dl>
<dl class="article__content__view__field"><dd class="article__content__view__field__value">
 <p><strong>Votre mission</strong></p><p>Négocier du <b>pétrole</b> fictif.</p><ul><li>Rigueur</li><li>Curiosité</li></ul>
</dd></dl>
<dl class="article__content__view__field"><dd class="article__content__view__field__value"> </dd></dl>
</div><footer>Footer</footer></body></html>'''


class FakeClient:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


class AvatureTests(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(iso_date("16-11-2026"), "2026-11-16")
        self.assertEqual(iso_date("3-9-2026"), "2026-09-03")

    def test_listing_filters_by_country_follows_pages_and_checks_the_country(self):
        client = FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_2})
        refs = list(AvatureSource(client, base_url=BASE + "/", country_field=77, country_id=123).list_jobs())
        self.assertEqual(client.urls, [LIST_URL, PAGE_2_URL])
        self.assertEqual([(r.job_id, r.title, r.posted_on, r.url, r.extra) for r in refs], [
            ("901", "Trader fictif", "2026-11-16", BASE + "/JobDetail/Trader-fictif/901",
             {"employment_type": "Regular position", "employer": "Société fictive SA"}),
            ("903", "Opérateur fictif", "2026-11-16", BASE + "/JobDetail/Opérateur-fictif/903",
             {"employment_type": "Fixed term position", "employer": "Société fictive SA"}),
        ])   # 902 is in France

    def test_no_results_is_not_an_error(self):
        client = FakeClient({LIST_URL: page([], 0)})
        self.assertEqual(list(AvatureSource(client, base_url=BASE, country_field=77, country_id=123).list_jobs()), [])

    def test_changed_layout_is_an_error(self):
        client = FakeClient({LIST_URL: "<html><body>Maintenance</body></html>"})
        with self.assertRaises(RuntimeError):
            list(AvatureSource(client, base_url=BASE, country_field=77, country_id=123).list_jobs())

    def test_detail_has_the_city_and_the_ad(self):
        job_url = BASE + "/JobDetail/Trader-fictif/901"
        src = AvatureSource(FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_2, job_url: DETAIL}),
                            base_url=BASE, country_field=77, country_id=123)
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual(d.location, "GENEVE")
        self.assertEqual(d.raw["fields"], {"Country": "Switzerland", "City": "GENEVE", "Domain": "Trading"})
        self.assertIn("Négocier du pétrole fictif.", d.description)
        self.assertIn("- Rigueur\n- Curiosité", d.description)
        for gone in ("Menu", "Footer", "Domain"):
            self.assertNotIn(gone, d.description)

    def test_detail_without_fields_is_an_error(self):
        job_url = BASE + "/JobDetail/Trader-fictif/901"
        src = AvatureSource(FakeClient({LIST_URL: PAGE_1, PAGE_2_URL: PAGE_2, job_url: "<html>Maintenance</html>"}),
                            base_url=BASE, country_field=77, country_id=123)
        with self.assertRaises(RuntimeError):
            src.fetch_detail(next(src.list_jobs()))
