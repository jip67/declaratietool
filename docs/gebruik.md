# Gebruik

## Indiener

1. Mail een foto of pdf van de bon naar het declaratie-adres. Heb je een account met de rol **Gebruiker**, dan kun je ook inloggen en de bon toevoegen via **Nieuwe declaratie**. Meerdere bonnen in één mail worden één declaratie. Het onderwerp van de mail wordt alvast als omschrijving ingevuld.
2. Je krijgt een bevestiging met een persoonlijke link.
3. Vul via die link het bedrag, de omschrijving, je IBAN en de tenaamstelling in. Vink "onthouden" aan, dan staan je rekeninggegevens er de volgende keer al.
4. Je krijgt een mail bij elke stap: goedgekeurd, betaling klaargezet, betaald (of afgewezen, met reden). Via dezelfde link kun je altijd de status bekijken.

Tot de voorzitter heeft goedgekeurd kun je je gegevens nog aanpassen.

## Voorzitter

1. Je krijgt een mail als er een declaratie klaarstaat.
2. Log in, open de declaratie (of kijk onder **Mijn taken**) en bekijk de bon.
3. Klik op **Goedkeuren en paraferen**. Elke bon krijgt een stempel met je naam, datum en kenmerk; de geparafeerde versie staat als pdf bij de declaratie.
4. Klopt er iets niet? Gebruik **Afwijzen** en geef een reden; de indiener krijgt die te zien.

### Goedkeuren via een link in de mail

Voor een voorzitter die liever niet inlogt kan de beheerder **goedkeuren via een link** aanzetten
(Instellingen → Gebruikers → Bewerken → *Mag goedkeuren via een link in de e-mail*). De mail over een
nieuwe declaratie en de dagelijkse herinnering bevatten dan een extra link. Die opent een pagina met de
gegevens en de bonnen en één grote knop **Goedkeuren en paraferen**. De paraaf is dezelfde als in het portaal.

- Openen alleen keurt niets goed; pas de knop doet dat. Zo kan een virusscanner die links in mail opent
  niet per ongeluk goedkeuren.
- Een link hoort bij één declaratie en één voorzitter, werkt één keer en verloopt na
  `APPROVAL_LINK_DAYS` dagen (standaard 7). De herinnering van de volgende ochtend heeft weer een verse link.
- Is de declaratie al goedgekeurd, afgewezen of ongedaan gemaakt, of staat de instelling uit, dan werkt
  een oude link niet meer.
- Veranderen bedrag, rekening of bonnen terwijl de pagina openstaat, dan vraagt de pagina om opnieuw te kijken.
- In de geschiedenis staat *Goedgekeurd en geparafeerd · naam (via link in e-mail)*.
- Afwijzen of een opmerking plaatsen gaat niet via de link; daarvoor log je in.

Het risico: wie de mail van de voorzitter kan lezen, kan ook goedkeuren, zonder wachtwoord of
tweestapsverificatie. Daarom staat het standaard uit en kan het alleen voor iemand met de rol Voorzitter.
Boekhouder en secretaris controleren de declaratie daarna nog, en de tool betaalt zelf niets uit.

## Boekhouder

1. Na goedkeuring krijg je een mail met alle gegevens (bedrag, IBAN, tenaamstelling, omschrijving, kenmerk) en de geparafeerde bonnen als bijlage.
2. Zet de betaling klaar bij de bank. Gebruik het kenmerk in de omschrijving van de betaling.
3. Klik in het portaal op **Betaling is klaargezet**.

## Secretaris

1. Je krijgt een mail zodra de boekhouder de betaling heeft klaargezet.
2. Voer de betaling uit bij de bank.
3. Klik in het portaal op **Betaling is uitgevoerd**. De declaratie staat dan op betaald en iedereen, ook de indiener, weet dat er betaald is.

## Declaratie aanmaken namens iemand

Alle medewerkers kunnen via **Nieuwe declaratie** zelf een declaratie invoeren, bijvoorbeeld voor iemand die geen mail gebruikt of een bon op papier inleverde:

- Vul het e-mailadres van de indiener in en voeg de bon(nen) toe.
- Vul je ook bedrag, omschrijving, IBAN en tenaamstelling in, dan gaat de declaratie direct naar de voorzitter.
- Laat je die leeg, dan krijgt de indiener een mail met de link om ze zelf aan te vullen.

## Interne opmerkingen

