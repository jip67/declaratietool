# Beveiliging

## Wat de tool zelf doet

- **Versleutelde verbinding.** Caddy haalt automatisch een https-certificaat op en dwingt https af (HSTS).
- **Alleen het nodige staat open.** De database is niet van buitenaf bereikbaar en de app luistert alleen
  op de server zelf (`127.0.0.1:8000`); alleen Caddy (poort 80 en 443) is publiek.
- **Wachtwoorden** worden opgeslagen als scrypt-hash, nooit leesbaar.
- **Wachtwoorden raden** wordt afgeremd: na 5 foute pogingen op één account, of 20 vanaf één IP-adres,
  moet je 15 minuten wachten.
- **Tweestapsverificatie (2FA)** kan iedereen zelf aanzetten onder de eigen naam (rechtsboven). Na het
  wachtwoord vul je dan ook een code in, uit een authenticator-app (Google Authenticator, Microsoft
  Authenticator, Bitwarden, 1Password, Aegis, …) of uit een mail die de tool stuurt. De app is het veiligst;
  de mailcode is zo veilig als je mailbox. Bij het aanzetten krijg je 10 herstelcodes die elk één keer werken.
  Mislukte codes tellen mee voor de blokkering hierboven en staan in het logboek. Is iemand telefoon én
  herstelcodes kwijt, dan zet een beheerder het via Gebruikers → Bewerken weer uit. Zie [gebruik.md](gebruik.md#tweestapsverificatie).
- **Logboek**: bestuursleden en beheerders zien onder Instellingen → Logboek elke geslaagde en mislukte inlogpoging met tijd, IP-adres en
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
ssh-copy-id root@<jouw-domein>
```

Gebruik je PuTTY, maak de sleutel dan met PuTTYgen (type Ed25519, met passphrase) en zet de regel
`ssh-ed25519 AAAA...` uit PuTTYgen in `/root/.ssh/authorized_keys` op de server; zie
[beheer.md](beheer.md#5-inloggen-op-de-server).

Op Windows bestaat `ssh-copy-id` niet; gebruik dan:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@<jouw-domein> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Test in een **nieuw** venster dat `ssh root@<jouw-domein>` werkt zonder wachtwoord te vragen.

### 2. Zet inloggen met wachtwoord uit

Alleen als stap 1 werkt, anders sluit je jezelf buiten. Op de server:

```sh
cat > /etc/ssh/sshd_config.d/00-alleen-sleutels.conf <<'EOF2'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF2
sshd -t && systemctl reload ssh
```

De `00` in de naam zorgt dat dit bestand voorgaat op instellingen die de aanbieder al heeft neergezet.
Test opnieuw in een nieuw venster voordat je het oude sluit. Kom je er toch niet meer in,
dan kun je via de console in het klantpaneel van je VPS-aanbieder inloggen en het bestand weer verwijderen.

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
- Zet de nachtelijke, versleutelde back-up naar Google Drive aan en bewaar de sleutel buiten de server.
  Zie [backup.md](backup.md).
