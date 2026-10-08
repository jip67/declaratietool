# Stappenplan

Van idee naar een werkende declaratietool op je eigen domein. Stappen met ✅ zijn al gebouwd en staan in deze repository; de rest doe je zelf (eenmalig).

## Fase 1: de basis bouwen ✅

1. ✅ Datamodel: indieners (met onthouden rekeninggegevens), declaraties, bijlagen, gebruikers met rollen en een logboek per declaratie.
2. ✅ Mail ophalen (IMAP): elke minuut nieuwe mail lezen, bijlagen (foto/pdf) opslaan, declaratie aanmaken met een kenmerk zoals `D2026-0001`, bevestiging met persoonlijke link sturen. Mails zonder bijlage krijgen een nette weigering; automatische antwoorden worden genegeerd.
3. ✅ Formulier voor de indiener: bedrag, omschrijving, IBAN (met controle) en tenaamstelling. Rekeninggegevens worden vooraf ingevuld en zijn aan te passen.
4. ✅ Workflow met vaste volgorde: voorzitter → boekhouder → secretaris. Bij elke stap mail naar de indiener en naar wie daarna aan zet is.
5. ✅ Paraaf: bij goedkeuring krijgt elke bon een stempel (GOEDGEKEURD, naam, datum, kenmerk) en wordt hij opgeslagen als pdf. De boekhouder krijgt de geparafeerde pdf's als bijlage.
6. ✅ Portaal met inloggen: overzicht, "mijn taken", details, geschiedenis, afwijzen met reden, declaratie aanmaken namens iemand, gebruikersbeheer.
7. ✅ Dagelijkse herinneringen voor openstaande taken (ook voor indieners die hun gegevens nog niet hebben ingevuld, standaard maximaal 14 dagen).
8. ✅ Meertaligheid: Nederlands en Engels, uit te breiden met één JSON-bestand.
9. ✅ Docker: app, achtergrondproces (mail en herinneringen), PostgreSQL en Caddy (automatisch https).
10. ✅ GitHub Actions: tests bij elke wijziging en een Docker-image in GitHub Packages.

## Fase 2: zelf regelen (eenmalig)

Gebruik je OVH, volg dan [ovh-vps.md](ovh-vps.md): die handleiding en het installatiescript `deploy/install-vps.sh` doen stap 2.2 tot en met 2.5 voor je.

### 2.1 Code op GitHub
1. Maak een (lege) repository aan, bijvoorbeeld `declaratietool`.
2. Zet deze code erin. Bij een publieke repository kunnen anderen de tool ook gebruiken.

### 2.2 Een server
Iets dat altijd aan staat en Docker kan draaien, bijvoorbeeld:
- een kleine VPS (1 vCPU, 1 à 2 GB geheugen is ruim voldoende), of
- een thuisserver of NAS met Docker (dan moeten poort 80 en 443 naar die machine doorgestuurd worden).

Installeer Docker met de officiële instructies op [docs.docker.com](https://docs.docker.com/engine/install/).

### 2.3 Domein registreren
1. Registreer een domein bij een registrar naar keuze (bijvoorbeeld `jouwvereniging-declaraties.nl`), of gebruik een subdomein van een bestaand domein, zoals `declaraties.jouwvereniging.nl`.
2. Maak in het DNS-beheer een **A-record** aan dat naar het IP-adres van je server wijst (en een AAAA-record als je server IPv6 heeft).
3. Wacht tot `ping declaraties.jouwvereniging.nl` het IP-adres van je server geeft. Caddy vraagt daarna zelf een https-certificaat aan.

### 2.4 Mailbox voor declaraties
1. Maak een mailbox aan, bijvoorbeeld `declaraties@jouwvereniging.nl`. Veel registrars leveren mail bij het domein; anders kan het bij elke mailprovider die IMAP en SMTP ondersteunt.
2. Noteer de IMAP- en SMTP-server, poorten, gebruikersnaam en wachtwoord. Gebruik bij Gmail of Microsoft 365 een app-wachtwoord.
3. Gebruik deze mailbox alleen voor de tool: alles wat ongelezen binnenkomt wordt als declaratie verwerkt.

### 2.5 Installeren
Volg [installatie.md](installatie.md): `.env` invullen, `docker compose up -d --build`, eerste gebruiker aanmaken, voorzitter en secretaris toevoegen.

### 2.6 Testen
1. Stuur vanaf je eigen adres een mail met een foto van een bon naar het declaratie-adres.
2. Controleer de bevestiging, vul het formulier in en loop als voorzitter, boekhouder en secretaris de stappen door.
3. Werkt alles? Laat de leden weten naar welk adres ze hun bonnen kunnen sturen.

## Fase 3: later (ideeën)

- Export van betaalde declaraties naar CSV of Excel voor de boekhouding.
- SEPA-betaalbestand (pain.001) maken, zodat de boekhouder meerdere declaraties in één keer kan klaarzetten bij de bank.
- Bedrag en datum automatisch van de bon lezen (OCR).
- Inloggen met een eenmalige link per mail in plaats van een wachtwoord, of tweestapsverificatie.
- Meer talen (Duits, Frans, ...): kopieer `app/locales/en.json` en vertaal.
- Instelbare workflow (bijvoorbeeld een extra goedkeurder boven een bepaald bedrag).
- Automatische back-ups van database en bijlagen.