Onderaan elke declaratie staat het blok **Interne opmerkingen**, met het label *intern, niet zichtbaar voor indiener*. Voorzitter, boekhouder, secretaris en beheerder kunnen daar extra informatie kwijt, bijvoorbeeld "bon nagevraagd bij de penningmeester". Elke opmerking krijgt naam en tijdstip. De indiener ziet ze nooit: niet op de pagina van de persoonlijke link, niet in mails en ook niet als hij inlogt met de rol Gebruiker.

## Stap ongedaan maken

Per ongeluk goedgekeurd, klaargezet, uitgevoerd of afgewezen? Open de declaratie en kies **Laatste stap ongedaan maken**. De declaratie gaat terug naar de vorige status; bij een teruggedraaide goedkeuring verdwijnt ook de paraaf op de bonnen. Dit kan degene die de stap zette, en een beheerder. De indiener krijgt een statusupdate, wie weer aan zet is krijgt een bericht, en in de geschiedenis staat "Stap ongedaan gemaakt". Je kunt zo ook meerdere stappen achter elkaar terugdraaien.

## Declaratie bewerken of wissen (beheerder)

Een beheerder ziet bij elke declaratie de knop **Declaratie bewerken**. Daarmee pas je naam en e-mailadres van de indiener, bedrag, omschrijving, IBAN en tenaamstelling aan, ook als de declaratie al is goedgekeurd of betaald. De status verandert niet en de indiener krijgt geen mail; in de geschiedenis staat "Gegevens aangepast door beheerder", met welke velden zijn gewijzigd.

Een typefout in het e-mailadres herstel je hier ook. De declaratie wordt dan gekoppeld aan het nieuwe adres; hangen aan het foute adres geen andere declaraties, dan wordt het vergeten. Laat het vinkje aan om de indiener op het nieuwe adres de link en de huidige stand te sturen, want eerdere mails gingen naar het verkeerde adres.

Onder elke bijlage staat **Bijlage vervangen**. Daarmee zet je een nieuwe versie in de plaats van de bon of factuur, bijvoorbeeld een met de hand getekende factuur van de voorzitter. Het oude bestand wordt verwijderd. Was de declaratie al goedgekeurd, dan krijgt het nieuwe bestand dezelfde paraaf (naam van de voorzitter en tijdstip van de goedkeuring), zodat de boekhouder en secretaris de geparafeerde versie blijven zien. In de geschiedenis staat "Bijlage vervangen door beheerder" met de oude en de nieuwe bestandsnaam.

Onderaan de declaratie staat **Declaratie wissen**. Na het aanvinken van de bevestiging wordt de declaratie definitief verwijderd, met de bijlagen (ook de geparafeerde versies) op schijf, de geschiedenis en de interne opmerkingen. Handig om testdata op te ruimen; het kan niet ongedaan worden gemaakt.

## Eenvoudige weergave

Voor wie niet veel met computers doet is er een **eenvoudige weergave**, voor voorzitter, boekhouder en secretaris. Na het inloggen staat dan alleen wat op die persoon wacht, als grote kaarten met bedrag, omschrijving en een knop als **Bekijken en goedkeuren**. Na het goedkeuren (of klaarzetten, of betaling uitvoeren) kom je meteen terug op de takenlijst, met de melding dat het gelukt is. Instellingen en Nieuwe declaratie staan niet in het menu; via **Alle declaraties bekijken** blijft de volledige lijst bereikbaar.

Iedereen zet dit zelf aan of uit onder zijn naam (**Eenvoudige weergave**). De beheerder kan het ook per persoon aanzetten onder **Instellingen → Gebruikers → Bewerken**.

## Meekijken als een andere gebruiker (beheerder)

Onder **Instellingen → Gebruikers** staat bij elke actieve gebruiker de knop **Meekijken**. Je ziet het portaal dan precies zoals die persoon het ziet: dezelfde declaraties, dezelfde taken en dezelfde knoppen. Zo kun je bijvoorbeeld de voorzitter aan de telefoon uitleggen waar hij moet klikken, of controleren wat een lid met de rol Gebruiker ziet.

Meekijken is alleen-lezen. Een gele balk bovenaan laat zien met wie je meekijkt; knoppen zijn grijs en de server weigert elke wijziging (goedkeuren, opmerkingen, instellingen, account). Met **Stoppen met meekijken** ben je weer jezelf. Elke keer dat je gaat meekijken komt in het logboek onder **Inlogs** ("Meegekeken als ...").

Indieners zonder account hebben geen portaal; hun eigen pagina open je via de link bij de declaratie.

## Herinneringen

