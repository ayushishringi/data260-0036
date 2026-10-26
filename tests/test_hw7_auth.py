"""HW7 Part 1: JWT login, /auth/me and role rules on the domain routes (needs the local MySQL)."""

from __future__ import annotations

import unittest
from datetime import timedelta

from sqlalchemy import text

try:
    from fastapi.testclient import TestClient

    from backend.database import engine
    from backend.jwt_auth import create_access_token
    from backend.main import app
    from backend.models import User

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    MYSQL_AVAILABLE = True
except Exception:  # pragma: no cover - environment without MySQL
    MYSQL_AVAILABLE = False

PASSWORDS = {"reader": "reader-pass-0036", "writer": "writer-pass-0036", "moderator": "moderator-pass-0036"}
REPORT = {
    "packageName": "hw7-unittest-pkg", "affectedVersion": "<1.0", "submitterEmail": "t@example.edu",
    "description": "Temporary record created by the HW7 auth unit test.", "severity": "low", "agreedToTerms": True,
}


@unittest.skipUnless(MYSQL_AVAILABLE, "MySQL s0036_rel is not reachable")
class JwtAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.tokens = {}
        for role, password in PASSWORDS.items():
            response = cls.client.post("/auth/login", json={"username": f"{role}0036", "password": password})
            cls.tokens[role] = response.json()["access_token"]

    def headers(self, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[role]}"}

    def test_login_valid_returns_token(self) -> None:
        response = self.client.post("/auth/login", json={"username": "reader0036", "password": PASSWORDS["reader"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token_type"], "bearer")
        self.assertEqual(response.json()["access_token"].count("."), 2)

    def test_login_invalid_returns_401(self) -> None:
        self.assertEqual(self.client.post("/auth/login", json={"username": "reader0036", "password": "x"})
                         .status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"username": "nobody", "password": "x"})
                         .status_code, 401)

    def test_me_requires_valid_token(self) -> None:
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code, 401)
        expired = create_access_token(User(id=0, username="reader0036", role="reader"), timedelta(seconds=-1))
        response = self.client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Token expired")

    def test_me_returns_identity_and_role(self) -> None:
        body = self.client.get("/auth/me", headers=self.headers("writer")).json()
        self.assertEqual((body["username"], body["role"]), ("writer0036", "writer"))

    def test_role_rules_on_reports(self) -> None:
        self.assertEqual(self.client.get("/api/reports", headers=self.headers("reader")).status_code, 200)
        self.assertEqual(self.client.post("/api/reports", json=REPORT, headers=self.headers("reader")).status_code,
                         403)
        created = self.client.post("/api/reports", json=REPORT, headers=self.headers("writer"))
        self.assertEqual(created.status_code, 201)
        report_id = created.json()["id"]
        self.assertEqual(self.client.delete(f"/api/reports/{report_id}", headers=self.headers("writer"))
                         .status_code, 403)
        self.assertEqual(self.client.delete(f"/api/reports/{report_id}", headers=self.headers("moderator"))
                         .status_code, 204)

    def test_passwords_are_hashed(self) -> None:
        with engine.connect() as connection:
            hashes = [row[0] for row in connection.execute(text("SELECT password_hash FROM users"))]
        for stored in hashes:
            self.assertNotIn(stored, PASSWORDS.values())
            salt, digest = stored.split("$")
            self.assertEqual((len(salt), len(digest)), (32, 64))


if __name__ == "__main__":
    unittest.main()
