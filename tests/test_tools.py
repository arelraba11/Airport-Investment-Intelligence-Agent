from backend.tools import resolve_airport


def test_resolve_airport_long_form_query_strips_noise_words():
    """Known gap since Phase A.5: a long free-text phrase like 'Boston Logan
    airport' used to return not_found even though 'Boston' alone resolved
    correctly. Fixed by stripping noise words (airport/international/etc.)
    and retrying the match on the cleaned query.
    """
    result = resolve_airport("Boston Logan airport")
    assert result.get("iata") == "BOS"


def test_resolve_airport_short_city_name_still_resolves():
    """No regression: the short form this used to work through must still work."""
    result = resolve_airport("Anchorage")
    assert result.get("iata") == "ANC"


def test_resolve_airport_no_match_stays_not_found():
    """No regression: a city with no in-scope airport must not become a
    false match once noise-word stripping is added."""
    result = resolve_airport("Springfield")
    assert result == {"not_found": True, "in_scope": False}


def test_resolve_airport_portland_still_ambiguous():
    """No regression: a genuine collision (PDX vs PWM) must still be
    surfaced as ambiguous, not resolved outright by the new fallback pass."""
    result = resolve_airport("Portland")
    assert result.get("ambiguous") is True
    candidates = {c["iata"] for c in result["candidates"]}
    assert candidates == {"PDX", "PWM"}
