# Configuratie

Alle instellingen staan in `.env` (zie `.env.example`). Na een wijziging: `docker compose up -d`.

## Algemeen

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `APP_NAME` | Declaratietool | Naam in de kop en als afzendernaam van mails |
| `ORGANISATION_NAME` | Mijn vereniging | Naam van je vereniging, onder mails |
| `DOMAIN` | | Domein voor Caddy, zonder `https://` |
| `BASE_URL` | http://localhost:8000 | Volledig adres van de tool; wordt gebruikt in links in mails |
| `SECRET_KEY` | | Geheime sleutel voor inlogsessies (`openssl rand -hex 32`) |
| `DEFAULT_LANGUAGE` | nl | Standaardtaal (`nl` of `en`). Iedereen ziet eerst deze taal, ongeacht de browsertaal; bezoekers wisselen met NL/EN rechtsboven, medewerkers onder hun account. |
| `TIMEZONE` | Europe/Amsterdam | Tijdzone voor datums en herinneringen |
| `REFERENCE_PREFIX` | D | Voorvoegsel van het kenmerk (`D2026-0001`) |
| `MAX_UPLOAD_MB` | 15 | Maximale grootte per bijlage |

## Database

| Instelling | Betekenis |
| --- | --- |
| `POSTGRES_PASSWORD` | Wachtwoord van de database (alleen intern gebruikt) |

## Mailinstellingen in het portaal

De mailinstellingen (SMTP en IMAP) kun je ook in de tool zelf invullen: log in als beheerder en kies **Mailinstellingen**. Dan hoef je `.env` niet aan te passen.

- Wat je in het portaal opslaat gaat vóór de waarden in `.env`; `.env` blijft de terugval. Achter elk veld staat waar de huidige waarde vandaan komt.
- Wijzigingen gelden meteen, ook voor het ophalen van mail. Een herstart is niet nodig.
- Wachtwoorden worden versleuteld in de database bewaard (met een sleutel afgeleid van `SECRET_KEY`) en nooit in de pagina getoond. Laat je het wachtwoordveld leeg, dan blijft het opgeslagen wachtwoord staan.
- Met **Test SMTP-verbinding** en **Test IMAP-verbinding** probeer je de ingevulde gegevens uit voordat je ze opslaat. De SMTP-test verbindt en logt in zonder een mail te versturen; de IMAP-test logt in, opent de map en telt de ongelezen mails.
- Met **Terug naar de instellingen uit .env** wis je alles wat in het portaal is opgeslagen.

Verander je `SECRET_KEY`, dan kunnen opgeslagen wachtwoorden niet meer worden gelezen. De tool valt dan terug op het wachtwoord uit `.env`; vul het wachtwoord opnieuw in via Mailinstellingen.

De tabellen hieronder beschrijven de waarden in `.env`. `IMAP_POLL_SECONDS` stel je alleen in `.env` in.

## Inkomende mail (IMAP)

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `IMAP_HOST` | | IMAP-server. Leeg = geen mail ophalen |
| `IMAP_PORT` | 993 | Poort (SSL) |
| `IMAP_USER` / `IMAP_PASSWORD` | | Inloggegevens van de declaratie-mailbox |
| `IMAP_FOLDER` | INBOX | Map waarin gekeken wordt |
| `IMAP_POLL_SECONDS` | 60 | Hoe vaak er gekeken wordt |

Elke **ongelezen** mail in de map wordt verwerkt en daarna als gelezen gemarkeerd. Foto's (jpg, png, heic, webp) en pdf's worden bijlagen; kleine plaatjes in de tekst (logo's in handtekeningen) worden overgeslagen. Automatische antwoorden (afwezigheidsmeldingen) worden genegeerd.

Gebruik je een mailprovider zonder IMAP (zoals Proton Mail), laat `IMAP_HOST` dan leeg. Declaraties kunnen dan alleen via het portaal worden ingediend, door gebruikers met een account of door een medewerker namens iemand.

## Uitgaande mail (SMTP)

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `SMTP_HOST` | | SMTP-server. Leeg = mails alleen loggen (handig om te testen) |
| `SMTP_PORT` | 587 | Poort |
| `SMTP_STARTTLS` | true | STARTTLS gebruiken (poort 587) |
| `SMTP_SSL` | false | Direct SSL (poort 465); zet dan `SMTP_STARTTLS=false` |
| `SMTP_USER` / `SMTP_PASSWORD` | | Inloggegevens |
| `MAIL_FROM` | | Afzenderadres; meestal hetzelfde als de declaratie-mailbox |

Voorbeeld voor Proton Mail (met een SMTP-token uit de Proton-instellingen): `SMTP_HOST=smtp.protonmail.ch`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_SSL=false`, `SMTP_USER` en `MAIL_FROM` het adres, `SMTP_PASSWORD` het token.

## Herinneringen

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `REMINDER_HOUR` | 9 | Vanaf dit uur (lokale tijd) gaat één keer per dag de herinneringsronde |
| `SUBMITTER_REMINDER_DAYS` | 14 | Hoe lang indieners herinnerd worden om hun gegevens aan te vullen |

Medewerkers krijgen één mail met al hun openstaande taken. Wie een taak minder dan 12 uur geleden kreeg, wordt die dag nog niet herinnerd.
