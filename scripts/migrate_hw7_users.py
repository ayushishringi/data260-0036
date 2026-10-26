"""HW7 Part 1: migrate the MySQL users table to username + role and seed one user per role.

Idempotent: safe to run more than once. Only password hashes are stored.
Passwords come from HW7_<ROLE>_PASSWORD environment variables, falling back to
the documented local demo passwords.

Usage: .venv/bin/python scripts/migrate_hw7_users.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.database import engine  # noqa: E402
from backend.security import hash_password  # noqa: E402

ROLES = ("reader", "writer", "moderator")
DEMO_USERS = {
    "reader0036": ("reader", os.getenv("HW7_READER_PASSWORD", "reader-pass-0036")),
    "writer0036": ("writer", os.getenv("HW7_WRITER_PASSWORD", "writer-pass-0036")),
    "moderator0036": ("moderator", os.getenv("HW7_MODERATOR_PASSWORD", "moderator-pass-0036")),
}


def main() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.begin() as connection:
        if "username" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(80) NULL AFTER id"))
        if "role" not in columns:
            connection.execute(text(
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'reader' AFTER password_hash"
            ))
        # The HW4 login identified users by email; keep those columns but make them optional.
        connection.execute(text("ALTER TABLE users MODIFY name VARCHAR(120) NULL"))
        connection.execute(text("ALTER TABLE users MODIFY email VARCHAR(255) NULL"))
        # Backfill the HW4 account: username = local part of the email.
        connection.execute(text(
            "UPDATE users SET username = SUBSTRING_INDEX(email, '@', 1) WHERE username IS NULL"
        ))
        connection.execute(text("ALTER TABLE users MODIFY username VARCHAR(80) NOT NULL"))

        indexes = {index["name"] for index in inspect(connection).get_indexes("users")}
        if "uq_users_username" not in indexes:
            connection.execute(text("ALTER TABLE users ADD CONSTRAINT uq_users_username UNIQUE (username)"))
        checks = {row[0] for row in connection.execute(text(
            "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND CONSTRAINT_TYPE = 'CHECK'"
        ))}
        if "ck_users_role" not in checks:
            connection.execute(text(
                "ALTER TABLE users ADD CONSTRAINT ck_users_role "
                "CHECK (role IN ('reader', 'writer', 'moderator'))"
            ))

        for username, (role, password) in DEMO_USERS.items():
            exists = connection.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": username}
            ).first()
            if exists:
                connection.execute(
                    text("UPDATE users SET role = :r, password_hash = :h WHERE username = :u"),
                    {"r": role, "h": hash_password(password), "u": username},
                )
            else:
                connection.execute(
                    text("INSERT INTO users (username, password_hash, role) VALUES (:u, :h, :r)"),
                    {"u": username, "h": hash_password(password), "r": role},
                )

        rows = connection.execute(text(
            "SELECT id, username, role, LEFT(password_hash, 24) AS hash_prefix FROM users ORDER BY id"
        )).all()
    print("users table after migration:")
    for row in rows:
        print(f"  id={row.id:<3} username={row.username:<15} role={row.role:<10} password_hash={row.hash_prefix}...")


if __name__ == "__main__":
    main()
