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

## Inkomende mail (IMAP)

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `IMAP_HOST` | | IMAP-server. Leeg = geen mail ophalen |
| `IMAP_PORT` | 993 | Poort (SSL) |
| `IMAP_USER` / `IMAP_PASSWORD` | | Inloggegevens van de declaratie-mailbox |
| `IMAP_FOLDER` | INBOX | Map waarin gekeken wordt |
| `IMAP_POLL_SECONDS` | 60 | Hoe vaak er gekeken wordt |

Elke **ongelezen** mail in de map wordt verwerkt en daarna als gelezen gemarkeerd. Foto's (jpg, png, heic, webp) en pdf's worden bijlagen; kleine plaatjes in de tekst (logo's in handtekeningen) worden overgeslagen. Automatische antwoorden (afwezigheidsmeldingen) worden genegeerd.

Gebruik je een mailprovider zonder IMAP (zoals Proton Mail), laat `IMAP_HOST` dan leeg. Indieners uploaden hun bon dan via `https://<jouw-domein>/indienen`; de rest werkt hetzelfde.

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
