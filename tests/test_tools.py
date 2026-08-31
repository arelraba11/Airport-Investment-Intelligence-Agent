"""Tests for resolve_airport's free-text matching (backend/tools.py).

Most cases below are pinned regressions, each recording a specific way the
matcher previously went wrong — a confident match to an unrelated airport, or
an unnecessary disambiguation turn. The docstrings keep the failing input and
its measured similarity ratio next to the assertion, because the ratios are
what show why the fix had to be a word-level gate rather than a higher
threshold.
"""

from backend.tools import resolve_airport


def test_resolve_airport_long_form_query_strips_noise_words():
    """A long free-text phrase like "Boston Logan airport" used to return
    not_found even though "Boston" alone resolved correctly. Fixed by
    stripping noise words (airport/international/etc.) and retrying the match
    on the cleaned query.
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
    """The word "International" pulls a long phrase toward every unrelated
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


def test_resolve_airport_out_of_scope_city_is_not_a_confident_match():
    """The query "Bar Harbor" used to resolve confidently to BDL (Bradley
    International, Hartford CT). "bar harbor" vs. the city "Hartford" scores
    0.5556 on SequenceMatcher — bare shared characters (a, r, h, o), no shared
    word — which cleared _FUZZY_MIN_RATIO as the *only* plausible candidate,
    so the confidence-margin check was skipped entirely.

    Bar Harbor's real airport (BHB) is genuinely out of scope, so the honest
    answer is not_found: a confident match to an unrelated airport in another
    state is worse than admitting the scope boundary.
    """
    assert resolve_airport("Bar Harbor") == {"not_found": True, "in_scope": False}


def test_resolve_airport_near_miss_city_name_is_not_a_confident_match():
    """The case that proves this is not fixable by raising the threshold:
    "Asheville" scores 0.8889 against "Nashville" — higher than almost every
    *legitimate* fuzzy match in the dataset (most sit at 0.55-0.65). Character
    similarity alone cannot separate a real match from a different city that
    happens to be spelled similarly; only requiring a shared whole word can.
    """
    assert resolve_airport("Asheville") == {"not_found": True, "in_scope": False}
    assert resolve_airport("Fresno") == {"not_found": True, "in_scope": False}


def test_resolve_airport_shared_generic_word_is_not_enough():
    """A single shared word must not carry a match on its own. "Santa Barbara"
    shares "Santa" with Santa Ana (SNA) and "Rapid City" shares "City" with
    Kansas City (MCI), but the remaining word is unaccounted for in both, so
    neither is a real reference to an in-scope airport.
    """
    assert resolve_airport("Santa Barbara") == {"not_found": True, "in_scope": False}
    assert resolve_airport("Rapid City") == {"not_found": True, "in_scope": False}


def test_resolve_airport_invented_place_names_are_not_found():
    """Made-up names used to land confident matches purely on character
    overlap ("Blorptown" -> BOS, "Grand Fenwick" -> GRR, "Nowhere City" -> OKC).
    """
    for query in ("Blorptown", "Grand Fenwick", "Nowhere City", "Zzyzx"):
        assert resolve_airport(query) == {"not_found": True, "in_scope": False}, query


def test_resolve_airport_out_of_scope_non_us_airport():
    """No regression: a well-known airport outside the US scope stays out."""
    assert resolve_airport("Heathrow") == {"not_found": True, "in_scope": False}
    assert resolve_airport("Nantucket") == {"not_found": True, "in_scope": False}


def test_resolve_airport_alias_beats_unrelated_fuzzy_match():
    """The query "sf airport" used to resolve to SRQ (Sarasota) on a 0.5556
    character match, beating the "sf" -> SFO alias that the noise-word retry would have
    found. Rejecting the unanchored fuzzy match lets the retry reach the alias.
    """
    assert resolve_airport("sf airport").get("iata") == "SFO"


def test_resolve_airport_tolerates_a_single_character_typo():
    """The word-level gate must still allow a mistyped word through: matching
    is per-word and fuzzy, not exact string equality."""
    assert resolve_airport("Bostn").get("iata") == "BOS"
    assert resolve_airport("Anchorag").get("iata") == "ANC"
