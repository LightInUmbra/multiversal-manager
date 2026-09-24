import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_NAME", str(tmp_path / "test.db"))
    db.create_table()
    return db


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # Tests pass fakes explicitly; anything that falls through to Scryfall fails loudly,
    # except the fuzzy fallback, which just finds nothing
    import scryfall

    def offline(*args, **kwargs):
        raise AssertionError("test tried to reach Scryfall")

    monkeypatch.setattr(scryfall, "get_collection", offline)
    monkeypatch.setattr(scryfall, "get_set_codes", offline)
    monkeypatch.setattr(scryfall, "fuzzy_card", lambda name: None)
