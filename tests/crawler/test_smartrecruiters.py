import unittest

from jobseeker.crawler.sources.smartrecruiters import SmartRecruitersSource


def posting(i, city="Geneva"):
    return {"id": str(i), "name": f"Job {i} ", "releasedDate": "2026-10-30T12:44:50.504Z",
            "location": {"city": city, "country": "ch", "fullLocation": f"{city}, GE, Switzerland"}}


DETAIL = {"id": "1", "name": "Job 1", "releasedDate": "2026-10-30T12:44:50.504Z",
          "jobAd": {"sections": {"companyDescription": {"title": "Company Description", "text": "<p>Bank</p>"},
                                 "jobDescription": {"title": "Job Description", "text": "<p>Do things</p>"},
                                 "videos": {"title": "Videos", "text": ""}}}}


class FakeClient:
    def __init__(self, total=150):
        self.jobs = [posting(i) for i in range(total)]
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        if "/postings?" not in url:
            return DETAIL
        q = dict(kv.split("=") for kv in url.split("?", 1)[1].split("&"))
        start, size = int(q["offset"]), int(q["limit"])
        return {"totalFound": len(self.jobs), "content": self.jobs[start:start + size]}


class SmartRecruitersTests(unittest.TestCase):
    def test_pages_through_all_postings_with_the_country_filter(self):
        src = SmartRecruitersSource(FakeClient(), "Acme", country="ch")
        refs = list(src.list_jobs())
        self.assertEqual(len(refs), 150)
        self.assertEqual((refs[0].job_id, refs[0].title, refs[0].location, refs[0].posted_on, refs[0].url),
                         ("0", "Job 0", "Geneva, GE, Switzerland", "2026-10-30", "https://jobs.smartrecruiters.com/Acme/0"))
        self.assertEqual(src.client.urls, [
            "https://api.smartrecruiters.com/v1/companies/Acme/postings?offset=0&limit=100&country=ch",
            "https://api.smartrecruiters.com/v1/companies/Acme/postings?offset=100&limit=100&country=ch"])

    def test_employer_job_url(self):
        src = SmartRecruitersSource(FakeClient(1), "Acme", job_url="https://acme.example/jobs/{id}")
        self.assertEqual(next(src.list_jobs()).url, "https://acme.example/jobs/0")

    def test_detail_joins_the_ad_sections(self):
        src = SmartRecruitersSource(FakeClient(1), "Acme")
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual(d.description_html,
                         "<h2>Company Description</h2><p>Bank</p><h2>Job Description</h2><p>Do things</p>")
        self.assertIn("Do things", d.description)
