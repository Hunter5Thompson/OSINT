# X01 — Hotspot-Vertrag zur Entscheidung

Stand10.10.2026: Vorlage, keine neue Produktpolicy oder Datenfreigabe.
A03/D06 erhalten den bisherigen Vertrag. Empfehlung für den nächsten Release:

| Entscheidung | Konkrete Empfehlung | Folgen / Alternative |
|---|---|---|
| Stufen | CRITICAL/HIGH/ELEVATED/MODERATE behalten; producerLOW wird ausdrücklich als MODERATE komprimiert | LOW/UNKNOWN benötigt separaten Modell-, Farb-, API- und Cachevertrag |
| Snapshot | `hotspots:all` bleibt vollständiger kuratierter Snapshot | Bei Messausfall gültigen Vorwert desselben aktiven IDs erhalten; ohne Vorwert kuratierte Basis. Entfernte kuratierte IDs nicht wiederbeleben, keine Default-Union. Redis-Schreibfehler ist kein erfolgreicher Snapshot |
| IDs | Für eine spätere Vereinheitlichung Updater-IDs vorschlagen, Default-IDs als geprüfte Aliase | Aktuell keine IDs ändern. Nähe allein beweist keine gleiche Bedeutung; Kandidateninventar unter evidence/G04/B06/hotspot-catalog-candidates.json. Alias-/Migrationsimplementierung braucht eigene Abnahme |
| Datenstatus | Kuratierte Basis, erfolgreiche Messung und erhaltenen Altstand sichtbar unterscheiden | A03 führt im Einzelcache `measurement_status`/`measurement_at`, unbekannte Zählung bleibtnull; API-Stufen unverändert. `last_updated` ist Cache-/Recordzeit, kein Beweis für eine erfolgreiche Quellenmessung. Additiver Anzeigevertrag gesondert vorbereiten |

**Taiwan:** Backend-/Updaterpunkte bleiben unverändert. Ein Geografiereferenzpunkt
muss die intendierte Meerenge statt eines beliebigen Operationsgebiets abbilden.
NGA Pub157 beschreibt die Meerenge zwischen Taiwans Westküste und der Festlandküste
([primäre Publikation](https://msi.nga.mil/api/publications/download?key=16694491%2FSFH00000%2FPub157bk.pdf)).
Der verfügbare Suchindex belegt diese Beschreibung; vollständige PDF-/Koordinaten-
prüfung blieb am Webtool-Größenlimit offen. Der MarineRegions-Punkt mit192km
Genauigkeit und Wikipedia als Ursprung wird nicht als präzise Ortsfreigabe übernommen.
IHO-Draft-2002-Abruf war502; Draft ist ohnehin keine aktuelle Normfreigabe.
Exakter Referenzpunkt und Gebietssemantik bleiben als eigene Entscheidung offen.

**Abnahmefälle:** A03 prüft Fehler/0/>15/>30, erhaltenen Einzel-/Gesamtcache,
fehlenden/kaputten Vorwert, bewusste Entfernung und Redis-Schreibfehler. D06 prüft
Null-/Nichttext-/Whitespace-Identität, optionale Texte und gesunde Nachbarn.
Diese Sourcebelege ersetzen keine produktive oder menschliche fachliche Abnahme.
Der bestehende Mention-Query scrollt höchstens100Titelmatches und enthält keinen
Zeitfilter; `recent_mentions` beweist daher keine Frische. Eine neue Zeit-/
Bedrohungspolitik wird aus A03 nicht abgeleitet und bleibt Teil der G06-Prüfung.
