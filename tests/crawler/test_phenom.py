import json
import unittest

from jobseeker.crawler.sources.phenom import PhenomSource


class FakePhenomClient:
    JOBS = [{"jobId": str(i), "title": f"Job {i}", "location": "Lausanne, Switzerland",
             "multi_location": ["Lausanne, Switzerland"], "postedDate": "2026-09-28T09:47:27.000+0000"}
            for i in range(13)]
    JOBS[3] = JOBS[3] | {"location": "London, United Kingdom",
                         "multi_location": ["London, United Kingdom", "Lausanne, Switzerland"]}

    def post_json(self, url, payload):
        page = self.JOBS[payload["from"]:payload["from"] + payload["size"]]
        return {"refineSearch": {"status": 200, "totalHits": len(self.JOBS), "data": {"jobs": page}}}

    def get_text(self, url):
        job = {"title": "Job", "description": "<p>Hello</p>", "completeDescription_chunk_0": {"chunk": "x"},
               "multi_location": [{"location": "Bern, Switzerland"}]}
        canonical = '<link rel="canonical" href="https://jobs.example.com/gb/en/job/SEQ0/Job">' if url.endswith("/0") else ""
        return f"{canonical}<script>phApp.ddo = {json.dumps({'jobDetail': {'data': {'job': job}}})}; phApp.x = 1;</script>"


class PhenomTests(unittest.TestCase):
    def test_paginates_and_lists_all_locations(self):
        refs = list(PhenomSource(FakePhenomClient(), "https://jobs.example.com").list_jobs())
        self.assertEqual(len(refs), 13)
        self.assertEqual(refs[3].location, "London, United Kingdom / Lausanne, Switzerland")
        self.assertEqual(refs[0].url, "https://jobs.example.com/gb/en/job/0")

    def test_detail_from_embedded_json(self):
        src = PhenomSource(FakePhenomClient(), "https://jobs.example.com")
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual(d.description, "Hello")
        self.assertEqual(d.location, "Bern, Switzerland")
        self.assertNotIn("completeDescription_chunk_0", d.raw)

    def test_detail_link_is_the_canonical_url(self):
        src = PhenomSource(FakePhenomClient(), "https://jobs.example.com")
        first, second = list(src.list_jobs())[:2]
        self.assertEqual(src.fetch_detail(first).url, "https://jobs.example.com/gb/en/job/SEQ0/Job")
        self.assertIsNone(src.fetch_detail(second).url)   # no canonical link: the listing URL is kept
