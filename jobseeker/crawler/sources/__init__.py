from .creditagricole import CreditAgricoleSource
from .jobcloud import JobCloudSource
from .johdi import JohdiSource
from .lausanne import LausanneSource
from .oracle import OracleSource
from .phenom import PhenomSource
from .sfcareer import SFCareerSource
from .smartrecruiters import SmartRecruitersSource
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
    "creditagricole": CreditAgricoleSource,
    "sfcareer": SFCareerSource,
    "johdi": JohdiSource,
    "smartrecruiters": SmartRecruitersSource,
    "lausanne": LausanneSource,
}


def build_source(client, company: dict):
    kind = company["type"]
    if kind not in SOURCE_TYPES:
        raise ValueError(f"Unknown source type {kind!r} for {company['name']}")
    return SOURCE_TYPES[kind](client, **company)
