"""Create the first administrator account (idempotent bootstrap).

The spec forbids hardcoded demo data; this is an OPERATIONAL bootstrap tool,
run deliberately by the deployer. Example (from backend/):

    python -m scripts.bootstrap_admin --email you@example.com --name "You" [--password ...]

If --password is omitted you are prompted (input hidden). Refuses to run
against a non-SQLite database unless --yes-remote is passed.
"""

import argparse
import getpass
import sys

sys.path.insert(0, ".")  # allow `python scripts/bootstrap_admin.py` from backend/

from app.core.security import hash_password
from app.db.base import Base, register_all_models
from app.db.session import SessionLocal, engine
from app.models.user import User
from app.services.rbac_service import get_role, sync_rbac
from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the first admin user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", default=None)
    parser.add_argument("--yes-remote", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.is_sqlite and not args.yes_remote:
        print("Refusing to run against a remote database without --yes-remote.")
        return 2

    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 2

    register_all_models()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        sync_rbac(db)
        email = args.email.strip().lower()
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            roles = {r.code for r in existing.roles}
            if "admin" not in roles:
                admin = get_role(db, "admin")
                existing.roles.append(admin)
                db.commit()
                print(f"Granted admin role to existing user {email}.")
            else:
                print(f"Admin {email} already exists — no change made.")
            return 0
        admin = get_role(db, "admin")
        user = User(
            email=email,
            full_name=args.name.strip(),
            hashed_password=hash_password(password),
            is_active=True,
        )
        user.roles.append(admin)
        db.add(user)
        db.commit()
        print(f"Created admin user {email} (id={user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
