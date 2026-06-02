from app.services.country_almanac import get_country_almanac_store


def test_store_exposes_factbook_revision_and_is_cached():
    get_country_almanac_store.cache_clear()
    a = get_country_almanac_store()
    b = get_country_almanac_store()
    assert a is b                                # cached singleton
    assert a.factbook_revision                   # loaded from _meta
    assert a.refreshed_at
