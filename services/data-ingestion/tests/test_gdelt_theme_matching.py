from gdelt_raw.theme_matching import compile_patterns, matches_any, any_match_in_themes


def test_exact_match():
    matcher = compile_patterns(["NUCLEAR", "ARMEDCONFLICT"])
    assert matches_any("NUCLEAR", matcher)
    assert matches_any("ARMEDCONFLICT", matcher)
    assert not matches_any("CYBER_ATTACK", matcher)


def test_prefix_match_star():
    matcher = compile_patterns(["CRISISLEX_*", "WEAPONS_*"])
    assert matches_any("CRISISLEX_T03_DEAD", matcher)
    assert matches_any("CRISISLEX_CRISISLEXREC", matcher)
    assert matches_any("WEAPONS_PROLIFERATION", matcher)
    assert not matches_any("UNRELATED_THEME", matcher)


def test_mixed_exact_and_prefix():
    matcher = compile_patterns(["NUCLEAR", "CRISISLEX_*"])
    assert matches_any("NUCLEAR", matcher)
    assert matches_any("CRISISLEX_T11_UPDATESSYMPATHY", matcher)
    # prefix must anchor at START — avoid false positives:
    assert not matches_any("PRE_NUCLEAR_FALLOUT", matcher)


def test_any_match_in_themes_list():
    matcher = compile_patterns(["NUCLEAR", "CRISISLEX_*"])
    assert any_match_in_themes(
        ["FOO", "BAR", "CRISISLEX_T03_DEAD"], matcher
    )
    assert not any_match_in_themes(["FOO", "BAR"], matcher)
    assert not any_match_in_themes([], matcher)


def test_case_sensitive_exact():
    # GDELT themes are always upper-case; we enforce case-sensitive match.
    matcher = compile_patterns(["NUCLEAR"])
    assert not matches_any("nuclear", matcher)
