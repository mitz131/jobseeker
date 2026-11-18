"""Avature career portals, e.g. TotalEnergies' jobs.totalenergies.com.

Everything is server-rendered HTML:

  GET {base_url}/SearchJobs/?<country_field>[]=<country_id>&listFilterMode=1
      -> 20 results per page (div.article--result): a link to JobDetail/<slug>/<id>,
         then list items jobCreationDate (dd-mm-yyyy), jobCountry, employmentType, ...
         and a "next page" link (a.paginationNextLink, jobOffset=) while there are more
  GET the job's page
      -> dl.article__content__view__field blocks: labelled facts (Country, City,
         Workplace location, Domain, Type of contract, ...) then the ad, unlabelled

The Country filter takes an option id, not a name: the search page's form loads the
options by a separate request (autocomplete), so the field number and the country's id go
in the config (TotalEnergies: field 3834, Switzerland 41579, read in the browser's
developer tools). Each listed job's country is still checked against `country`, so a wrong
id gives no jobs rather than other countries' jobs.
The list has no city; the job page's City becomes the job's location.
"""

import re
from collections.abc import Iterator
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup, Tag

from ..html_text import html_to_text
from .base import JobDetail, JobRef

MAX_PAGES = 20
JOB_ID_RE = re.compile(r"/JobDetail/[^/]+/(\d+)")
DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def iso_date(text: str) -> str:
    m = DATE_RE.search(text)
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def parse_results(page_html: str, page_url: str) -> tuple[list[tuple[JobRef, str]], str | None]:
    """The page's jobs, each with its listed country, and the next page's URL (or None)."""
    soup = BeautifulSoup(page_html, "html.parser")
    if not soup.select_one(".list-controls__text__legend"):   # "1-20 of 25 results", also "0 results"
        raise RuntimeError(f"No results counter on {page_url}; page layout may have changed")
    jobs = []
    for article in soup.select("div.article--result"):
        link = article.find("a", href=JOB_ID_RE)
        if not link:
            continue

        def item(name: str) -> str:
            return _text(article.select_one(f".list-item-{name}"))

        jobs.append((JobRef(
            job_id=JOB_ID_RE.search(link["href"])[1],
            title=_text(link),
            url=urljoin(page_url, link["href"]),
            posted_on=iso_date(item("jobCreationDate")),
            extra={"employment_type": item("employmentType"), "employer": item("jobEmployerCompany")},
        ), item("jobCountry")))
    nxt = soup.select_one("a.paginationNextLink[href]")
    return jobs, (urljoin(page_url, nxt["href"]) if nxt else None)


class AvatureSource:
    def __init__(self, client, base_url: str, country_field: int | str, country_id: int | str,
                 country: str = "Switzerland", **_):
        self.client = client
        self.base_url = base_url.rstrip("/")   # e.g. https://jobs.totalenergies.com/en_US/careers
        self.country_field = country_field
        self.country_id = country_id
        self.country = country

    def list_jobs(self) -> Iterator[JobRef]:
        query = urlencode({f"{self.country_field}[]": self.country_id, "listFilterMode": 1})
        url, seen = f"{self.base_url}/SearchJobs/?{query}", set()
        for _ in range(MAX_PAGES):
            jobs, url = parse_results(self.client.get_text(url), url)
            new = [(r, c) for r, c in jobs if r.job_id not in seen]
            seen.update(r.job_id for r, _ in new)
            # a safety net: with a wrong or reused id, other countries' jobs are dropped
            yield from (r for r, c in new if c.casefold() == self.country.casefold())
            if not new or not url:
                break
        else:
            raise RuntimeError(f"{self.base_url}: more than {MAX_PAGES} pages of results for "
                               f"{self.country_field}[]={self.country_id}")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        soup = BeautifulSoup(self.client.get_text(ref.url), "html.parser")
        fields = soup.select("dl.article__content__view__field")
        if not fields:
            raise RuntimeError(f"No job fields on {ref.url}; page layout may have changed")
        facts, ad = {}, []
        for dl in fields:
            label, value = dl.find("dt"), dl.find("dd")
            if label:
                facts[_text(label)] = _text(value)
            elif value and value.get_text(strip=True):
                ad.append(value.decode_contents())
        html = "\n".join(ad)
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw={"url": ref.url, **ref.extra, "fields": facts},
            location=facts.get("City") or None,
        )
