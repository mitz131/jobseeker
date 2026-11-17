from pathlib import Path

from jobseeker.config import Config

REPO_CONFIG = Path(__file__).parent.parent / "config.toml"


def test_category_needs_a_definition(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('''
[[category]]
name = "bank"
label = "Banks"

[[company]]
name = "a"
category = "bank"

[[company]]
name = "b"
category = "typo"

[[company]]
name = "c"
''')
    config = Config.load(path)
    assert config.categories() == [{"name": "bank", "label": "Banks"}]
    assert config.company_categories() == {"a": "bank"}  # unknown or missing: shown under "Other"


def test_every_company_in_config_toml_has_a_category():
    config = Config.load(REPO_CONFIG)
    names = {c["name"] for c in config.data["company"]}
    assert names - config.company_categories().keys() == set()
