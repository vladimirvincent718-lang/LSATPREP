import unittest
from unittest.mock import patch

from src import auth


class PersistentAuthCookieTests(unittest.TestCase):
    def setUp(self):
        self.user = {
            "id": 7,
            "username": "mobileuser",
            "password_hash": "password-hash-v1",
            "created_at": "2026-06-19T10:00:00",
            "is_admin": 0,
        }

    def test_signed_cookie_restores_user(self):
        with patch.object(auth, "_auth_secret", return_value="test-secret"), patch.object(
            auth, "get_user_by_id", return_value=self.user
        ):
            cookie = auth._encode_signed_auth_cookie(self.user)
            restored = auth._decode_signed_auth_cookie(cookie)

        self.assertEqual(restored["id"], self.user["id"])
        self.assertEqual(restored["username"], self.user["username"])

    def test_tampered_signed_cookie_is_rejected(self):
        with patch.object(auth, "_auth_secret", return_value="test-secret"), patch.object(
            auth, "get_user_by_id", return_value=self.user
        ):
            cookie = auth._encode_signed_auth_cookie(self.user)
            tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")

            self.assertIsNone(auth._decode_signed_auth_cookie(tampered))

    def test_password_change_invalidates_old_signed_cookie(self):
        changed_user = {**self.user, "password_hash": "password-hash-v2"}
        with patch.object(auth, "_auth_secret", return_value="test-secret"):
            cookie = auth._encode_signed_auth_cookie(self.user)
            with patch.object(auth, "get_user_by_id", return_value=changed_user):
                self.assertIsNone(auth._decode_signed_auth_cookie(cookie))


if __name__ == "__main__":
    unittest.main()
