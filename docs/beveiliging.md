# Beveiliging

## Wat de tool zelf doet

- **Versleutelde verbinding.** Caddy haalt automatisch een https-certificaat op en dwingt https af (HSTS).
- **Alleen het nodige staat open.** De database is niet van buitenaf bereikbaar en de app luistert alleen
  op de server zelf (`127.0.0.1:8000`); alleen Caddy (poort 80 en 443) is publiek.
- **Wachtwoorden** worden opgeslagen als scrypt-hash, nooit leesbaar.
- **Wachtwoorden raden** wordt afgeremd: na 5 foute pogingen op één account, of 20 vanaf één IP-adres,
  moet je 15 minuten wachten.
- **Logboek**: beheerders zien onder Logboek elke geslaagde en mislukte inlogpoging met tijd, IP-adres en
  reden, en alle binnengekomen mail. Na 90 dagen worden de regels automatisch verwijderd.
- **Inlogsessie** zit in een ondertekend cookie (alleen via https, niet vanaf andere sites mee te sturen,
  verloopt na 12 uur). De tool weigert te starten als `SECRET_KEY` ontbreekt of te kort is.
- **Formulieren vanaf andere websites** (CSRF) worden geweigerd.
- **Persoonlijke links** voor indieners bevatten een willekeurige code van 32 tekens, die niet te raden is,
  en lekken niet via de Referer naar andere sites.
- **Bijlagen**: alleen pdf en foto's, met een maximale grootte; ze worden onder een willekeurige naam
  opgeslagen en de browser mag ze niet als webpagina uitvoeren (`nosniff`, Content-Security-Policy).
- **Pagina's** worden geëscaped (geen ingevoegde scripts) en mogen niet op andere sites ingebed worden.
- **Uploadformulier** heeft een limiet per IP-adres en een onzichtbaar veld tegen spambots.
- **De app draait niet als root** in de container en heeft geen toegang tot Docker. De knop Bijwerken
  legt alleen een verzoek neer voor een aparte updater op de server (zie [bijwerken.md](bijwerken.md)).
- **Updates**: Dependabot stelt een pull request voor zodra er een beveiligingsupdate van een pakket is.

## De server dichtzetten

Het installatiescript zet al een firewall (ufw), automatische beveiligingsupdates en fail2ban aan.
Het belangrijkste dat je zelf nog moet doen: **inloggen met een SSH-sleutel in plaats van een wachtwoord.**
Een server met root-login op wachtwoord krijgt binnen een paar minuten de eerste raadpogingen.

### 1. Maak een SSH-sleutel op je eigen computer

Op Mac, Linux of Windows (PowerShell):

```sh
ssh-keygen -t ed25519
ssh-copy-id root@zambesidreef.nl
```

Op Windows bestaat `ssh-copy-id` niet; gebruik dan:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@zambesidreef.nl "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Test in een **nieuw** venster dat `ssh root@zambesidreef.nl` werkt zonder wachtwoord te vragen.

### 2. Zet inloggen met wachtwoord uit

Alleen als stap 1 werkt, anders sluit je jezelf buiten. Op de server:

```sh
cat > /etc/ssh/sshd_config.d/10-alleen-sleutel.conf <<'EOF2'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF2
sshd -t && systemctl reload ssh
```

Test opnieuw in een nieuw venster voordat je het oude sluit. Kom je er toch niet meer in,
dan kun je via de console in het Netcup-klantpaneel (SCP) inloggen en het bestand weer verwijderen.

### 3. Controleren

```sh
ufw status                       # alleen 22, 80 en 443 open
fail2ban-client status sshd      # aantal geblokkeerde IP-adressen
docker compose ps                # in /opt/declaratietool: db en app zonder publieke poort
```

## Bijhouden

- Bijwerken naar de nieuwste versie (ook voor beveiligingsupdates van de tool):
  de knop **Bijwerken** in het portaal, of `sudo /opt/declaratietool/deploy/updater.sh update`
- Gebruik voor de accounts in de tool lange wachtwoorden (minstens 10 tekens, liever een zin).
- Maak een back-up van de database en bijlagen, zodat je bij een probleem terug kunt.
  Zie [installatie.md](installatie.md).
