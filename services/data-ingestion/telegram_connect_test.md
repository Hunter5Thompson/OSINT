# Telegram Connect Test

Einmalig im Terminal ausführen — erstellt die Session-Datei:

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/data-ingestion && uv run python -c "
from telethon import TelegramClient
client = TelegramClient('/tmp/odin_test_session', 39501469, 'c238fa19a7714bd3fea72ff00f994774')
client.start()
print('Connected! User:', client.get_me().first_name)
client.disconnect()
"
```

Es wird interaktiv fragen:
1. **Phone number:** Deine Nummer mit Ländervorwahl (z.B. `+491234567890`)
2. **Code:** Den Code den Telegram in die Desktop-App schickt
3. Optional: **2FA Passwort** falls aktiviert

Nach erfolgreichem Connect: Session-Datei liegt unter `/tmp/odin_test_session.session`
