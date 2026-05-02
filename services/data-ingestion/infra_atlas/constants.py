"""Verified Wikidata identifiers used by the infra_atlas builders.

Every Q-ID and P-ID below has been resolved live against
https://www.wikidata.org/wiki/Special:EntityData/<id>.json on 2026-05-01 and
its English label is recorded inline. Do NOT add new IDs from memory — verify
each one and add the label as a comment, then ensure the integration test
(tests/integration/test_constants_resolve_live.py) covers it.
"""

from __future__ import annotations

# Class Q-IDs (used as wdt:P31 or wdt:P31/wdt:P279* targets in SPARQL).
QID_OIL_REFINERY = "Q12353044"           # oil refinery
QID_LNG_TERMINAL = "Q15709854"           # liquefied natural gas terminal
QID_DATA_CENTER = "Q671224"              # data center

# Property IDs.
PID_INSTANCE_OF = "P31"                  # instance of
PID_SUBCLASS_OF = "P279"                 # subclass of
PID_COORDINATE_LOCATION = "P625"         # coordinate location
PID_OPERATOR = "P137"                    # operator
PID_OWNED_BY = "P127"                    # owned by  (NOT the same as operator;
                                         # P127 owners and P137 operators
                                         # routinely differ — e.g. a property
                                         # company owns a building, AWS
                                         # operates the data center inside)
PID_COUNTRY = "P17"                      # country
PID_COUNTRY_ISO_ALPHA2 = "P297"          # ISO 3166-1 alpha-2 code
PID_LOCATED_IN = "P131"                  # located in the administrative
                                         # territorial entity
PID_IMAGE = "P18"                        # image
PID_NOMINAL_POWER = "P2109"              # nominal power output (W)
PID_PRODUCTION_RATE = "P2197"            # production rate
                                         # (NOTE: live coverage is 0 across
                                         # Q12353044 — never used as the
                                         # source for capacity_bpd.)

# Schema-extension constants used by builders.
COORD_QUALITY_CAMPUS_VERIFIED = "campus_verified"
COORD_QUALITY_WIKIDATA_VERIFIED = "wikidata_verified"
COORD_QUALITY_LEGACY = "legacy"          # default for unenriched existing entries

COORD_SOURCE_WIKIDATA = "wikidata"
