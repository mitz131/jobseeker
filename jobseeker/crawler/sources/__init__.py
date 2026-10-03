from .jobcloud import JobCloudSource
from .oracle import OracleSource
from .phenom import PhenomSource
from .successfactors import SuccessFactorsSource
from .vaudoise import VaudoiseSource
from .workday import WorkdaySource

SOURCE_TYPES = {
    "workday": WorkdaySource,
    "successfactors": SuccessFactorsSource,
    "phenom": PhenomSource,
    "vaudoise": VaudoiseSource,
    "oracle": OracleSource,
    "jobcloud": JobCloudSource,
}


def build_source(client, company: dict):
    kind = company["type"]
    if kind not in SOURCE_TYPES:
        raise ValueError(f"Unknown source type {kind!r} for {company['name']}")
    return SOURCE_TYPES[kind](client, **company)
