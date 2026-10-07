# Ontwikkelen

## Lokaal draaien zonder Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

export DATABASE_URL=sqlite:///./dev.db UPLOAD_DIR=./data/uploads SECRET_KEY=dev
alembic upgrade head
python -m app.cli create-user --email dev@example.org --name Dev --roles admin,chair,treasurer,secretary
uvicorn app.main:app --reload
```

Zonder `SMTP_HOST` worden mails in de terminal gelogd in plaats van verstuurd; zo zie je ook de link voor de indiener.

## Tests

```bash
pytest -q
```

De tests gebruiken SQLite en een tijdelijke map, en lopen de hele workflow door: mail binnen, formulier, goedkeuren met paraaf, klaarzetten, betalen, afwijzen en herinneringen.

## Opbouw

```
app/
  main.py         FastAPI-app
  config.py       instellingen uit .env
  models.py       database-tabellen, rollen en statussen
  workflow.py     de stappen en de mails die daarbij horen
  intake.py       mail ophalen (IMAP) en omzetten in declaraties
  reminders.py    dagelijkse herinneringen
  worker.py       achtergrondproces (mail + herinneringen)
  stamping.py     paraaf op foto's en pdf's
  mailer.py       mail versturen (SMTP)
  i18n.py         vertalingen
  locales/        nl.json, en.json
  routes/         pagina's: public (indiener), auth, portal
  templates/      HTML (Jinja2)
migrations/       Alembic-migraties
```

## Database wijzigen

Pas `app/models.py` aan en maak een migratie:

```bash
alembic revision --autogenerate -m "korte omschrijving"
```

Controleer het gegenereerde bestand in `migrations/versions/` en commit het. Bij de volgende start op de server wordt het automatisch toegepast.

## Een taal toevoegen

1. Kopieer `app/locales/en.json` naar bijvoorbeeld `app/locales/de.json`.
2. Vertaal de teksten. Laat de woorden tussen `{accolades}` staan; die worden ingevuld.
3. Voeg in alle taalbestanden `"lang.de": "Deutsch"` toe.

De taal verschijnt vanzelf in de taalkeuze. Indieners krijgen mails in hun eigen taal; medewerkers kiezen hun taal onder hun account.

## Beveiliging

- Wachtwoorden worden opgeslagen met scrypt.
- Na 5 mislukte inlogpogingen wordt een account 15 minuten geblokkeerd.
- Sessiecookies zijn ondertekend, `HttpOnly`, `SameSite=Lax` en bij https `Secure`.
- De link voor de indiener bevat een willekeurig token van 32 tekens; wie de link heeft, kan de declaratie zien en aanvullen tot de voorzitter heeft goedgekeurd.
- Bijlagen worden alleen getoond aan ingelogde medewerkers of via de link van de indiener.
