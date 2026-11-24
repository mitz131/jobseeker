from .assura import AssuraSource
from .avature import AvatureSource
from .bcge import BCGESource
from .cornerstone import CornerstoneSource
from .creditagricole import CreditAgricoleSource
from .eightfold import EightfoldSource
from .jobcloud import JobCloudSource
from .johdi import JohdiSource
from .lausanne import LausanneSource
from .oracle import OracleSource
from .phenom import PhenomSource
from .prospective import ProspectiveSource
from .radancy import RadancySource
from .sfcareer import SFCareerSource
from .smartrecruiters import SmartRecruitersSource
from .successfactors import SuccessFactorsSource
from .umantis import UmantisSource
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
    "bcge": BCGESource,
    "assura": AssuraSource,
    "umantis": UmantisSource,
    "radancy": RadancySource,
    "avature": AvatureSource,
    "eightfold": EightfoldSource,
    "cornerstone": CornerstoneSource,
    "prospective": ProspectiveSource,
}


def build_source(client, company: dict):
    kind = company["type"]
    if kind not in SOURCE_TYPES:
        raise ValueError(f"Unknown source type {kind!r} for {company['name']}")
    return SOURCE_TYPES[kind](client, **company)
