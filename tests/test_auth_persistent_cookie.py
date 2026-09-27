import unittest
from unittest.mock import patch
from types import SimpleNamespace

from src import auth
from src import auth_cookies


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

    def test_refresh_waits_for_browser_then_restores_user(self):
        state = {}
        fake_st = SimpleNamespace(session_state=state, rerun=lambda: None)
        with patch.object(auth, "st", fake_st), patch.object(auth_cookies, "st", fake_st), patch.object(
            auth_cookies, "_bridge", side_effect=[None, {
                "revision": "read", "cookies": {auth.COOKIE_NAME: "saved-token"}
            }]
        ), patch.object(auth, "validate_session_token", return_value=self.user), patch.object(
            auth, "get_user_by_id", return_value=self.user
        ):
            self.assertFalse(auth.restore_session_from_cookie())
            self.assertTrue(auth.cookie_load_is_pending())
            self.assertTrue(auth.restore_session_from_cookie())
            self.assertEqual(state["user_id"], self.user["id"])

    def test_browser_without_cookies_can_reach_login(self):
        state = {}
        fake_st = SimpleNamespace(session_state=state)
        with patch.object(auth, "st", fake_st), patch.object(auth_cookies, "st", fake_st), patch.object(
            auth_cookies, "_bridge", return_value={"revision": "read", "cookies": {}}
        ):
            self.assertFalse(auth.restore_session_from_cookie())
            self.assertFalse(auth.cookie_load_is_pending())

    def test_login_writes_survive_rerun_until_matching_acknowledgement(self):
        state = {}
        fake_st = SimpleNamespace(session_state=state)
        user = {**self.user, "password_hash": auth._hash("password")}
        with patch.object(auth, "st", fake_st), patch.object(auth_cookies, "st", fake_st), patch.object(
            auth, "get_user_by_username", return_value=user
        ), patch.object(auth, "get_user_by_id", return_value=user), patch.object(
            auth, "create_session_token", return_value="new-token"
        ), patch.object(auth_cookies, "_bridge") as bridge:
            self.assertTrue(auth.login_user("mobileuser", "password")[0])
            pending = dict(state[auth_cookies.PENDING_KEY])
            self.assertEqual(pending[auth.COOKIE_NAME]["value"], "new-token")
            self.assertIn(auth.SIGNED_COOKIE_NAME, pending)
            bridge.return_value = {"revision": "read", "cookies": {}}
            self.assertTrue(auth_cookies.sync_cookies())
            self.assertEqual(state[auth_cookies.PENDING_KEY], pending)
            bridge.return_value = {
                "revision": state[auth_cookies.REVISION_KEY],
                "cookies": dict(state[auth.COOKIE_STATE_KEY]),
            }
            self.assertFalse(auth_cookies.sync_cookies())
            self.assertNotIn(auth_cookies.PENDING_KEY, state)

    def test_logout_revokes_token_and_cannot_restore_stale_cookie(self):
        state = {"user_id": 7, "username": "mobileuser", auth.COOKIE_STATE_KEY: {
            auth.COOKIE_NAME: "saved-token", auth.SIGNED_COOKIE_NAME: "signed-token"
        }}
        fake_st = SimpleNamespace(session_state=state)
        with patch.object(auth, "st", fake_st), patch.object(auth_cookies, "st", fake_st), patch.object(
            auth, "delete_session_token"
        ) as revoke, patch.object(auth, "sync_cookies", return_value=False), patch.object(
            auth, "validate_session_token"
        ) as validate:
            auth.logout()
            revoke.assert_called_once_with("saved-token")
            for name in (auth.COOKIE_NAME, auth.SIGNED_COOKIE_NAME):
                self.assertIsNone(state[auth_cookies.PENDING_KEY][name]["value"])
            self.assertNotIn("user_id", state)
            self.assertFalse(auth.restore_session_from_cookie())
            validate.assert_not_called()

    def test_browser_reports_blocked_cookie_write(self):
        state = {}
        with patch.object(auth_cookies, "st", SimpleNamespace(session_state=state)), patch.object(
            auth_cookies, "_bridge"
        ) as bridge:
            auth_cookies.CookieController().set("sf_auth", "token", expires=auth._cookie_expires())
            bridge.return_value = {"revision": state[auth_cookies.REVISION_KEY],
                                   "cookies": {}, "error": "Cookies blocked"}
            self.assertFalse(auth_cookies.sync_cookies())
            self.assertEqual(state[auth_cookies.ERROR_KEY], "Cookies blocked")


if __name__ == "__main__":
    unittest.main()
