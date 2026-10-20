# Extra websites

Caddy laadt naast de declaratietool ook elk bestand `sites/*.caddy`. Zo kun je op dezelfde
server een extra (sub)domein laten draaien, met automatisch een https-certificaat.

De `*.caddy`-bestanden staan niet in git (zie `.gitignore`): ze bevatten je eigen domein en
wachtwoord-hash, en de knop **Bijwerken** laat ze met rust.

Kant-en-klaar voorbeeld: [`qr.caddy.example`](qr.caddy.example), een pagina met wachtwoord
waarop je van een URL een QR-code maakt. Zie [docs/qr.md](../docs/qr.md).
