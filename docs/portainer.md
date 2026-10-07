# Installeren met Portainer

Heb je al een Docker-server met Portainer en een reverse proxy (bijvoorbeeld Nginx Proxy Manager, Traefik of Caddy), dan gebruik je `docker-compose.portainer.yml`. Die gebruikt het kant-en-klare image van GitHub en bevat geen eigen proxy.

## 1. Subdomein

Maak in het DNS-beheer van je domein een record voor het subdomein, bijvoorbeeld `declaraties.example.nl`:

- een **A-record** naar het publieke IP-adres van je server, of
- een **CNAME** naar een naam die al naar je server wijst.

## 2. Stack aanmaken

In Portainer: **Stacks → Add stack**.

- **Name:** `declaratietool`
- **Build method:** *Repository*
  - Repository URL: `https://github.com/jip67/declaratietool`
  - Repository reference: `refs/heads/main`
  - Compose path: `docker-compose.portainer.yml`
  - Is de repository privé, zet dan *Authentication* aan met je GitHub-naam en een token met leesrechten.
- **Environment variables** (via *Advanced mode* kun je ze in één keer plakken):

```
BASE_URL=https://declaraties.example.nl
SECRET_KEY=<lange willekeurige tekst, bijv. uit: openssl rand -hex 32>
POSTGRES_PASSWORD=<willekeurig wachtwoord>
ORGANISATION_NAME=Mijn vereniging
APP_PORT=8000
IMAP_HOST=
IMAP_USER=
IMAP_PASSWORD=
SMTP_HOST=
SMTP_USER=
SMTP_PASSWORD=
MAIL_FROM=
```

Laat `IMAP_HOST` en `SMTP_HOST` leeg om eerst zonder mail te testen: mails komen dan alleen in de log van de container `app`/`worker`, inclusief de links.

Klik op **Deploy the stack**. Is poort 8000 al bezet, kies dan een andere `APP_PORT`.

## 3. Reverse proxy

Laat je proxy het subdomein doorsturen naar `http://<ip-van-de-server>:8000` (of de `APP_PORT` die je koos) en zet daar https (Let's Encrypt) aan. Sta uploads tot zo'n 50 MB toe.

Bij **Nginx Proxy Manager**: *Proxy Hosts → Add*, domein invullen, scheme `http`, forward host het IP van de server, poort `8000`, en op het tabblad *SSL* een Let's Encrypt-certificaat aanvragen met *Force SSL*. Zet onder *Advanced* eventueel `client_max_body_size 50m;`.

## 4. Eerste gebruiker

In Portainer: **Containers → declaratietool-app-1 → Console → Connect** (`/bin/sh`), en dan:

```sh
python -m app.cli create-user --email jij@example.nl --name "Jouw naam" --roles admin,treasurer
```

Je typt het wachtwoord daarna in. Log in op je subdomein en voeg de andere bestuursleden toe onder **Gebruikers**.

## Bijwerken

Open de stack en klik op **Pull and redeploy** met *Re-pull image* aangevinkt. Wil je dat automatisch, zet dan *GitOps updates* aan op de stack. Het image wordt bij elke wijziging op `main` opnieuw gebouwd door GitHub Actions.
