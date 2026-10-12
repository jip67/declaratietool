# Back-up naar Google Drive

Elke nacht maakt de server een back-up van alles wat nodig is om de tool terug te zetten:

- de database (declaraties, gebruikers, geschiedenis, logboek, mailinstellingen);
- alle bijlagen (bonnen en geparafeerde pdf's);
- de `.env` met de instellingen van de server.

De back-up wordt **op de server versleuteld** (gpg, AES-256) en pas daarna naar Google Drive
gestuurd. Google, of iemand die het Google-account binnenkomt, ziet alleen onleesbare bestanden.

De server krijgt alleen toegang tot de bestanden die hij zelf op de Drive zet (Google noemt dit
`drive.file`), niet tot de rest van de Drive. Back-ups staan in de map `declaratietool-backup`,
op de server blijven de laatste 7 dagen staan en op Google Drive de laatste 90 dagen.

## Wat je nodig hebt

- Een Google-account voor de back-up. Gebruik bij voorkeur een account dat bij de rol hoort
  (bijvoorbeeld het Gmail-account van de boekhouder), zodat een opvolger het kan overnemen.
  **Zet tweestapsverificatie aan op dat account.**
- Je eigen computer met een webbrowser, om Google Drive één keer te koppelen.
- Een plek om de back-upsleutel te bewaren: een wachtwoordmanager, of op papier in de kluis.

## Instellen (eenmalig)

Log in op de server en draai:

```sh
sudo /opt/declaratietool/deploy/backup.sh setup
```

Het script:

1. installeert `rclone` (praat met Google Drive) en `gpg` (versleutelt);
2. maakt een **sleutel** en toont die één keer. **Bewaar hem meteen buiten de server.** Zonder
   deze sleutel is een back-up niet terug te zetten, ook niet door ons. Op de server staat hij in
   `/etc/declaratietool/backup.key`;
3. vraagt je Google Drive te koppelen. Daarvoor installeer je rclone op je eigen computer
   ([downloads](https://rclone.org/downloads/); Mac: `brew install rclone`) en typ je daar de
   opdracht die het script laat zien:

   ```sh
   rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlLmZpbGUifQ"
   ```

   Er opent een browser; log in met het back-upaccount en geef toestemming. rclone toont daarna
   een regel tussen `Paste the following` en `End paste`. Plak die in het venster van de server;
4. zet de nachtelijke back-up aan (rond 03:30, een gemiste back-up wordt ingehaald na opstarten);
5. maakt meteen de eerste back-up.

Je kunt het script veilig opnieuw draaien; een bestaande sleutel en koppeling blijven staan.

## Controleren

In het portaal staat onder **Instellingen → Bijwerken** wanneer de laatste back-up is gelukt.
Mislukt de back-up, of is er meer dan anderhalve dag geen back-up gemaakt, dan ziet een beheerder
een waarschuwing op het overzicht.

Op de server:

```sh
sudo /opt/declaratietool/deploy/backup.sh list     # back-ups op Google Drive en op de server
sudo /opt/declaratietool/deploy/backup.sh          # nu een back-up maken
journalctl -u declaratietool-backup -n 50          # wat er de laatste keer gebeurde
systemctl list-timers declaratietool-backup        # wanneer de volgende back-up is
```

## Terugzetten

**Dit vervangt alle huidige gegevens** door die uit de back-up. Het script vraagt eerst om
bevestiging.

```sh
sudo /opt/declaratietool/deploy/backup.sh list
sudo /opt/declaratietool/deploy/backup.sh restore declaratietool-2026-10-12_0330.tar.gz.gpg
```

Het script haalt het bestand zo nodig van Google Drive, zet de tool stil, zet database en bijlagen
terug en start de tool weer.

### Op een nieuwe server

1. Installeer de tool met `deploy/install-vps.sh` (zie [ovh-vps.md](ovh-vps.md)).
2. Zet de bewaarde sleutel terug:
   ```sh
   sudo mkdir -p /etc/declaratietool
   sudo sh -c 'printf "%s" "JOUW-SLEUTEL" > /etc/declaratietool/backup.key && chmod 600 /etc/declaratietool/backup.key'
   ```
3. Draai `sudo /opt/declaratietool/deploy/backup.sh setup` om Google Drive opnieuw te koppelen
   (de sleutel blijft staan). Dit maakt ook een back-up van de lege nieuwe installatie; dat is
   niet erg.
4. Zet de gewenste back-up terug met `restore`, zoals hierboven.

Het script neemt de `SECRET_KEY` uit de back-up over, zodat opgeslagen mailwachtwoorden blijven
werken. De volledige oude `.env` staat daarna ter vergelijking in `/etc/declaratietool/env-uit-backup`.

### Met de hand openen

Een back-up is een gewoon versleuteld bestand. Op elke computer met gpg
([Gpg4win](https://gpg4win.org) op Windows) open je hem zo:

```sh
gpg -d declaratietool-2026-10-12_0330.tar.gz.gpg > backup.tar.gz   # vraagt om de sleutel
tar xzf backup.tar.gz    # database.sql, uploads.tar.gz, env, versie.txt
```

## Extra zekerheid

Netcup biedt snapshots van de hele server. Die zijn handig om na een mislukte update snel terug te
gaan, maar staan bij dezelfde partij als de server. De versleutelde back-up op Google Drive is je
kopie buiten de deur. Probeer af en toe (bijvoorbeeld eens per jaar) of terugzetten werkt.
