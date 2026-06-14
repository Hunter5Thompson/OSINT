"""ISO-3166-1 alpha-2 -> (lat, lon) country centroids.

Coarse geocoding source for RSS events (geo_basis="country_centroid"). Derived
from the public Google "country-centroids" dataset (country code, latitude,
longitude). Approximate country centers; not city precision.
"""
from __future__ import annotations

import re

_CENTROIDS: dict[str, tuple[float, float]] = {
    "AD": (42.546245, 1.601554),
    "AE": (23.424076, 53.847818),
    "AF": (33.93911, 67.709953),
    "AG": (17.060816, -61.796428),
    "AI": (18.220554, -63.068615),
    "AL": (41.153332, 20.168331),
    "AM": (40.069099, 45.038189),
    "AN": (12.226079, -69.060087),
    "AO": (-11.202692, 17.873887),
    "AQ": (-75.250973, -0.071389),
    "AR": (-38.416097, -63.616672),
    "AS": (-14.270972, -170.132217),
    "AT": (47.516231, 14.550072),
    "AU": (-25.274398, 133.775136),
    "AW": (12.52111, -69.968338),
    "AZ": (40.143105, 47.576927),
    "BA": (43.915886, 17.679076),
    "BB": (13.193887, -59.543198),
    "BD": (23.684994, 90.356331),
    "BE": (50.503887, 4.469936),
    "BF": (12.364566, -1.561593),
    "BG": (42.733883, 25.48583),
    "BH": (25.930414, 50.637772),
    "BI": (-3.373056, 29.918886),
    "BJ": (9.30769, 2.315834),
    "BM": (32.321384, -64.75737),
    "BN": (4.535277, 114.727669),
    "BO": (-16.290154, -63.588653),
    "BR": (-14.235004, -51.92528),
    "BS": (25.03428, -77.39628),
    "BT": (27.514162, 90.433601),
    "BV": (-54.423199, 3.413194),
    "BW": (-22.328474, 24.684866),
    "BY": (53.709807, 27.953389),
    "BZ": (17.189877, -88.49765),
    "CA": (56.130366, -106.346771),
    "CC": (-12.164165, 96.870956),
    "CD": (-4.038333, 21.758664),
    "CF": (6.611111, 20.939444),
    "CG": (-0.228021, 15.827659),
    "CH": (46.818188, 8.227512),
    "CI": (7.539989, -5.54708),
    "CK": (-21.236736, -159.777671),
    "CL": (-35.675147, -71.542969),
    "CM": (3.848033, 11.502075),
    "CN": (35.86166, 104.195397),
    "CO": (4.570868, -74.297333),
    "CR": (9.748917, -83.753428),
    "CU": (21.521757, -77.781167),
    "CV": (16.002082, -24.013197),
    "CX": (-10.447525, 105.690449),
    "CY": (35.126413, 33.429859),
    "CZ": (49.817492, 15.472962),
    "DE": (51.165691, 10.451526),
    "DJ": (11.825138, 42.590275),
    "DK": (56.26392, 9.501785),
    "DM": (15.414999, -61.370976),
    "DO": (18.735693, -70.162651),
    "DZ": (28.033886, 1.659626),
    "EC": (-1.831239, -78.183406),
    "EE": (58.595272, 25.013607),
    "EG": (26.820553, 30.802498),
    "EH": (24.215527, -12.885834),
    "ER": (15.179384, 39.782334),
    "ES": (40.463667, -3.74922),
    "ET": (9.145, 40.489673),
    "FI": (61.92411, 25.748151),
    "FJ": (-16.578193, 179.414413),
    "FK": (-51.796253, -59.523613),
    "FM": (7.425554, 150.550812),
    "FO": (61.892635, -6.911806),
    "FR": (46.227638, 2.213749),
    "GA": (-0.803689, 11.609444),
    "GB": (55.378051, -3.435973),
    "GD": (12.262776, -61.604171),
    "GE": (42.315407, 43.356892),
    "GF": (3.933889, -53.125782),
    "GH": (7.946527, -1.023194),
    "GI": (36.137741, -5.345374),
    "GL": (71.706936, -42.604303),
    "GM": (13.443182, -15.310139),
    "GN": (9.945587, -9.696645),
    "GP": (16.995971, -62.067641),
    "GQ": (1.650801, 10.267895),
    "GR": (39.074208, 21.824312),
    "GS": (-54.429579, -36.587909),
    "GT": (15.783471, -90.230759),
    "GU": (13.444304, 144.793731),
    "GW": (11.803749, -15.180413),
    "GY": (4.860416, -58.93018),
    "GG": (49.465691, -2.585278),
    "HK": (22.396428, 114.109497),
    "HM": (-53.08181, 73.504158),
    "HN": (15.199999, -86.241905),
    "HR": (45.1, 15.2),
    "HT": (18.971187, -72.285215),
    "HU": (47.162494, 19.503304),
    "ID": (-0.789275, 113.921327),
    "IE": (53.41291, -8.24389),
    "IL": (31.046051, 34.851612),
    "IM": (54.236107, -4.548056),
    "IN": (20.593684, 78.96288),
    "IO": (-6.343194, 71.876519),
    "IQ": (33.223191, 43.679291),
    "IR": (32.427908, 53.688046),
    "IS": (64.963051, -19.020835),
    "IT": (41.87194, 12.56738),
    "JE": (49.214439, -2.13125),
    "JM": (18.109581, -77.297508),
    "JO": (30.585164, 36.238414),
    "JP": (36.204824, 138.252924),
    "KE": (-0.023559, 37.906193),
    "KG": (41.20438, 74.766098),
    "KH": (12.565679, 104.990963),
    "KI": (-3.370417, -168.734039),
    "KM": (-11.875001, 43.872219),
    "KN": (17.357822, -62.782998),
    "KP": (40.339852, 127.510093),
    "KR": (35.907757, 127.766922),
    "KW": (29.31166, 47.481766),
    "KY": (19.513469, -80.566956),
    "KZ": (48.019573, 66.923684),
    "LA": (19.85627, 102.495496),
    "LB": (33.854721, 35.862285),
    "LC": (13.909444, -60.978893),
    "LI": (47.166, 9.555373),
    "LK": (7.873054, 80.771797),
    "LR": (6.428055, -9.429499),
    "LS": (-29.609988, 28.233608),
    "LT": (55.169438, 23.881275),
    "LU": (49.815273, 6.129583),
    "LV": (56.879635, 24.603189),
    "LY": (26.3351, 17.228331),
    "MA": (31.791702, -7.09262),
    "MC": (43.750298, 7.412841),
    "MD": (47.411631, 28.369885),
    "ME": (42.708678, 19.37439),
    "MG": (-18.766947, 46.869107),
    "MH": (7.131474, 171.184478),
    "MK": (41.608635, 21.745275),
    "ML": (17.570692, -3.996166),
    "MM": (21.913965, 95.956223),
    "MN": (46.862496, 103.846656),
    "MO": (22.198745, 113.543873),
    "MP": (17.33083, 145.38469),
    "MQ": (14.641528, -61.024174),
    "MR": (21.00789, -10.940835),
    "MS": (16.742498, -62.187366),
    "MT": (35.937496, 14.375416),
    "MU": (-20.348404, 57.552152),
    "MV": (3.202778, 73.22068),
    "MW": (-13.254308, 34.301525),
    "MX": (23.634501, -102.552784),
    "MY": (4.210484, 101.975766),
    "MZ": (-18.665695, 35.529562),
    "NA": (-22.95764, 18.49041),
    "NC": (-20.904305, 165.618042),
    "NE": (17.607789, 8.081666),
    "NF": (-29.040835, 167.954712),
    "NG": (9.081999, 8.675277),
    "NI": (12.865416, -85.207229),
    "NL": (52.132633, 5.291266),
    "NO": (60.472024, 8.468946),
    "NP": (28.394857, 84.124008),
    "NR": (-0.522778, 166.931503),
    "NU": (-19.054445, -169.867233),
    "NZ": (-40.900557, 174.885971),
    "OM": (21.512583, 55.923255),
    "PA": (8.537981, -80.782127),
    "PE": (-9.189967, -75.015152),
    "PF": (-17.679742, -149.406843),
    "PG": (-6.314993, 143.95555),
    "PH": (12.879721, 121.774017),
    "PK": (30.375321, 69.345116),
    "PL": (51.919438, 19.145136),
    "PM": (46.941936, -56.27111),
    "PN": (-24.703615, -127.439308),
    "PR": (18.220833, -66.590149),
    "PS": (31.952162, 35.233154),
    "PT": (39.399872, -8.224454),
    "PW": (7.51498, 134.58252),
    "PY": (-23.442503, -58.443832),
    "QA": (25.354826, 51.183884),
    "RE": (-21.115141, 55.536384),
    "RO": (45.943161, 24.96676),
    "RS": (44.016521, 21.005859),
    "RU": (61.52401, 105.318756),
    "RW": (-1.940278, 29.873888),
    "SA": (23.885942, 45.079162),
    "SB": (-9.64571, 160.156194),
    "SC": (-4.679574, 55.491977),
    "SD": (12.862807, 30.217636),
    "SE": (60.128161, 18.643501),
    "SG": (1.352083, 103.819836),
    "SH": (-24.143474, -10.030696),
    "SI": (46.151241, 14.995463),
    "SJ": (77.553604, 23.670272),
    "SK": (48.669026, 19.699024),
    "SL": (8.460555, -11.779889),
    "SM": (43.94236, 12.457777),
    "SN": (14.497401, -14.452362),
    "SO": (5.152149, 46.199616),
    "SR": (3.919305, -56.027783),
    "SS": (4.859363, 31.571251),
    "ST": (0.18636, 6.613081),
    "SV": (13.794185, -88.89653),
    "SY": (34.802075, 38.996815),
    "SZ": (-26.522503, 31.465866),
    "TC": (21.694025, -71.797928),
    "TD": (15.454166, 18.732207),
    "TF": (-49.280366, 69.348557),
    "TG": (8.619543, 0.824782),
    "TH": (15.870032, 100.992541),
    "TJ": (38.861034, 71.276093),
    "TK": (-8.967363, -171.855881),
    "TL": (-8.874217, 125.727539),
    "TM": (38.969719, 59.556278),
    "TN": (33.886917, 9.537499),
    "TO": (-21.178986, -175.198242),
    "TR": (38.963745, 35.243322),
    "TT": (10.691803, -61.222503),
    "TV": (-7.109535, 177.64933),
    "TW": (23.69781, 120.960515),
    "TZ": (-6.369028, 34.888822),
    "UA": (48.379433, 31.16558),
    "UG": (1.373333, 32.290275),
    "UM": (19.2823192688, 166.6470931462),
    "US": (37.09024, -95.712891),
    "UY": (-32.522779, -55.765835),
    "UZ": (41.377491, 64.585262),
    "VA": (41.902916, 12.453389),
    "VC": (12.984305, -61.287228),
    "VE": (6.42375, -66.58973),
    "VG": (18.420695, -64.639968),
    "VI": (18.335765, -64.896335),
    "VN": (14.058324, 108.277199),
    "VU": (-15.376706, 166.959158),
    "WF": (-13.768752, -177.156097),
    "WS": (-13.759029, -172.104629),
    "XK": (42.602636, 20.902977),
    "YE": (15.552727, 48.516388),
    "YT": (-12.8275, 45.166244),
    "ZA": (-30.559482, 22.937506),
    "ZM": (-13.133897, 27.849332),
    "ZW": (-19.015438, 29.154857),
}


