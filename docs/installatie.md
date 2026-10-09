# Installatie en bijwerken

## Vereisten

- Een server met [Docker](https://docs.docker.com/engine/install/) en Docker Compose.
- Een domeinnaam waarvan het A-record naar de server wijst.
- Poort 80 en 443 open (voor https via Caddy).
- Een mailbox met IMAP en SMTP voor de declaraties.

## Eerste installatie

```bash
git clone https://github.com/<jouw-naam>/declaratietool.git
cd declaratietool
cp .env.example .env
```

Vul `.env` in (zie [configuratie.md](configuratie.md)). Minimaal nodig:

- `DOMAIN` en `BASE_URL`
- `SECRET_KEY`: maak er een met `openssl rand -hex 32`
- `POSTGRES_PASSWORD`: een willekeurig wachtwoord
- de IMAP- en SMTP-gegevens

Start alles:

```bash
docker compose up -d --build
docker compose ps           # alle vier de diensten moeten "running" zijn
```

Maak je eigen account aan (je typt het wachtwoord daarna in):

```bash
docker compose exec app python -m app.cli create-user \
    --email jij@example.org --name "Jouw naam" --roles admin,treasurer
```

Rollen: `admin` (gebruikers beheren), `chair` (voorzitter), `treasurer` (boekhouder), `secretary` (secretaris). Iemand kan meerdere rollen hebben.

Log in op `https://<jouw-domein>` en voeg onder **Instellingen → Gebruikers** de voorzitter en secretaris toe.

## Bijwerken

Nieuwe versies komen via GitHub. Met het installatiescript kan een beheerder bijwerken via
**Instellingen → Bijwerken** in het portaal; zie [bijwerken.md](bijwerken.md). Met de hand, op de server:

```bash
cd declaratietool
git pull
docker compose up -d --build
```

De database wordt bij het starten automatisch bijgewerkt (Alembic-migraties).

### Alternatief: kant-en-klaar image

GitHub Actions bouwt bij elke wijziging op `main` een image in GitHub Packages (`ghcr.io/<jouw-naam>/declaratietool`). Zet `IMAGE=ghcr.io/<jouw-naam>/declaratietool:latest` in `.env` en gebruik:

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

Is je repository privé, log dan eerst in met `docker login ghcr.io` en een GitHub-token met `read:packages`.

## Al een reverse proxy?

Gebruik je Portainer, volg dan [portainer.md](portainer.md).


Gebruik je al Traefik, Nginx Proxy Manager of iets vergelijkbaars, start dan zonder Caddy:

```bash
docker compose up -d db app worker
```

De app luistert op `127.0.0.1:8000`. Laat je proxy daarheen doorsturen en zorg dat uploads tot ongeveer 50 MB zijn toegestaan.

## Back-ups

Alles wat bewaard moet blijven staat in twee Docker-volumes: `pgdata` (database) en `uploads` (bonnen en geparafeerde pdf's).

```bash
# database
docker compose exec -T db pg_dump -U declaratie declaratie > backup-$(date +%F).sql
# bijlagen
docker run --rm -v declaratietool_uploads:/data -v "$PWD":/backup alpine \
    tar czf /backup/uploads-$(date +%F).tar.gz -C /data .
```

De volumenaam begint met de mapnaam van het project; controleer hem met `docker volume ls`.

## Problemen oplossen

```bash
docker compose logs -f app worker
```

- **Geen mails binnen:** controleer de IMAP-gegevens; de worker logt elke fout. De tool verwerkt alleen *ongelezen* mail.
- **Geen mails verstuurd:** zonder `SMTP_HOST` worden mails alleen in de log gezet. Controleer poort en `SMTP_STARTTLS`/`SMTP_SSL` (587 met STARTTLS of 465 met SSL).
- **Geen https:** controleer of het domein naar de server wijst en poort 80/443 open zijn: `docker compose logs caddy`.
- **Herinneringen direct opnieuw versturen:** `docker compose exec app python -m app.cli send-reminders`.
