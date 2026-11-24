import json
import unittest

from jobseeker.crawler.sources.prospective import ProspectiveSource

BASE = "https://careers.example.test"
LIST = BASE + "/?lang=de&offset={}&limit=100"
UUID = "a2fcd50a-ed7c-4619-9bf1-{:012d}"


def job_link(n, title, place):
    """A list entry shaped like Prospective's, with made-up content."""
    return f'''<a class="job job-{n}" href="{BASE}/offene-stellen/{title.lower().replace(" ", "-")}/{UUID.format(n)}" title="{title}">
 <div class="ui grid"><div class="column"><span class="job-title"> {title} </span></div>
 <div class="column"><div class="job-meta"><span class="place-of-work"> {place} </span></div></div></div></a>'''


def page(links, total):
    return (f'<html><body><header id="header-content"><h1 class="ui header jobs-total"><span class="total">{total}</span>'
            f' Jobs</h1></header><div id="jobs-list">{"".join(links)}</div></body></html>')


def job_page(posting):
    return f'<html><head><script type="application/ld+json">{json.dumps(posting)}</script></head><body>…</body></html>'


class FakeClient:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


class ProspectiveTests(unittest.TestCase):
    def test_listing_pages_until_the_total(self):
        first = [job_link(i, f"Poste fictif {i}", "Nyon") for i in range(100)]
        client = FakeClient({LIST.format(0): page(first, 102),
                             LIST.format(100): page([job_link(0, "Poste fictif 0", "Nyon"),   # moved down a page
                                                     job_link(100, "Agent fictif", "Genève 15"),
                                                     job_link(101, "Juriste fictif", "Adliswil")], 102)})
        refs = list(ProspectiveSource(client, base_url=BASE + "/").list_jobs())
        self.assertEqual(client.urls, [LIST.format(0), LIST.format(100)])
        self.assertEqual(len(refs), 102)   # the repeated job counted once
        self.assertEqual((refs[-1].job_id, refs[-1].title, refs[-1].location, refs[-1].url),
                         (UUID.format(101), "Juriste fictif", "Adliswil",
                          f"{BASE}/offene-stellen/juriste-fictif/{UUID.format(101)}"))

    def test_no_jobs_is_not_an_error(self):
        self.assertEqual(list(ProspectiveSource(FakeClient({LIST.format(0): page([], 0)}), base_url=BASE).list_jobs()), [])

    def test_changed_layout_is_an_error(self):
        with self.assertRaises(RuntimeError):
            list(ProspectiveSource(FakeClient({LIST.format(0): "<html>Wartung</html>"}), base_url=BASE).list_jobs())

    def test_detail_from_the_job_posting(self):
        url = f"{BASE}/offene-stellen/juriste-fictif/{UUID.format(7)}"
        client = FakeClient({LIST.format(0): page([job_link(7, "Juriste fictif", "Nyon")], 1), url: job_page({
            "@context": "http://schema.org", "@type": "JobPosting", "title": "Juriste fictif - 80 - 100%",
            "description": "<h3>Intro fictive</h3><p>Ce qui t'attend</p><ul><li>Négocier</li><li>Conseiller</li></ul>",
            "datePosted": "2026-11-24", "validThrough": "2026-12-23", "employmentType": "PART_TIME",
            "hiringOrganization": {"name": "Assureur fictif SA"},
            "jobLocation": {"@type": "Place", "address": {"addressCountry": "Schweiz", "addressLocality": "Nyon",
                                                          "postalCode": "1260"}}})})
        src = ProspectiveSource(client, base_url=BASE)
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertIn("- Négocier\n- Conseiller", d.description)
        self.assertEqual((d.location, d.posted_on), ("1260 Nyon", "2026-11-24"))
        self.assertEqual(d.raw["employer"], "Assureur fictif SA")
        self.assertEqual(d.raw["title"], "Juriste fictif - 80 - 100%")

    def test_detail_without_a_job_posting_is_an_error(self):
        url = f"{BASE}/offene-stellen/juriste-fictif/{UUID.format(7)}"
        client = FakeClient({LIST.format(0): page([job_link(7, "Juriste fictif", "Nyon")], 1), url: "<html>Wartung</html>"})
        src = ProspectiveSource(client, base_url=BASE)
        with self.assertRaises(RuntimeError):
            src.fetch_detail(next(src.list_jobs()))
