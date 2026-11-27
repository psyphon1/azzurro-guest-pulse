import json
from pathlib import Path

import pytest

from scraper.parse import parse_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_payload():
    return json.loads((FIXTURES / "olympic_reviewlist_page1.json").read_text())


@pytest.fixture
def sample_page(raw_payload):
    return parse_page(raw_payload, property_slug="olympic-paddington")