def centroid_for(iso2: str) -> tuple[float, float] | None:
    return _CENTROIDS.get((iso2 or "").upper())


# ---------------------------------------------------------------------------
# Country-name → ISO-2 resolver
# ---------------------------------------------------------------------------

def _norm_name(s: str) -> str:
    """Normalize a country name for lookup: lowercase, strip, collapse whitespace,
    drop dots and apostrophes."""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(".", "").replace("'", "")
    return s


# Maps NORMALIZED country names (and common aliases) to ISO-2 codes.
# Every value MUST exist as a key in _CENTROIDS (enforced by assertion below).
_NAME_TO_ISO2: dict[str, str] = {
    # AD — Andorra
    "andorra": "AD",
    # AE — United Arab Emirates
    "united arab emirates": "AE",
    "uae": "AE",
    # AF — Afghanistan
    "afghanistan": "AF",
    # AG — Antigua and Barbuda
    "antigua and barbuda": "AG",
    "antigua": "AG",
    # AI — Anguilla
    "anguilla": "AI",
    # AL — Albania
    "albania": "AL",
    # AM — Armenia
    "armenia": "AM",
    # AN — Netherlands Antilles
    "netherlands antilles": "AN",
    # AO — Angola
    "angola": "AO",
    # AQ — Antarctica
    "antarctica": "AQ",
    # AR — Argentina
    "argentina": "AR",
    # AS — American Samoa
    "american samoa": "AS",
    # AT — Austria
    "austria": "AT",
    # AU — Australia
    "australia": "AU",
    # AW — Aruba
    "aruba": "AW",
    # AZ — Azerbaijan
    "azerbaijan": "AZ",
    # BA — Bosnia and Herzegovina
    "bosnia and herzegovina": "BA",
    "bosnia": "BA",
    "herzegovina": "BA",
    # BB — Barbados
    "barbados": "BB",
    # BD — Bangladesh
    "bangladesh": "BD",
    # BE — Belgium
    "belgium": "BE",
    # BF — Burkina Faso
    "burkina faso": "BF",
    # BG — Bulgaria
    "bulgaria": "BG",
    # BH — Bahrain
    "bahrain": "BH",
    # BI — Burundi
    "burundi": "BI",
    # BJ — Benin
    "benin": "BJ",
    # BM — Bermuda
    "bermuda": "BM",
    # BN — Brunei
    "brunei": "BN",
    "brunei darussalam": "BN",
    # BO — Bolivia
    "bolivia": "BO",
    "plurinational state of bolivia": "BO",
    # BR — Brazil
    "brazil": "BR",
    "brasil": "BR",
    # BS — Bahamas
    "bahamas": "BS",
    "the bahamas": "BS",
    # BT — Bhutan
    "bhutan": "BT",
    # BV — Bouvet Island
    "bouvet island": "BV",
    # BW — Botswana
    "botswana": "BW",
    # BY — Belarus
    "belarus": "BY",
    "byelorussia": "BY",
    # BZ — Belize
    "belize": "BZ",
    # CA — Canada
    "canada": "CA",
    # CC — Cocos Islands
    "cocos islands": "CC",
    "cocos keeling islands": "CC",
    # CD — Democratic Republic of the Congo
    "democratic republic of the congo": "CD",
    "dr congo": "CD",
    "drc": "CD",
    "congo kinshasa": "CD",
    "zaire": "CD",
    # CF — Central African Republic
    "central african republic": "CF",
    # CG — Republic of the Congo
    "republic of the congo": "CG",
    "congo brazzaville": "CG",
    "congo": "CG",
    # CH — Switzerland
    "switzerland": "CH",
    # CI — Ivory Coast / Côte d'Ivoire
    "ivory coast": "CI",
    "cote divoire": "CI",
    "cote d ivoire": "CI",
    # CK — Cook Islands
    "cook islands": "CK",
    # CL — Chile
    "chile": "CL",
    # CM — Cameroon
    "cameroon": "CM",
    # CN — China
    "china": "CN",
    "peoples republic of china": "CN",
    "prc": "CN",
    # CO — Colombia
    "colombia": "CO",
    # CR — Costa Rica
    "costa rica": "CR",
    # CU — Cuba
    "cuba": "CU",
    # CV — Cape Verde
    "cape verde": "CV",
    "cabo verde": "CV",
    # CX — Christmas Island
    "christmas island": "CX",
    # CY — Cyprus
    "cyprus": "CY",
    # CZ — Czech Republic / Czechia
    "czech republic": "CZ",
    "czechia": "CZ",
    # DE — Germany
    "germany": "DE",
    "deutschland": "DE",
    # DJ — Djibouti
    "djibouti": "DJ",
    # DK — Denmark
    "denmark": "DK",
    # DM — Dominica
    "dominica": "DM",
    # DO — Dominican Republic
    "dominican republic": "DO",
    # DZ — Algeria
    "algeria": "DZ",
    # EC — Ecuador
    "ecuador": "EC",
    # EE — Estonia
    "estonia": "EE",
    # EG — Egypt
    "egypt": "EG",
    # EH — Western Sahara
    "western sahara": "EH",
    # ER — Eritrea
    "eritrea": "ER",
    # ES — Spain
    "spain": "ES",
    "espana": "ES",
    # ET — Ethiopia
    "ethiopia": "ET",
    # FI — Finland
    "finland": "FI",
    # FJ — Fiji
    "fiji": "FJ",
    # FK — Falkland Islands
    "falkland islands": "FK",
    "malvinas": "FK",
    # FM — Micronesia
    "micronesia": "FM",
    "federated states of micronesia": "FM",
    # FO — Faroe Islands
    "faroe islands": "FO",
    # FR — France
    "france": "FR",
    # GA — Gabon
    "gabon": "GA",
    # GB — United Kingdom
    "united kingdom": "GB",
    "uk": "GB",
    "u k": "GB",
    "britain": "GB",
    "great britain": "GB",
    # GD — Grenada
    "grenada": "GD",
    # GE — Georgia
    "georgia": "GE",
    # GF — French Guiana
    "french guiana": "GF",
    # GG — Guernsey
    "guernsey": "GG",
    # GH — Ghana
    "ghana": "GH",
    # GI — Gibraltar
    "gibraltar": "GI",
    # GL — Greenland
    "greenland": "GL",
    # GM — Gambia
    "gambia": "GM",
    "the gambia": "GM",
    # GN — Guinea
    "guinea": "GN",
    # GP — Guadeloupe
    "guadeloupe": "GP",
    # GQ — Equatorial Guinea
    "equatorial guinea": "GQ",
    # GR — Greece
    "greece": "GR",
    # GS — South Georgia
    "south georgia": "GS",
    "south georgia and the south sandwich islands": "GS",
    # GT — Guatemala
    "guatemala": "GT",
    # GU — Guam
    "guam": "GU",
    # GW — Guinea-Bissau
    "guinea bissau": "GW",
    "guinea-bissau": "GW",
    # GY — Guyana
    "guyana": "GY",
    # HK — Hong Kong
    "hong kong": "HK",
    # HM — Heard Island
    "heard island": "HM",
    "heard island and mcdonald islands": "HM",
    # HN — Honduras
    "honduras": "HN",
    # HR — Croatia
    "croatia": "HR",
    "hrvatska": "HR",
    # HT — Haiti
    "haiti": "HT",
    # HU — Hungary
    "hungary": "HU",
    # ID — Indonesia
    "indonesia": "ID",
    # IE — Ireland
    "ireland": "IE",
    # IL — Israel
    "israel": "IL",
    # IM — Isle of Man
    "isle of man": "IM",
    # IN — India
    "india": "IN",
    # IO — British Indian Ocean Territory
    "british indian ocean territory": "IO",
    # IQ — Iraq
    "iraq": "IQ",
    # IR — Iran
    "iran": "IR",
    "islamic republic of iran": "IR",
    # IS — Iceland
    "iceland": "IS",
    # IT — Italy
    "italy": "IT",
    # JE — Jersey
    "jersey": "JE",
    # JM — Jamaica
    "jamaica": "JM",
    # JO — Jordan
    "jordan": "JO",
    # JP — Japan
    "japan": "JP",
    # KE — Kenya
    "kenya": "KE",
    # KG — Kyrgyzstan
    "kyrgyzstan": "KG",
    "kyrgyz republic": "KG",
    # KH — Cambodia
    "cambodia": "KH",
    "kampuchea": "KH",
    # KI — Kiribati
    "kiribati": "KI",
    # KM — Comoros
    "comoros": "KM",
    # KN — Saint Kitts and Nevis
    "saint kitts and nevis": "KN",
    "st kitts and nevis": "KN",
    # KP — North Korea
    "north korea": "KP",
    "dprk": "KP",
    "democratic peoples republic of korea": "KP",
    # KR — South Korea
    "south korea": "KR",
    "republic of korea": "KR",
    "korea": "KR",
    # KW — Kuwait
    "kuwait": "KW",
    # KY — Cayman Islands
    "cayman islands": "KY",
    # KZ — Kazakhstan
    "kazakhstan": "KZ",
    # LA — Laos
    "laos": "LA",
    "lao pdr": "LA",
    "lao peoples democratic republic": "LA",
    # LB — Lebanon
    "lebanon": "LB",
    # LC — Saint Lucia
    "saint lucia": "LC",
    "st lucia": "LC",
    # LI — Liechtenstein
    "liechtenstein": "LI",
    # LK — Sri Lanka
    "sri lanka": "LK",
    # LR — Liberia
    "liberia": "LR",
    # LS — Lesotho
    "lesotho": "LS",
    # LT — Lithuania
    "lithuania": "LT",
    # LU — Luxembourg
    "luxembourg": "LU",
    # LV — Latvia
    "latvia": "LV",
    # LY — Libya
    "libya": "LY",
    # MA — Morocco
    "morocco": "MA",
    # MC — Monaco
    "monaco": "MC",
    # MD — Moldova
    "moldova": "MD",
    "republic of moldova": "MD",
    # ME — Montenegro
    "montenegro": "ME",
    # MG — Madagascar
    "madagascar": "MG",
    # MH — Marshall Islands
    "marshall islands": "MH",
    # MK — North Macedonia
    "north macedonia": "MK",
    "macedonia": "MK",
    # ML — Mali
    "mali": "ML",
    # MM — Myanmar / Burma
    "myanmar": "MM",
    "burma": "MM",
    # MN — Mongolia
    "mongolia": "MN",
    # MO — Macau
    "macau": "MO",
    "macao": "MO",
    # MP — Northern Mariana Islands
    "northern mariana islands": "MP",
    # MQ — Martinique
    "martinique": "MQ",
    # MR — Mauritania
    "mauritania": "MR",
    # MS — Montserrat
    "montserrat": "MS",
    # MT — Malta
    "malta": "MT",
    # MU — Mauritius
    "mauritius": "MU",
    # MV — Maldives
    "maldives": "MV",
    # MW — Malawi
    "malawi": "MW",
    # MX — Mexico
    "mexico": "MX",
    # MY — Malaysia
    "malaysia": "MY",
    # MZ — Mozambique
    "mozambique": "MZ",
    # NA — Namibia
    "namibia": "NA",
    # NC — New Caledonia
    "new caledonia": "NC",
    # NE — Niger
    "niger": "NE",
    # NF — Norfolk Island
    "norfolk island": "NF",
    # NG — Nigeria
    "nigeria": "NG",
    # NI — Nicaragua
    "nicaragua": "NI",
    # NL — Netherlands / Holland
    "netherlands": "NL",
    "holland": "NL",
    # NO — Norway
    "norway": "NO",
    # NP — Nepal
    "nepal": "NP",
    # NR — Nauru
    "nauru": "NR",
    # NU — Niue
    "niue": "NU",
    # NZ — New Zealand
    "new zealand": "NZ",
    # OM — Oman
    "oman": "OM",
    # PA — Panama
    "panama": "PA",
    # PE — Peru
    "peru": "PE",
    # PF — French Polynesia
    "french polynesia": "PF",
    # PG — Papua New Guinea
    "papua new guinea": "PG",
    "png": "PG",
    # PH — Philippines
    "philippines": "PH",
    # PK — Pakistan
    "pakistan": "PK",
    # PL — Poland
    "poland": "PL",
    # PM — Saint Pierre and Miquelon
    "saint pierre and miquelon": "PM",
    # PN — Pitcairn
    "pitcairn": "PN",
    # PR — Puerto Rico
    "puerto rico": "PR",
    # PS — Palestine
    "palestine": "PS",
    "state of palestine": "PS",
    "palestinian territories": "PS",
    "west bank": "PS",
    "gaza": "PS",
    "gaza strip": "PS",
    # PT — Portugal
    "portugal": "PT",
    # PW — Palau
    "palau": "PW",
    # PY — Paraguay
    "paraguay": "PY",
    # QA — Qatar
    "qatar": "QA",
    # RE — Réunion
    "reunion": "RE",
    "la reunion": "RE",
    # RO — Romania
    "romania": "RO",
    # RS — Serbia
    "serbia": "RS",
    # RU — Russia
    "russia": "RU",
    "russian federation": "RU",
    # RW — Rwanda
    "rwanda": "RW",
    # SA — Saudi Arabia
    "saudi arabia": "SA",
    "ksa": "SA",
    # SB — Solomon Islands
    "solomon islands": "SB",
    # SC — Seychelles
    "seychelles": "SC",
    # SD — Sudan
    "sudan": "SD",
    # SE — Sweden
    "sweden": "SE",
    # SG — Singapore
    "singapore": "SG",
    # SH — Saint Helena
    "saint helena": "SH",
    "st helena": "SH",
    # SI — Slovenia
    "slovenia": "SI",
    # SJ — Svalbard and Jan Mayen
    "svalbard and jan mayen": "SJ",
    "svalbard": "SJ",
    # SK — Slovakia
    "slovakia": "SK",
    # SL — Sierra Leone
    "sierra leone": "SL",
    # SM — San Marino
    "san marino": "SM",
    # SN — Senegal
    "senegal": "SN",
    # SO — Somalia
    "somalia": "SO",
    # SR — Suriname
    "suriname": "SR",
    "surinam": "SR",
    # SS — South Sudan
    "south sudan": "SS",
    # ST — São Tomé and Príncipe
    "sao tome and principe": "ST",
    "sao tome": "ST",
    # SV — El Salvador
    "el salvador": "SV",
    # SY — Syria
    "syria": "SY",
    "syrian arab republic": "SY",
    # SZ — Eswatini / Swaziland
    "eswatini": "SZ",
    "swaziland": "SZ",
    # TC — Turks and Caicos Islands
    "turks and caicos islands": "TC",
    "turks and caicos": "TC",
    # TD — Chad
    "chad": "TD",
    # TF — French Southern Territories
    "french southern territories": "TF",
    # TG — Togo
    "togo": "TG",
    # TH — Thailand
    "thailand": "TH",
    # TJ — Tajikistan
    "tajikistan": "TJ",
    # TK — Tokelau
    "tokelau": "TK",
    # TL — Timor-Leste
    "timor leste": "TL",
    "east timor": "TL",
    # TM — Turkmenistan
    "turkmenistan": "TM",
    # TN — Tunisia
    "tunisia": "TN",
    # TO — Tonga
    "tonga": "TO",
    # TR — Turkey / Türkiye
    "turkey": "TR",
    "turkiye": "TR",
    # TT — Trinidad and Tobago
    "trinidad and tobago": "TT",
    "trinidad": "TT",
    # TV — Tuvalu
    "tuvalu": "TV",
    # TW — Taiwan
    "taiwan": "TW",
    "republic of china": "TW",
    # TZ — Tanzania
    "tanzania": "TZ",
    "united republic of tanzania": "TZ",
    # UA — Ukraine
    "ukraine": "UA",
    # UG — Uganda
    "uganda": "UG",
    # UM — U.S. Minor Outlying Islands
    "us minor outlying islands": "UM",
    "united states minor outlying islands": "UM",
    # US — United States
    "united states": "US",
    "usa": "US",
    "us": "US",
    "u s": "US",
    "united states of america": "US",
    # UY — Uruguay
    "uruguay": "UY",
    # UZ — Uzbekistan
    "uzbekistan": "UZ",
    # VA — Vatican City
    "vatican city": "VA",
    "holy see": "VA",
    # VC — Saint Vincent and the Grenadines
    "saint vincent and the grenadines": "VC",
    "st vincent and the grenadines": "VC",
    # VE — Venezuela
    "venezuela": "VE",
    "bolivarian republic of venezuela": "VE",
    # VG — British Virgin Islands
    "british virgin islands": "VG",
    # VI — U.S. Virgin Islands
    "us virgin islands": "VI",
    "united states virgin islands": "VI",
    # VN — Vietnam
    "vietnam": "VN",
    "viet nam": "VN",
    # VU — Vanuatu
    "vanuatu": "VU",
    # WF — Wallis and Futuna
    "wallis and futuna": "WF",
    # WS — Samoa
    "samoa": "WS",
    # XK — Kosovo
    "kosovo": "XK",
    # YE — Yemen
    "yemen": "YE",
    # YT — Mayotte
    "mayotte": "YT",
    # ZA — South Africa
    "south africa": "ZA",
    # ZM — Zambia
    "zambia": "ZM",
    # ZW — Zimbabwe
    "zimbabwe": "ZW",
}

# Invariant: every ISO-2 value in _NAME_TO_ISO2 must exist in _CENTROIDS.
assert all(iso2 in _CENTROIDS for iso2 in _NAME_TO_ISO2.values()), (
    "BUG: _NAME_TO_ISO2 contains ISO-2 code(s) missing from _CENTROIDS"
)


def resolve_iso2(value: str | None) -> str | None:
    """Resolve a country name or ISO-2 code to a canonical ISO-2 code.

    Accepts:
    - A valid ISO-2 code (case-insensitive, must be present in _CENTROIDS)
    - A known country name or alias (full names, common abbreviations)

    Returns the uppercase ISO-2 string, or None if unrecognized.
    """
    if not value:
        return None
    up = value.strip().upper()
    if len(up) == 2 and up in _CENTROIDS:
        return up
    return _NAME_TO_ISO2.get(_norm_name(value))
