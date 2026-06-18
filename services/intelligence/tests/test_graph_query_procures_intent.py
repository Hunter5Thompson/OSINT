from agents.tools.graph_query import _match_intent


def test_procurement_question_routes_to_relationship_template():
    tmpl, params = _match_intent('Welche Vorhaben beschafft "Deutsche Luftwaffe"?')
    assert tmpl == "one_hop" and params == {"name": "Deutsche Luftwaffe"}
