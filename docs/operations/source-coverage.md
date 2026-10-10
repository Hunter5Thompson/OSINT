# Quellenabdeckung: FIRMS und Militärflugzeuge

Dies beschreibt die Konfiguration des geprüften Repo-Source, keine frisch
verifizierte produktive Abdeckung. Gebietsschlüssel sind technische Namen für
Operationsrechtecke; sie sind keine Ländergrenzen oder Herkunftsnachweise.
Die UI nennt ausgewählte Regionen und fehlende globale Vollständigkeit.

## FIRMS

`feeds/firms_collector.py` fragt drei VIIRS-NRT-Quellen ab: SNPP, NOAA20, NOAA21.
Die9Rechtecke haben folgendes Format in Grad: west,south,east,north.
NASA beschreibt den [Area-API-Vertrag](https://firms2.modaps.eosdis.nasa.gov/api/area/)
mit einem Rechteck oder `world`. ODIN verwendet hier die ausgewählten Rechtecke:

| Schlüssel / Operationsgebiet | West | Süd | Ost | Nord |
|---|---:|---:|---:|---:|
| ukraine |22.0|44.0|40.0|52.5|
| russia |30.0|50.0|60.0|70.0|
| iran |44.0|25.0|63.5|39.8|
| israel_gaza |34.0|29.5|35.9|33.5|
| syria |35.5|32.0|42.5|37.5|
| taiwan |119.0|21.5|122.5|25.5|
| north_korea |124.0|37.5|130.5|42.5|
| saudi_arabia |36.5|16.0|55.5|32.2|
| turkey |26.0|36.0|44.8|42.2|

Überschneidungen sind möglich. `country_iso3` stammt aus dem Spatialkatalog;
der Fetchschlüssel wird nicht zur Ortsidentität. Fehlende Treffer außerhalb der
Gebiete oder bei Fetchausfall beweisen keine Abwesenheit thermischer Anomalien.
Die API zeigt zuletzt ingestierte FIRMS-Daten im angeforderten Ingestionszeitfenster,
begrenzt den Scroll auf ungefähr5000Datensätze; der Layer zeigt maximal400.
Weder APIliste noch sichtbare Punkte sind eine vollständige Weltkarte.
Beobachtungszeit, Ingestionszeit und Abrufzeit bleiben verschiedene Begriffe.

## Militärflugzeuge

`REGION_BBOXES` enthält dieselben9Gebiete, in der anderen Reihenfolge
south,north,west,east. Dazu kommen pacific=(0,60,100,180) und
western=(25,75,-25,45); beide werden bei der Regionsklassifikation ausgelassen
und dienen der erweiterten Abfrage. Präsenz im Rechteck beweist weder Land noch
Teilstreitkraft. Technische Schlüssel und Cacheverträge bleiben unverändert.

Weltweite Collection erfordert eine eigene Entscheidung über Quota, Frequenz,
Kosten und Datumsgrenze. X02 autorisiert dafür keinen Download oder Betriebscutover.
FRP-Farben und Explosionsheuristiken wurden nicht geändert.
