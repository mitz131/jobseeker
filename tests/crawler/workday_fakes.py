"""Fake Workday API shared by the runner and Workday tests."""


class FakeWorkdayClient:
    """Serves a fixed set of Workday postings, paginated like the real API."""

    def __init__(self, n_jobs: int):
        self.paths = [f"/job/Zurich/Engineer-{i}_JR{i}" for i in range(n_jobs)]
        self.detail_calls = []

    def post_json(self, url, payload):
        off, lim = payload["offset"], payload["limit"]
        page = [{"title": f"Engineer {p[-1]}", "externalPath": p, "locationsText": "Zurich"}
                for p in self.paths[off:off + lim]]
        return {"total": len(self.paths) if off == 0 else 0, "jobPostings": page}

    def get_json(self, url):
        self.detail_calls.append(url)
        return {"jobPostingInfo": {"title": "Engineer", "jobDescription": "<p>Build <b>things</b></p>"}}


WORKDAY = {"name": "acme", "type": "workday", "base_url": "https://acme.wd1.myworkdayjobs.com",
           "tenant": "acme", "site": "Ext"}
