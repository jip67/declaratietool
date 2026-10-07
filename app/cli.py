"""Beheeropdrachten.

    python -m app.cli create-user --email jij@example.org --name "Jouw naam" --roles admin,treasurer
    python -m app.cli send-reminders
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from .db import new_session
from .models import Role, User
from .reminders import send_reminders
from .security import hash_password


def create_user(args) -> int:
    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    valid = {r.value for r in Role}
    unknown = [r for r in roles if r not in valid]
    if unknown:
        print(f"Onbekende rol(len): {', '.join(unknown)}. Kies uit: {', '.join(sorted(valid))}")
        return 1
    password = args.password or getpass.getpass("Wachtwoord (minimaal 10 tekens): ")
    if len(password) < 10:
        print("Wachtwoord te kort.")
        return 1
    db = new_session()
    try:
        email = args.email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=args.name, password_hash="")
            db.add(user)
        user.name = args.name
        user.password_hash = hash_password(password)
        user.roles = ",".join(roles)
        user.language = args.language
        user.active = True
        db.commit()
        print(f"Gebruiker {email} opgeslagen met rollen: {user.roles}")
        return 0
    finally:
        db.close()


def reminders(_args) -> int:
    db = new_session()
    try:
        print(f"{send_reminders(db)} herinnering(en) verstuurd")
        db.commit()
        return 0
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-user", help="Maak of wijzig een portaalgebruiker")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--roles", default="admin", help="Komma-gescheiden: admin,chair,treasurer,secretary")
    p.add_argument("--language", default="nl")
    p.add_argument("--password", help="Laat leeg om het wachtwoord veilig in te typen")
    p.set_defaults(func=create_user)
    r = sub.add_parser("send-reminders", help="Verstuur nu herinneringen (los van het dagelijkse schema)")
    r.set_defaults(func=reminders)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
