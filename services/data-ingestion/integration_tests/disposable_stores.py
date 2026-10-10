"""Explicit local disposable store inputs for destructive integration fixtures."""

from urllib.parse import urlsplit

_KEYS = (
    "HN_TEST_NEO4J_URI", "HN_TEST_NEO4J_PASSWORD", "HN_TEST_REDIS_URL",
    "HN_TEST_QDRANT_URL", "HN_TEST_QDRANT_COLLECTION", "HN_TEST_TEI_EMBED_URL",
)


def require_disposable_config(inputs):
    if any(not isinstance(inputs.get(key), str) or not inputs[key].strip() for key in _KEYS):
        raise ValueError("Explicit disposable inputs are required; production defaults forbidden")
    result = {key: inputs[key] for key in _KEYS}
    for key, scheme, forbidden in (
        ("HN_TEST_NEO4J_URI", "bolt", 7687),
        ("HN_TEST_REDIS_URL", "redis", 6379),
        ("HN_TEST_QDRANT_URL", "http", 6333),
    ):
        uri = urlsplit(result[key])
        if (
            uri.scheme != scheme or uri.hostname not in {"localhost", "127.0.0.1"}
            or uri.port is None or uri.port <= 1024 or uri.port == forbidden
            or uri.username or uri.password or uri.query or uri.fragment
        ):
            raise ValueError("Store endpoint must be an explicit local disposable instance")
    if result["HN_TEST_QDRANT_COLLECTION"] != "hn_gdelt_isolated_20261010":
        raise ValueError("Qdrant collection must be the declared disposable test collection")
    return result


async def verify_disposable_markers(neo4j, redis, qdrant):
    """Read all isolation markers before the first fixture mutation."""
    async with neo4j._driver.session() as session:
        result = await session.run(
            "MATCH (:HNTestInstance {id: $marker}) RETURN true AS isolated",
            marker="hn-gdelt-isolated-20261010",
        )
        if await result.single() is None:
            raise ValueError("Neo4j disposable instance marker is missing")
    if await redis.get("hn:test:instance") != "hn-gdelt-isolated-20261010":
        raise ValueError("Redis disposable instance marker is missing")
    await qdrant.get_collection("hn_test_instance_20261010")
