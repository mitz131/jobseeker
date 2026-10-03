"""config.toml, and the paths and objects derived from it. Shared by the CLI and the API."""

import tomllib
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .places import Places


@dataclass
class Config:
    path: Path
    data: dict

    @classmethod
    def load(cls, path: str | Path = "config.toml") -> "Config":
        path = Path(path)
        with open(path, "rb") as f:
            return cls(path, tomllib.load(f))

    @property
    def settings(self) -> dict:
        return self.data.get("settings", {})

    def _file(self, key: str, default: str) -> Path:
        """Paths in config.toml are relative to the config file."""
        return self.path.parent / self.settings.get(key, default)

    @property
    def db_path(self) -> Path:
        path = self._file("db_path", "data/jobs.db")
        path.parent.mkdir(parents=True, exist_ok=True)  # data/ is not in git
        return path

    @property
    def request_delay(self) -> float:
        return self.settings.get("request_delay", 0.5)

    @property
    def max_new_per_company(self) -> int:
        return self.settings.get("max_new_per_company", 200)

    def companies(self, names: list[str] | None = None) -> list[dict]:
        """Enabled companies, or exactly the named ones (even if disabled)."""
        companies = [c for c in self.data.get("company", []) if c.get("enabled", True) or names]
        if names:
            companies = [c for c in companies if c["name"] in names]
            missing = set(names) - {c["name"] for c in companies}
            if missing:
                raise ValueError(f"Unknown company: {', '.join(sorted(missing))}")
        return companies

    @cached_property
    def places(self) -> Places | None:
        """None when the locality register hasn't been downloaded."""
        register = self._file("places_register", "data/AMTOVZ_CSV_LV95.csv")
        if not register.exists():
            return None
        places_file = self._file("places_file", "places.toml")
        return Places(str(register), str(places_file) if places_file.exists() else None)
