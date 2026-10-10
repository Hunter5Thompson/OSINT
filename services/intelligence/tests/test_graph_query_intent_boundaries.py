"""L01: explicit phrases must not match inside unrelated words."""

import pytest

from agents.tools.graph_query import _match_intent


@pytest.mark.parametrize(
    ("question", "template", "params"),
    [
        ('resources of "NATO"', "entity_lookup", {"name": "NATO"}),
        ('does "NATO" cooperate?', "entity_lookup", {"name": "NATO"}),
        ('does "NATO" cooperates?', "entity_lookup", {"name": "NATO"}),
        ('Tell me about "Source Network"', "entity_lookup", {"name": "Source Network"}),
        ("events involving the 5th fleet", "events_by_entity", {"name": "the 5th fleet"}),
        ('EVENTS INVOLVING "5th Fleet"?', "events_by_entity", {"name": "5th Fleet"}),
        ("events in Black Sea", "event_timeline", {"location": "Black Sea"}),
        ("EVENTS AT black sea?", "event_timeline", {"location": "black sea"}),
        ('events inside "Ukraine"', "entity_lookup", {"name": "Ukraine"}),
        ("timeline", None, {}),
        ("events in", None, {}),
        ('SOURCES FOR "NATO"!', "source_backed", {"name": "NATO"}),
        ('What does "NATO" operate?', "one_hop", {"name": "NATO"}),
        ('Procurement for "NATO"?', "one_hop", {"name": "NATO"}),
        ("TOP ENTITIES?", "top_connected", {}),
    ],
)
def test_reviewed_intent_boundaries(question, template, params):
    assert _match_intent(question) == (template, params)
