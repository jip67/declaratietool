# Bijwerken via het portaal

Een beheerder kan de tool bijwerken met een knop in het portaal, zonder in te loggen op de server.
Onder **Instellingen → Bijwerken** (alleen zichtbaar met de rol Beheerder) zie je:

- welke versie er geïnstalleerd is en welke versie er draait;
- de nieuwste versie op GitHub, met de wijzigingen die erbij komen;
- of de laatste update gelukt is, met het logboek.

**Nu bijwerken** haalt de nieuwste versie van `main` op, bouwt de tool opnieuw en herstart hem. Dat duurt
een paar minuten; de tool is alleen tijdens het herstarten (enkele seconden) niet bereikbaar. De database
wordt daarbij automatisch bijgewerkt. **Nu controleren** kijkt alleen of er een nieuwe versie is; dat doet
de server ook zelf elk uur.

## Hoe het werkt

De app mag Docker bewust niet besturen: wie Docker kan besturen, is in feite baas over de hele server.
Daarom werkt de knop via een kleine, aparte updater die op de server zelf draait:

```
portaal (container)                      server (systemd, als root)
  knop "Nu bijwerken"
  └─> schrijft update/requests/request ──> declaratietool-updater.path ziet het bestand
                                           └─> deploy/updater.sh
                                                 git pull, docker compose build + up -d
  leest update/status/status.json  <────── schrijft status en logboek
```

- De app kan alleen het woord `check` of `update` neerleggen; elke andere inhoud wordt genegeerd.
- Er wordt altijd de versie van `main` op GitHub geïnstalleerd, nooit iets wat de app aanlevert.
- De statusmap is voor de app alleen-lezen.
- Is een update mislukt, dan draait de vorige versie gewoon door. Het logboek staat in het portaal en in
  `update/status/update.log`.

De onderdelen:

| Bestand | Doel |
|---|---|
| `deploy/updater.sh` | voert een controle of update uit |
| `deploy/systemd/declaratietool-updater.path` | start de updater zodra er een verzoek is |
| `deploy/systemd/declaratietool-updater.timer` | controleert elk uur op een nieuwe versie |
| `deploy/systemd/declaratietool-updater.service` | de updater zelf |

Gebruik je het kant-en-klare image van GitHub (`IMAGE=` in `.env`), dan haalt de updater dat image op in
plaats van zelf te bouwen. Wacht dan met bijwerken tot GitHub Actions het nieuwe image klaar heeft
(het groene vinkje bij de commit); anders meldt het portaal dat de draaiende versie afwijkt.

## Instellen

Het installatiescript `deploy/install-vps.sh` zet dit automatisch op. Heb je de tool al eerder
geïnstalleerd, werk dan één keer met de hand bij en draai het script opnieuw (je `.env` blijft staan):

```sh
cd /opt/declaratietool
git pull
sudo bash deploy/install-vps.sh
```

Daarna staat **Bijwerken** in het menu **Instellingen**.

Controleren of de updater actief is:

```sh
systemctl status declaratietool-updater.path declaratietool-updater.timer
journalctl -u declaratietool-updater.service -n 50
```

Bijwerken kan ook nog steeds op de server zelf:

```sh
sudo /opt/declaratietool/deploy/updater.sh update
```

Veranderen de systemd-bestanden in `deploy/systemd/` in een nieuwe versie, draai dan het
installatiescript opnieuw om ze te vernieuwen.

Met Portainer werkt deze knop niet; gebruik daar **Pull and redeploy** (zie [portainer.md](portainer.md)).
