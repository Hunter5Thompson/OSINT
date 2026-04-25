from gdelt_raw.normalize import normalize_entity_name


def test_lowercases_and_collapses_whitespace():
    assert normalize_entity_name("Vladimir   Putin") == "vladimir putin"


def test_strips_surrounding_punctuation():
    assert normalize_entity_name("NATO (Alliance)") == "nato alliance"


def test_keeps_alphanum_and_spaces_only():
    assert normalize_entity_name("Jean-Claude Van Damme!!!") == "jean claude van damme"


def test_does_not_drop_tokens():
    # This is normalization, not entity-resolution — all tokens stay.
    assert normalize_entity_name("Dr. Vladimir Putin") == "dr vladimir putin"


def test_unicode_preserved():
    assert normalize_entity_name("Владимир Путин") == "владимир путин"


def test_empty_and_whitespace_return_empty():
    assert normalize_entity_name("") == ""
    assert normalize_entity_name("   ") == ""
