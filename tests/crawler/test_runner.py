import unittest

from jobseeker.crawler.runner import passes_filter, run_company
from jobseeker.crawler.sources.base import JobRef
from jobseeker.db import JobStore

from .workday_fakes import WORKDAY, FakeWorkdayClient


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.store = JobStore(":memory:")

    def test_paginates_and_only_fetches_new_jobs(self):
        client = FakeWorkdayClient(45)
        r1 = run_company(self.store, client, WORKDAY, max_new=1000)
        self.assertEqual((r1.listed, r1.new), (45, 45))

        client.paths.append("/job/Zurich/Engineer-new_JR999")
        client.detail_calls.clear()
        r2 = run_company(self.store, client, WORKDAY, max_new=1000)
        self.assertEqual((r2.listed, r2.new), (46, 1))
        self.assertEqual(len(client.detail_calls), 1)

    def test_max_new_defers_rest_to_next_run(self):
        client = FakeWorkdayClient(10)
        self.assertEqual(run_company(self.store, client, WORKDAY, max_new=4).new, 4)
        self.assertEqual(run_company(self.store, client, WORKDAY, max_new=100).new, 6)

    def test_client_side_filter(self):
        client = FakeWorkdayClient(3)
        cfg = WORKDAY | {"filter": {"title_exclude": ["engineer 1"]}}
        self.assertEqual(run_company(self.store, client, cfg, max_new=100).new, 2)

    def test_title_filter_matches_whole_words(self):
        flt = {"title_exclude": ["intern", "internship"]}
        self.assertFalse(passes_filter(JobRef("1", "R&D Intern - Packaging"), flt))
        self.assertFalse(passes_filter(JobRef("2", "Summer Internship 2027"), flt))
        self.assertTrue(passes_filter(JobRef("3", "Internal Communications Manager"), flt))

    def test_title_filter_matches_plural_and_feminine_forms(self):
        flt = {"title_exclude": ["stagiaire", "apprenti"]}
        self.assertFalse(passes_filter(JobRef("1", "Stagiaires maturantes ou maturants"), flt))
        self.assertFalse(passes_filter(JobRef("2", "Apprenties ou apprentis de commerce"), flt))
        self.assertFalse(passes_filter(JobRef("3", "Apprenti-e Technologue"), flt))
        self.assertTrue(passes_filter(JobRef("4", "Apprentissage manager"), flt))

    def test_listing_failure_is_recorded(self):
        class Broken:
            def post_json(self, *a):
                raise RuntimeError("HTTP 503")
        r = run_company(self.store, Broken(), WORKDAY, max_new=10)
        self.assertIn("503", r.error)
