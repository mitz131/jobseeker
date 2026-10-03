import unittest

from jobseeker.crawler.sources.workday import WorkdaySource, job_locations, resolve_facet_filters

from .workday_fakes import WORKDAY


FACETS = [
    {"facetParameter": "jobFamilyGroup", "descriptor": "Job Category",
     "values": [{"id": "cat1", "descriptor": "Engineering", "count": 9}]},
    {"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locationCountry", "descriptor": "Country", "values": [
            {"id": "ch-id", "descriptor": "Switzerland", "count": 12},
            {"id": "de-id", "descriptor": "Germany", "count": 40}]}]},
]


class FacetTests(unittest.TestCase):
    def test_resolves_nested_facet_by_name(self):
        self.assertEqual(resolve_facet_filters(FACETS, {"Country": ["switzerland"]}),
                         {"locationCountry": ["ch-id"]})
        self.assertEqual(resolve_facet_filters(FACETS, {"Job Category": ["Engineering"]}),
                         {"jobFamilyGroup": ["cat1"]})

    def test_unknown_names_fail_instead_of_fetching_everything(self):
        with self.assertRaisesRegex(ValueError, "No value 'Swizerland'"):
            resolve_facet_filters(FACETS, {"Country": ["Swizerland"]})
        with self.assertRaisesRegex(ValueError, "available: .*locationCountry"):
            resolve_facet_filters(FACETS, {"Region": ["Europe"]})

    def test_all_locations_of_multi_location_job(self):
        info = {"location": "Cork, Ireland", "additionalLocations": ["Lausanne, Switzerland", "Utrecht, Netherlands"]}
        self.assertEqual(job_locations(info), "Cork, Ireland / Lausanne, Switzerland / Utrecht, Netherlands")
        self.assertEqual(job_locations({"location": "Switzerland - Zurich"}), "Switzerland - Zurich")

    def test_resolved_ids_are_sent_with_search(self):
        sent = []

        class Client:
            def post_json(self, url, payload):
                sent.append(payload["appliedFacets"])
                return {"total": 0, "jobPostings": [], "facets": FACETS}

        src = WorkdaySource(Client(), **WORKDAY, facet_filters={"Country": ["Switzerland"]})
        list(src.list_jobs())
        self.assertEqual(sent, [{}, {"locationCountry": ["ch-id"]}])
