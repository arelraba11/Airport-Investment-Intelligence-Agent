from backend.tools import resolve_airport


def test_resolve_airport_long_form_query_strips_noise_words():
    """Known gap since Phase A.5: a long free-text phrase like 'Boston Logan
    airport' used to return not_found even though 'Boston' alone resolved
    correctly. Fixed by stripping noise words (airport/international/etc.)
    and retrying the match on the cleaned query.
    """
    result = resolve_airport("Boston Logan airport")
    assert result.get("iata") == "BOS"


def test_resolve_airport_noisy_query_prefers_confident_stripped_match():
    """A noisy phrase can come back *ambiguous* rather than empty: "Santa Ana
    airport" fuzzy-matches SNA and SAT because "airport" dilutes the ratio
    toward San Antonio. The noise-word retry must run on the ambiguous path
    too, not only the not-found path, since "Santa Ana" alone is confident.

    This is required example question #2 ("Compare LA and Santa Ana airport
    congestion levels"), so an unnecessary disambiguation turn here is a
    user-visible regression.
    """
    result = resolve_airport("Santa Ana airport")
    assert result.get("iata") == "SNA"


def test_resolve_airport_long_noisy_query_not_pulled_to_wrong_candidates():
    """"International" pulls a long phrase toward every unrelated
    "... International" in the dataset: "Boston Logan International Airport"
    used to return ambiguous across PWM/PDX/MCO/RSW/LAX — a candidate list
    that didn't even contain BOS. Stripping the noise words resolves it.
    """
    result = resolve_airport("Boston Logan International Airport")
    assert result.get("iata") == "BOS"


def test_resolve_airport_noise_word_inside_real_airport_name():
    """The retry must strip noise words from the candidate names too, not just
    the query. "International" is genuinely part of BDL's name ("Bradley
    International"), so stripping one side only leaves "Bradley" as a weak
    0.57 match against the full name — weak enough that an unrelated airport
    wins on noise. Stripping both sides makes it an exact match.
    """
    result = resolve_airport("Bradley International Airport")
    assert result.get("iata") == "BDL"


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
