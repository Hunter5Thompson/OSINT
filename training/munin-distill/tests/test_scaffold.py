import munin_distill


def test_package_imports():
    assert hasattr(munin_distill, "__version__")
