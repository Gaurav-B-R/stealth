"""Home country (current_residence_country) is a real answer, never a default.

2026-08-24: the signup dropdown offered only the 9 pricing countries and pre-selected
"United States"; Google signups hardcoded it; the schema and the DB column defaulted to it.
Every skipped field silently recorded a US home country, and the AI surfaces (chat,
shortlists, prep interviews) reasoned from it. Now: full canonical list in app/countries.py,
mirrored verbatim in static/app.js, required at signup and at onboarding, no defaults.

Run: cd web_app && python3 -m pytest tests/test_residence_country.py
"""

import re
from pathlib import Path

import pytest

from app import countries, models, schemas

WEB_APP = Path(__file__).resolve().parents[1]


def test_normalizer_accepts_canonical_names_aliases_and_rejects_junk():
    n = countries.normalize_residence_country
    assert n("India") == "India"
    assert n("  india ") == "India"
    assert n("USA") == "United States"
    assert n("UK") == "United Kingdom"
    assert n("UAE") == "United Arab Emirates"
    assert n("viet nam") == "Vietnam"
    assert n("", required=False) is None
    with pytest.raises(ValueError, match="Select your current country"):
        n("")
    with pytest.raises(ValueError, match="from the list"):
        n("Atlantis")
    for name in countries.RESIDENCE_COUNTRIES:
        assert n(name) == name
    for name in countries.POPULAR_RESIDENCE_COUNTRIES:
        assert name in countries.RESIDENCE_COUNTRIES


def test_no_united_states_defaults_remain():
    assert schemas.UserBase.model_fields["current_residence_country"].default is None
    assert models.User.__table__.columns["current_residence_country"].default is None
    auth_src = (WEB_APP / "app/routers/auth.py").read_text(encoding="utf-8")
    assert 'current_residence_country="United States"' not in auth_src
    assert 'current_residence_country=user.current_residence_country or "United States"' not in auth_src
    assert "normalize_residence_country(user.current_residence_country)" in auth_src
    onb_src = (WEB_APP / "app/routers/onboarding.py").read_text(encoding="utf-8")
    assert "Select your home country." in onb_src and "normalize_residence_country" in onb_src


def test_ui_list_matches_the_server_list_exactly():
    js = (WEB_APP / "static/app.js").read_text(encoding="utf-8")
    def js_array(name):
        m = re.search(name + r"\s*=\s*\[(.*?)\];", js, re.S)
        assert m, f"{name} not found in app.js"
        return re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))
    ui = [c.replace("\\'", "'") for c in js_array("RESIDENCE_COUNTRIES")]
    assert ui == countries.RESIDENCE_COUNTRIES
    popular = [c.replace("\\'", "'") for c in js_array("POPULAR_RESIDENCE_COUNTRIES")]
    assert popular == countries.POPULAR_RESIDENCE_COUNTRIES
    assert "countryInput.value = 'United States'" not in js
