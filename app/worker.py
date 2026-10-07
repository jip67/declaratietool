"""Achtergrondproces: haalt mail op en verstuurt dagelijkse herinneringen.

Start met: python -m app.worker
"""

import logging
import time

from . import intake, reminders
from .config import get_settings
from .db import new_session

log = logging.getLogger("worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.imap_host:
        log.warning("IMAP_HOST is niet ingesteld: er wordt geen mail opgehaald.")
    log.info("Worker gestart (mail elke %ss, herinneringen om %s:00)", settings.imap_poll_seconds, settings.reminder_hour)
    while True:
        try:
            intake.poll_mailbox(new_session)
        except Exception:
            log.exception("Mail ophalen mislukt")
        db = new_session()
        try:
            reminders.run_if_due(db)
        except Exception:
            db.rollback()
            log.exception("Herinneringen versturen mislukt")
        finally:
            db.close()
        time.sleep(settings.imap_poll_seconds)


if __name__ == "__main__":
    main()