Elke ochtend (instelbaar) krijgt iedereen met openstaande taken één mail met een overzicht. Bestuursleden die het aanzetten krijgen in dezelfde ronde ook een melding van taken die te lang openstaan (zie [Beheer](#beheer)). Indieners die hun gegevens nog niet hebben ingevuld krijgen ook een herinnering, standaard maximaal 14 dagen lang.

## Beheer

Rechtsboven staat het menu **Instellingen**. Wat je daarin ziet hangt af van je rol:

| Rol | Gebruikers | Logboek | Mailinstellingen | Meldingen | Updates |
| --- | --- | --- | --- | --- | --- |
| Gebruiker | – | – | – | – | – |
| Voorzitter, boekhouder, secretaris | bekijken | ja | – | eigen | – |
| Beheerder | bekijken en wijzigen | ja | ja | eigen + beheer | ja |

De rol Beheerder geeft geen rechten in de declaratiestappen. Goedkeuren kan alleen de voorzitter, de betaling klaarzetten alleen de boekhouder en de betaling uitvoeren alleen de secretaris. Heeft iemand meerdere rollen, dan mag hij de stappen van al die rollen zetten.

Gebruikers met de rol **Beheerder** voegen op de pagina **Gebruikers** mensen toe. Met **Bewerken** pas je naam, e-mailadres, taal en rollen aan, zet je een account uit of stel je een nieuw wachtwoord in. Onderaan die pagina kun je een gebruiker **verwijderen**. Komt iemand al voor in de geschiedenis van een declaratie (bijvoorbeeld omdat hij iets heeft goedgekeurd), dan wordt het account niet gewist maar uitgeschakeld en geanonimiseerd, zodat het logboek blijft kloppen. Je eigen account kun je niet verwijderen of uitzetten, en je houdt altijd de rol Beheerder. Geef leden die zelf declaraties willen indienen de rol **Gebruiker**: zij kunnen inloggen, een declaratie aanmaken en alleen hun eigen declaraties en de status daarvan zien. Iedereen kan onder zijn eigen naam (rechtsboven) zijn taal en wachtwoord wijzigen.

Onder **Logboek** (voor bestuursleden en beheerders) staan drie tabbladen:

- **Inlogs**: wie wanneer heeft ingelogd, vanaf welk IP-adres en met welke browser.
- **Mislukte inlogpogingen**: met de reden (onbekend e-mailadres, verkeerd wachtwoord, account staat uit of tijdelijk geblokkeerd na te veel pogingen). Veel pogingen vanaf één onbekend IP-adres wijzen op iemand die wachtwoorden probeert te raden.
- **Binnengekomen mail**: afzender, onderwerp, aantal bijlagen en wat de tool ermee deed (declaratie aangemaakt, geweigerd omdat er geen bijlage was, genegeerd als automatisch bericht, of mislukt).

Je kunt zoeken op e-mailadres, IP-adres, afzender of onderwerp. Regels ouder dan `LOG_RETENTION_DAYS` (standaard 90 dagen) worden automatisch verwijderd.

Bij een bestuurswissel: maak een account voor de nieuwe bestuurder met de juiste rol en zet het oude account uit. De geschiedenis van eerdere declaraties blijft bewaard.

Beheerders vinden onder **Instellingen → Mailinstellingen** de gegevens van de mailbox (SMTP voor versturen, IMAP voor ophalen). Daar pas je ze aan zonder `.env` te wijzigen en test je de verbinding met één klik; zie [Configuratie](configuratie.md#mailinstellingen-in-het-portaal).

Onder **Instellingen → Meldingen** kiest elk bestuurslid (voorzitter, boekhouder, secretaris en beheerder) zelf bij welke gebeurtenissen hij een e-mail wil krijgen. Het is een persoonlijke instelling: wat jij aanzet geldt alleen voor jou. Standaard staat alles uit. Wie de eenvoudige weergave gebruikt vindt de pagina via de link op de eigen accountpagina (onder je naam).

- **Nieuwe declaratie**: zodra er een declaratie binnenkomt, per mail of via het portaal, met indiener, bedrag en een link. Maak je zelf een declaratie aan, dan krijg je geen mail.
- **Statuswijzigingen**: bij elke stap (gegevens ingevuld, goedgekeurd, betaling klaargezet, betaald, afgewezen, stap ongedaan gemaakt), met wie de stap zette. Je krijgt geen melding van stappen die je zelf zet, en ook niet als de declaratie daarna op jou wacht: dan krijg je al de gewone mail met je taak.
- **Taak staat te lang open**: zodra een declaratie langer dan het gekozen aantal dagen (standaard 3, in te stellen van 1 tot 365) in dezelfde stap staat, ook als iemand anders aan zet is of de indiener zijn gegevens nog moet invullen. Je krijgt per taak maar één melding; gaat de declaratie naar de volgende stap, dan telt die als nieuwe taak. De melding gaat mee met de dagelijkse herinneringsronde, in één mail per persoon.

Beheerders zien daaronder nog drie meldingen:

- **Iemand logt in**: bij elke geslaagde login, met gebruiker, tijdstip, IP-adres en browser.
- **Tijdelijke inlogblokkering**: één mail zodra een e-mailadres of IP-adres na te veel mislukte pogingen 15 minuten wordt geblokkeerd.
- **Binnengekomen e-mail**: bij elk bericht in de declaratiemailbox, met afzender, onderwerp en wat de tool ermee deed. Automatische berichten zoals afwezigheidsmeldingen tellen niet mee.

Iedereen krijgt de meldingen in de eigen taal. Stonden de beheermeldingen al aan voor de update naar deze versie, dan staan ze daarna aan voor elke beheerder.

## Tweestapsverificatie

Iedereen met een account kan onder de eigen naam (rechtsboven) **tweestapsverificatie** aanzetten. Na het wachtwoord vraagt de tool dan om een code van 6 cijfers. Je kiest zelf hoe je die krijgt:

- **Authenticator-app** (aanbevolen): kies *Instellen met app*, scan de QR-code met bijvoorbeeld Google Authenticator, Microsoft Authenticator of Bitwarden (of typ de sleutel over) en vul ter controle de code in die de app toont.
- **Code per e-mail**: kies *Instellen met e-mail*. De tool stuurt een code naar je e-mailadres; vul die in om het aan te zetten. Bij elke login krijg je een nieuwe code, die 10 minuten geldig is. Met *Stuur een nieuwe code* vraag je (hooguit één keer per minuut) een nieuwe aan.

Daarna krijg je **10 herstelcodes**. Bewaar ze goed, bijvoorbeeld in je wachtwoordmanager: zonder telefoon of mail log je daarmee toch in, en elke code werkt één keer. Op de accountpagina zie je hoeveel er nog over zijn en maak je nieuwe aan. Uitzetten kan daar ook, met je wachtwoord.

Een beheerder ziet op de pagina **Gebruikers** wie 2FA gebruikt (App of E-mail). Is iemand zowel de telefoon als de herstelcodes kwijt, dan zet de beheerder het via **Bewerken → Tweestapsverificatie resetten** uit; die persoon logt daarna in met alleen het wachtwoord en kan het opnieuw instellen.

## Als app op je telefoon

De tool is een web-app (PWA): je kunt hem op Android en iPhone op het beginscherm zetten, zonder app-winkel. Hij opent dan schermvullend en werkt verder precies als de website; een update op de server is meteen in de app te zien.

- **Android (Chrome):** menu (⋮) → **App installeren** of **Toevoegen aan startscherm**.
- **iPhone/iPad (Safari):** deelknop → **Zet op beginscherm**.

**Teller op het icoon.** Wacht er een taak op je, dan staat het aantal op het app-icoon. Dat werkt op iPhone/iPad (iOS 16.4 of nieuwer; zet het één keer aan via **Mijn account → Teller op app-icoon aanzetten**, iOS vraagt dan om meldingen toe te staan) en op Windows/macOS. De teller wordt bijgewerkt zodra je de app opent of er weer naartoe gaat; een teller die verandert terwijl de app dicht is, of een teller op Android, kan alleen met pushmeldingen.

De app bewaart geen declaraties of bankgegevens op de telefoon; zonder internet toont hij alleen een melding dat er geen verbinding is. Op de iPhone log je in de app apart in, los van Safari. Installeren werkt alleen via https, dus op de echte server (niet op `http://localhost`, behalve in Chrome op dezelfde computer).

## Hulp

Via **Help** rechtsboven staat deze uitleg ook in de tool zelf, in het Nederlands en Engels. Ingelogde medewerkers zien de onderdelen voor hun eigen rol gemarkeerd.

## Bijlagen bekijken

Bonnen en facturen staan direct op de pagina van de declaratie: foto's als afbeelding, pdf's in een ingebouwde viewer. Na goedkeuring zie je in het portaal de geparafeerde versie. HEIC-foto's (iPhone) kunnen de meeste browsers niet op de pagina tonen; open die via de link.
