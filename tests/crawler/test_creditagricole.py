import unittest

from jobseeker.crawler.sources.creditagricole import CreditAgricoleSource, clean_location, iso_date


def card(ref, title, city, date="Mis à jour le 12/11/2026"):
    return f"""<div class="col-lg-3"><article class="card offer detail" data-gtm-jobCountry="Suisse"
  data-gtm-jobCity="{city}" data-gtm-jobTitle="{title}" data-gtm-jobContract="CDI"
  data-gtm-jobPublishDate="{date}" data-gtm-jobEntity="Indosuez Wealth Management">
  <h3 class="offer-title"><a href="https://ca.example/fr/nos-offres-emploi/{ref}-slug/">{title}</a></h3>
  <input id="input-favorite-{ref}" type="checkbox" data-reference="{ref}"/></article></div>"""


def page(*cards, total=None):
    total = len(cards) if total is None else total
    return f'<main id="main" data-param-total-offers="{total}" data-param-limit="32">{"".join(cards)}</main>'


DETAIL = """<script type="application/ld+json">{"@type": "BreadcrumbList"}</script>
<script type="application/ld+json">{"@type": "JobPosting", "title": "Trade Finance Officer &amp; Analyst H/F",
"datePosted": "05/11/2026", "description": "<p>Bonjour</p>"}</script>"""


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get_text(self, url):
        self.urls.append(url)
        if "nos-offres-emploi" in url:
            return DETAIL
        n = int(url.rstrip("/").rsplit("/", 1)[1])
        return self.pages[n - 1] if n <= len(self.pages) else page(total=0)


class CreditAgricoleTests(unittest.TestCase):
    def source(self, pages):
        return CreditAgricoleSource(FakeClient(pages), "https://ca.example/", location_id=176)

    def test_pages_until_one_without_new_jobs(self):
        src = self.source([page(card("2026-1", "A &amp; B H/F", "GENEVE - Suisse"), card("2026-2", "C", "  Nyon - Suisse")),
                           page(card("2026-2", "C", "  Nyon - Suisse"), card("2026-3", "D", "Geneve / Lausanne - Suisse"))])
        refs = list(src.list_jobs())
        self.assertEqual([(r.job_id, r.title, r.location, r.posted_on) for r in refs],
                         [("2026-1", "A & B H/F", "GENEVE, Suisse", "2026-11-12"),
                          ("2026-2", "C", "Nyon, Suisse", "2026-11-12"),
                          ("2026-3", "D", "Geneve / Lausanne, Suisse", "2026-11-12")])
        self.assertEqual(refs[0].url, "https://ca.example/fr/nos-offres-emploi/2026-1-slug/")
        self.assertEqual(src.client.urls[0], "https://ca.example/fr/nos-offres/localisations/176/page/1/")
        self.assertEqual(len(src.client.urls), 3)   # page 3 is empty: stop

    def test_no_jobs_in_the_country_is_not_an_error(self):
        self.assertEqual(list(self.source([page(total=0)]).list_jobs()), [])

    def test_changed_layout_is_an_error(self):
        with self.assertRaises(RuntimeError):
            list(self.source(["<html>redesigned</html>"]).list_jobs())

    def test_detail_from_json_ld(self):
        src = self.source([page(card("2026-1", "A", "GENEVE - Suisse"))])
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual((d.title, d.posted_on, d.description), ("Trade Finance Officer & Analyst H/F", "2026-11-05", "Bonjour"))

    def test_helpers(self):
        self.assertEqual(iso_date("Mis à jour le 01/02/2026"), "2026-02-01")
        self.assertEqual(iso_date("soon"), "")
        self.assertEqual(clean_location("Suisse"), "Suisse")
        self.assertEqual(clean_location("Chemin de Bérée 38 1010 Lausanne - Suisse"), "Lausanne, Suisse")
        self.assertEqual(clean_location("Route de Saint Julien 7  CAROUGE - Suisse"), "CAROUGE, Suisse")
