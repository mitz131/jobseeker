import json
import unittest

from jobseeker.crawler.html_text import html_to_text
from jobseeker.crawler.sources.jobcloud import embedded_jobs
from jobseeker.crawler.sources.successfactors import extract_description


class JobCloudTests(unittest.TestCase):
    def test_all_jobs_from_embedded_next_data(self):
        jobs = [{"id": f"{i:08d}-0000-4000-8000-000000000000", "title": f"Job {i}", "companyName": "Salt Mobile SA",
                 "location": "Prilly", "employmentPct": 100} for i in range(3)]
        rsc = 'a:["$","div",null,{"jobs":' + json.dumps(jobs) + '}]'
        page = ('<script>self.__next_f.push([1,' + json.dumps(rsc[:20]) + '])</script>'
                '<script>self.__next_f.push([1,' + json.dumps(rsc[20:]) + '])</script>')
        self.assertEqual([j["title"] for j in embedded_jobs(page)], ["Job 0", "Job 1", "Job 2"])

    def test_description_from_job_description_div(self):
        page = '<main><h1>T</h1><div class="job-description max-w-none"><div><p>Hallo</p></div></div><aside>x</aside></main>'
        self.assertEqual(html_to_text(extract_description(page, classes=("job-description",))), "Hallo")
