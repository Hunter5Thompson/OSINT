# Operatorzugriff auf Modellaufrufe und Dossiers

BP-01 ergänzt den bestehenden HN-B10/D09-Zugriffsvertrag. Alle vom Backend
angebotenen LLM-Auslöser benötigen nun `X-Admin-Token`, auch globale Analysen:

| Methode | Route unter `/api` |
|---|---|
| POST | `/intel/query` (global und mit `report_id`) |
| POST | `/intel/hotspot/{hotspot_id}` |
| POST | `/almanac/countries/{country_id}/briefing` |
| POST | `/almanac/country/briefing` |

`require_operator_access` wählt wie bisher den ersten nach Whitespace-Bereinigung
nichtleeren Wert aus `REPORTS_ADMIN_TOKEN`, danach `INCIDENTS_ADMIN_TOKEN`.
Berichtmutationen und beide Briefing-Speicherpfade verwenden dieselbe Dependency.
Ein fehlender/falscher Requesttoken liefert 401, fehlende Serverkonfiguration 503
mit der bestehenden Detailmeldung. Die Prüfung läuft vor SSE, Spatial-Auflösung,
Berichtzugriff, Nachrichtenspeicherung und Intelligence-HTTP. Öffentliche
Almanac-Leseendpunkte und die bisherige flüchtige Analysehistorie bleiben lesbar.

Der Browser-Dossierchat sendet selbst keinen Operator-Token. Das opt-in Gateway
ergänzt ihn serverseitig für die vier POST-Routen sowie bestehende
Berichtmutationen, Nachrichten und Briefing-Saves. Andere API-Routen erhalten
keinen Token. Ein von nginx als nichtleer gelesener mitgesendeter Token wird
unverändert weitergereicht; ein falscher Token wird nicht ersetzt. Leere
HTTP-Header gelten hier wie fehlende Header. Direkt am Backend führt ein leerer
oder nur aus Whitespace bestehender Token weiterhin zu 401.
SSE wird ohne nginx-Buffering weitergegeben. Dies ist keine Begrenzung
gleichzeitiger Modellaufrufe; die gehört zu BP-02.

## Releasevorbereitung und Aktivierung

Die Templates und der Start-Hook sind Bestandteil des Frontendimages.
Standardmäßig bleibt das Gateway ausgeschaltet. Nur ein Backend-/Frontendpaar
aus derselben geprüften Revision zusammen zur gesonderten Deploymentfreigabe
vorbereiten. Ein Backend-Rollout ohne passenden Gateway-Pfad unterbricht den
Browserchat und die Briefing-Generatoren.

1. Den ausgewählten Backendtoken zusätzlich als geschützte Secret-Datei außerhalb
   des Checkouts bereitstellen. Für das Gateway gilt das bisherige Format:
   32–128 Zeichen aus `A-Za-z0-9_-`; umgebender Whitespace wird entfernt.
2. In der privaten Release-Envdatei ausschließlich den Dateipfad setzen:
   `ODIN_OPERATOR_TOKEN_FILE=/data/odin-secrets/operator-token`.
   Der Dateiinhalt muss zur oben beschriebenen Backendauswahl passen.
3. Die Release-Konfiguration mit dem zusätzlichen Flag auswählen:

   ```bash
   ./odin.sh --env-file /data/odin-releases/<release>/release.env --release --operator-gateway doctor
   ```

   Das Flag ergänzt `docker-compose.operator-gateway.yml` nach den Release- und
   gegebenenfalls Tracing-Overlays. Es erzwingt für das Frontend Loopback
   `127.0.0.1:5173` und mountet ein Compose-Secret nach
   `/run/secrets/odin_operator_token`. Für freigegebene spätere Start-, Status-
   und Recoverykommandos dieselben Flags verwenden.

Der Hook liest die Secret-Datei erst beim Containerstart und rendert nur
nginx-Konfiguration außerhalb des Document-Roots mit restriktiver Dateimaske.
Fehlende oder ungültige Secrets verhindern den Start. Weder `VITE_*` noch
Buildargumente, Imageinhalt oder statische Assets erhalten diesen Token.
Die bestehende optionale `VITE_ADMIN_TOKEN`-Konfiguration des Frontendclients
darf dafür nicht verwendet werden; sie würde einen Token ins Browserbundle
einbetten. Das Gateway benötigt sie nicht.

## Origin-Vertrag

Für POST/PATCH/DELETE auf den freigeschalteten Pfaden gilt:

- Ein angegebener Origin muss exakt Schema und Host einschließlich Port der
  nginx-Anfrage entsprechen. Fremde Origins und `Origin: null` liefern 403.
- `Sec-Fetch-Site: cross-site` liefert auch bei fehlendem oder passendem Origin 403.
- Fehlender Origin ohne Cross-Site-Marker bleibt für lokale Operatorwerkzeuge
  ausdrücklich erlaubt. Dieser Pfad ist mitgetestet.

Die Ablehnung erfolgt vor dem Backend. Die Origin-Regel ersetzt keine
Benutzeridentität. Das Gateway vertraut lokalen Zugriffen auf seinen
Loopbackport. Weiterleitungen, zusätzliche Nutzer oder andere Netzbindungen
brauchen einen eigenen geprüften Zugriffsvertrag.

## Reproduktion

Im Backendverzeichnis:

```bash
uv sync --locked --all-extras
uv run pytest tests/unit/test_operator_access.py tests/unit/test_admin_auth.py -q
uv run pytest ../../tests/ops/test_operator_gateway.py -q
```

Für den tatsächlichen nginx-/Backend-/Browserpfad zuerst im Frontendverzeichnis
`npm ci`, `npm run build` und `npx playwright install chromium` ausführen.
Auf der Workstation Browserdownloads mit `PLAYWRIGHT_BROWSERS_PATH` nach `/data`
legen; denselben Wert beim Testaufruf setzen. Dann im Backendverzeichnis:

```bash
ODIN_GATEWAY_STATIC_ROOT="$PWD/../frontend/dist" \
  uv run pytest integration_tests/test_operator_gateway.py -q
```

Diese Tests verwenden das im Dockerfile gepinnte nginx-Image, eigene Container
und kurzlebige Loopbackports. Der Adapter nutzt echte Backendrouten mit isolierten
Store- und Intelligence-Fakes, ohne App-Lifespan und ohne produktive Datenbank.
Der Browser verwendet das gebaute SPA, sendet die Dossierfrage über nginx,
empfängt SSE und liest nach Reload die Fake-Chatpersistenz. Der Runtime-Testtoken
wird zusätzlich in allen ausgelieferten statischen Dateien gesucht. Die
CI-Aufgabe `gateway · operator access and built dossier chat` wiederholt dies.

## Rollback

Backend und Frontend gemeinsam auf das zuvor geprüfte Imagepaar und dessen
Gatewaykonfiguration zurückstellen. Ein Entfernen des Gateway-Flags bei neuem
Backend führt absichtlich zu 401 für Browser-Modellaufrufe. Das allein ist kein
funktionaler Rollback. BP-01 ändert keine gespeicherten Daten und benötigt keine
Datenmigration. Produktivrollout und Rollback wurden mit diesem Quellpaket nicht
ausgeführt.
