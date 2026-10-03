import unittest

from jobseeker.crawler.sources.oracle import OracleSource, job_locations as oracle_locations


class FakeOracleClient:
    def __init__(self, n):
        self.reqs = [{"Id": str(i), "Title": f"Poste {i}", "PrimaryLocation": "Lausanne, Switzerland",
                      "PostedDate": "2026-10-01"} for i in range(n)]

    def get_json(self, url):
        if "recruitingCEJobRequisitionDetails" in url:
            return {"items": [{"Title": "Poste", "ExternalDescriptionStr": "<p>Intro</p>",
                               "ExternalQualificationsStr": "<ul><li>CFC</li></ul>"}]}
        offset = int(url.split("offset=")[1].split(",")[0])
        # hasMore is always false on the real API, even when more pages exist
        return {"hasMore": False, "items": [{"TotalJobsCount": len(self.reqs),
                                             "requisitionList": self.reqs[offset:offset + 25]}]}


class OracleTests(unittest.TestCase):
    def test_pages_by_total_not_has_more(self):
        src = OracleSource(FakeOracleClient(38), "https://x.oraclecloud.com", "CX_1",
                           public_url="https://jobs.example.ch/#fr/sites/{site}")
        refs = list(src.list_jobs())
        self.assertEqual(len(refs), 38)
        self.assertEqual(refs[0].url, "https://jobs.example.ch/#fr/sites/CX_1/job/0")

    def test_multiple_sites_are_merged_by_id(self):
        client = FakeOracleClient(30)
        src = OracleSource(client, "https://x.oraclecloud.com", ["CX_1", "enseignement"])
        refs = list(src.list_jobs())
        self.assertEqual(len(refs), 30)  # same 30 requisitions on both sites -> listed once
        self.assertTrue(all(r.extra["site"] == "CX_1" for r in refs))

    def test_secondary_locations_skip_country_only_entries(self):
        job = {"PrimaryLocation": "Aigle, Suisse",
               "secondaryLocations": [{"Name": "Lausanne, Switzerland"}, {"Name": "Switzerland"}]}
        self.assertEqual(oracle_locations(job), "Aigle, Suisse / Lausanne, Switzerland")

    def test_detail_joins_sections(self):
        src = OracleSource(FakeOracleClient(1), "https://x.oraclecloud.com", "CX_1")
        d = src.fetch_detail(next(src.list_jobs()))
        self.assertEqual(d.description, "Intro\n\nProfil\n\n- CFC")
