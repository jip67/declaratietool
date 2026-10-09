# Installeren op een VPS bij OVH

Deze handleiding gaat van niets naar een werkende declaratietool op je eigen domein, met een VPS, domeinnaam en mailbox bij OVH. Andere aanbieders werken op dezelfde manier; alleen de menu's heten anders.

Reken op ongeveer een uur, waarvan het meeste wachten is (op de VPS en op DNS).

## 1. VPS bestellen

1. Ga in het OVHcloud-klantpaneel naar **Bare Metal Cloud → Virtual Private Servers** en bestel een VPS.
2. Het kleinste pakket is ruim voldoende (de tool gebruikt minder dan 1 GB geheugen).
3. Kies een datacenter in Europa, bijvoorbeeld Gravelines of Frankfurt.
4. Kies als besturingssysteem **Ubuntu 24.04** (zonder extra applicaties).
5. Voeg bij voorkeur je **SSH-sleutel** toe. Heb je die niet, dan krijg je een wachtwoord per mail.

Na het bestellen krijg je een mail met het **IP-adres** van je VPS en de gebruikersnaam (bij Ubuntu is dat `ubuntu`).

## 2. Domeinnaam registreren

1. Ga naar **Web Cloud → Domeinnamen → Domeinnaam bestellen** en registreer je domein, bijvoorbeeld `mijnvereniging.nl`.
2. Kies of de tool op het hoofddomein komt of op een subdomein. Een subdomein zoals `declaraties.mijnvereniging.nl` laat ruimte voor een website op het hoofddomein. Deze handleiding gaat daarvan uit.

## 3. DNS naar je VPS laten wijzen

1. Ga naar **Web Cloud → Domeinnamen → (je domein) → DNS-zone**.
2. Klik op **Record toevoegen → A**:
   - Subdomein: `declaraties`
   - Doel: het IPv4-adres van je VPS
3. Heeft je VPS ook een IPv6-adres, voeg dan op dezelfde manier een **AAAA**-record toe.
4. Wil je de tool op het hoofddomein, pas dan het bestaande A-record voor het lege subdomein (en `www`) aan; OVH laat die standaard naar een parkeerpagina wijzen.

Een wijziging is meestal binnen een kwartier actief, soms een paar uur. Controleer op je eigen computer:

```bash
ping declaraties.mijnvereniging.nl
```

Je moet het IP-adres van je VPS terugzien voordat je verdergaat; anders kan er geen https-certificaat worden aangevraagd.

## 4. Mailbox voor de declaraties

1. Ga naar **Web Cloud → E-mails** (bij een nieuw domein zit vaak een kleine gratis mailbox inbegrepen; anders bestel je het kleinste e-mailpakket).
2. Maak een account aan, bijvoorbeeld `declaraties@mijnvereniging.nl`, met een sterk wachtwoord.
3. Noteer de servergegevens. Bij de standaard OVH-mail (MX Plan) zijn dat:
   - IMAP: `ssl0.ovh.net`, poort 993 (SSL)
   - SMTP: `ssl0.ovh.net`, poort 465 (SSL)

   Heb je een ander OVH-mailpakket (bijvoorbeeld Zimbra of Exchange), dan staan de juiste servers bij dat pakket in het klantpaneel.

Gebruik deze mailbox alleen voor de tool: alles wat ongelezen binnenkomt wordt als declaratie verwerkt.

## 5. Inloggen op de VPS

Op je eigen computer (Terminal op Mac/Linux, PowerShell op Windows):

```bash
ssh ubuntu@<ip-adres-van-je-vps>
```

## 6. Installatiescript draaien

Op de VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/jip67/declaratietool/main/deploy/install-vps.sh -o install-vps.sh
sudo bash install-vps.sh
```

Het script:

- werkt de server bij en zet automatische beveiligingsupdates aan;
- zet de firewall aan, met alleen SSH, http en https open;
- installeert Docker;
- haalt de code op naar `/opt/declaratietool`;
- vraagt je domein, de naam van je vereniging en de mailgegevens, en maakt zelf veilige wachtwoorden voor de database en de inlogsessies;
- start alles, vraagt automatisch een https-certificaat aan en maakt je eerste account aan.

Laat je het mailwachtwoord leeg, dan draait de tool zonder mail. De links voor indieners verschijnen dan in het logboek (`docker compose logs app worker`). Zo kun je eerst rustig testen; zet daarna de mailgegevens in `/opt/declaratietool/.env` en start opnieuw met `docker compose up -d`.

## 7. Testen

1. Open `https://declaraties.mijnvereniging.nl` en log in.
2. Voeg onder **Gebruikers** de voorzitter en de secretaris toe.
3. Mail vanaf je eigen adres een foto van een bon naar het declaratie-adres en loop alle stappen door.

## Bijwerken

Het makkelijkst via **Bijwerken** in het portaal (zie [bijwerken.md](bijwerken.md)). Of op de server:

```bash
cd /opt/declaratietool
git pull
docker compose up -d --build
```

## Back-ups

OVH biedt voor een VPS een optie voor automatische back-ups (snapshots); die is aan te raden. Daarnaast kun je dagelijks een database-dump maken:

```bash
sudo crontab -e
```

en deze regel toevoegen:

```
30 3 * * * cd /opt/declaratietool && docker compose exec -T db pg_dump -U declaratie declaratie | gzip > /root/declaratie-$(date +\%a).sql.gz
```

Dat bewaart steeds de laatste zeven dagen. Zie ook [installatie.md](installatie.md#back-ups) voor het veiligstellen van de bijlagen.

## Problemen

- **Geen https / site niet bereikbaar:** wijst het domein al naar de VPS (`ping`)? Bekijk `docker compose logs caddy`.
- **Geen mail binnen of uit:** bekijk `docker compose logs worker`. Controleer servernaam, poort en wachtwoord in `.env`.
- **Mails komen in de spam:** voeg in de DNS-zone van OVH een SPF-record toe voor je maildomein (OVH doet dit vaak al automatisch voor zijn eigen mail) en zet DKIM aan bij je e-mailpakket.
