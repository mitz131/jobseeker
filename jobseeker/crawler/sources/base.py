from dataclasses import dataclass, field


@dataclass
class JobRef:
    """A job as it appears in a search listing (cheap to fetch)."""
    job_id: str
    title: str
    location: str = ""
    url: str = ""
    posted_on: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class JobDetail:
    """Full job posting, fetched only for jobs we have not seen before."""
    description_html: str
    description: str
    raw: dict = field(default_factory=dict)
    title: str | None = None
    location: str | None = None
    url: str | None = None
    posted_on: str | None = None
