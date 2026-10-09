"""Applicatie-instellingen, gelezen uit omgevingsvariabelen of een .env-bestand."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Algemeen
    app_name: str = "Declaratietool"
    organisation_name: str = "Mijn vereniging"
    base_url: str = "http://localhost:8000"
    secret_key: str = "verander-mij"
    default_language: str = "nl"
    timezone: str = "Europe/Amsterdam"
    reference_prefix: str = "D"

    # Opslag
    database_url: str = "postgresql+psycopg://declaratie:declaratie@db:5432/declaratie"
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 15
    # Gedeelde map met de updater op de server (zie docs/bijwerken.md)
    update_dir: str = "/data/update"
    # Versie van dit image, gezet bij het bouwen (Dockerfile)
    app_version: str = ""

    # Inkomende mail (IMAP)
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_poll_seconds: int = 60

    # Uitgaande mail (SMTP). Zonder smtp_host worden mails alleen gelogd.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    mail_from: str = "declaraties@example.org"

    # Herinneringen
    reminder_hour: int = 9
    submitter_reminder_days: int = 14

    # Logboek (inlogpogingen en binnengekomen mail): na zoveel dagen opruimen; 0 = nooit.
    log_retention_days: int = 90

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
