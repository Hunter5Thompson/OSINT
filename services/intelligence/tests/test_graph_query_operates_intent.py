from agents.tools.graph_query import _match_intent


def test_betreibt_question_routes_to_relationship_template():
    # Quoted CANONICAL operator name. Two reasons it must be quoted+canonical:
    # (1) the proper-noun heuristic on unquoted text is brittle (it would extract
    #     "Systeme Heer?" from "Welche Systeme betreibt das Heer?"), and
    # (2) OPERATES edges attach to "Deutsches Heer" (the seed's canonical operator),
    #     NOT "Heer" — so only the canonical name actually retrieves the edges.
    tmpl, params = _match_intent('Welche Systeme betreibt "Deutsches Heer"?')
    assert tmpl == "one_hop" and params == {"name": "Deutsches Heer"}


def test_operates_keyword_routes_to_relationship_template():
    tmpl, params = _match_intent('what does "Deutsche Luftwaffe" operate')
    assert tmpl == "one_hop" and params == {"name": "Deutsche Luftwaffe"}
