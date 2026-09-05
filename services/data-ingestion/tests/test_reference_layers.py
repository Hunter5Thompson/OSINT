from reference_layers import nuclear_sites, region_profiles


def test_nuclear_sites_do_not_promote_dataset_to_live_status():
    rows = [
        dict(
            primary_fuel="Nuclear",
            name="Reference plant",
            country="DEU",
            gppd_idnr="1",
            latitude="50",
            longitude="8",
            capacity_mw="1200",
        ),
        dict(primary_fuel="Gas"),
    ]
    sites = nuclear_sites(rows)
    assert len(sites) == 1
    assert sites[0]["kind"] == "nuclearPlants"
    assert "not live" in sites[0]["note"]
    assert "status" not in sites[0]


def test_region_capitals_require_same_country_and_containment():
    regions = {
        "features": [
            {
                "properties": {
                    "adm0_a3": "DEU",
                    "name": "Berlin",
                    "iso_3166_2": "DE-BE",
                    "iso_a2": "DE",
                    "type_en": "State",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[12, 51], [14, 51], [14, 53], [12, 53], [12, 51]]],
                },
            }
        ]
    }

    def city(country):
        return {
            "properties": {
                "ADM0_A3": country,
                "FEATURECLA": "Admin-0 capital",
                "NAME": "Berlin",
                "POP_MAX": 100,
                "TIMEZONE": "Europe/Berlin",
            },
            "geometry": {"type": "Point", "coordinates": [13, 52]},
        }

    assert region_profiles(regions, {"features": [city("FRA")]})[0]["capital"] is None
    assert region_profiles(regions, {"features": [city("DEU")]})[0]["capital"]["name"] == "Berlin"
    regions["features"][0]["properties"]["iso_a2"] = "RU"
    assert region_profiles(regions, {"features": [city("DEU")]}) == []
