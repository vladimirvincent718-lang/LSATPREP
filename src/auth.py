"""
auth.py — Authentication helpers: hashing, login, register, session guard,
          security-question-based password reset, and cookie-based session
          persistence so users stay logged in across browser refreshes.

Session architecture
────────────────────
1. On successful login a cryptographically-random token is created and stored
   in the ``user_sessions`` DB table (user_id + token + expires_at).
2. The token is written to the browser as a cookie named ``sf_auth``.
   The cookie contains ONLY the opaque token string — no passwords, no PII.
3. On every page load (including after a browser refresh) ``restore_session_from_cookie()``
   reads the cookie, validates the token against the DB, and restores
   st.session_state if the token is valid and not expired.
4. On logout the token is deleted from the DB and the cookie is removed.
5. Tokens use a far-future expiry so refreshes and browser restarts keep the
   user logged in.  Explicit logout still revokes the token server-side and
   removes the browser cookie.
"""

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

import streamlit as st
from src.auth_cookies import (
    CookieController, sync_cookies, LOADED_KEY, ERROR_KEY,
)

from src.database import (
    create_user, get_user_by_id, get_user_by_username,
    set_security_question, get_security_question,
    verify_security_answer, reset_password,
    create_session_token, validate_session_token,
    delete_session_token, delete_all_sessions_for_user,
    SESSION_TOKEN_DAYS,
)

# ── Constants ─────────────────────────────────────────────────────────────────
COOKIE_NAME   = "sf_auth"          # browser cookie that stores the session token
SIGNED_COOKIE_NAME = "sf_auth_persist"
LAST_USERNAME_COOKIE_NAME = "sf_last_username"
SESSION_DAYS  = SESSION_TOKEN_DAYS  # kept in sync with the DB-level expiry
COOKIE_STATE_KEY = "_sf_cookies"
COOKIE_LOAD_WAIT_KEY = "_sf_waited_for_cookie_load"
COOKIE_LOAD_ATTEMPTS_KEY = "_sf_cookie_load_attempts"
AUTH_COOKIE_VERSION = 1
AUTH_SECRET_ENV = "STUDYFORGE_AUTH_SECRET"
SIGNED_OUT_KEY = "_sf_explicitly_signed_out"

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What city were you born in?",
    "What is your mother's maiden name?",
    "What was the name of your elementary school?",
    "What was the make of your first car?",
    "What is the name of your favourite childhood friend?",
    "What street did you grow up on?",
    "What was your childhood nickname?",
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _user_value(user, key: str, default=None):
    if user is None:
        return default
    if isinstance(user, dict):
        return user.get(key, default)
    try:
        return user[key]
    except Exception:
        return default


def _get_cookie_controller():
    """Read cached cookies and queue writes for browser acknowledgement."""
    return CookieController()


def _cookie_expires() -> datetime:
    return datetime.now() + timedelta(days=SESSION_DAYS)


def _cookie_kwargs() -> dict:
    return {
        "expires": _cookie_expires(),
        "same_site": "lax",
    }


def _remove_cookie(cc, name: str) -> None:
    try:
        cc.remove(name)
    except KeyError:
        # CookieController removes in the browser before popping its local cache.
        pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _auth_secret() -> str:
    env_secret = os.getenv(AUTH_SECRET_ENV, "").strip()
    if env_secret:
        return env_secret
    try:
        for key in ("auth_cookie_secret", AUTH_SECRET_ENV):
            value = st.secrets.get(key, "")
            if value:
                return str(value)
    except Exception:
        pass
    return "studyforge-auth-cookie-fallback"


def _signing_key(user) -> bytes:
    password_hash = str(_user_value(user, "password_hash", ""))
    created_at = str(_user_value(user, "created_at", ""))
    material = f"{_auth_secret()}:{password_hash}:{created_at}".encode("utf-8")
    return hashlib.sha256(material).digest()


def _signed_cookie_payload(user) -> dict:
    return {
        "v": AUTH_COOKIE_VERSION,
        "uid": int(_user_value(user, "id")),
        "username": str(_user_value(user, "username", "")),
        "exp": int((datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).timestamp()),
    }


def _encode_signed_auth_cookie(user) -> str:
    payload = _signed_cookie_payload(user)
    body = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        _signing_key(user),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{body}.{_b64encode(signature)}"


def _decode_signed_auth_cookie(value: str) -> dict | None:
    try:
        body, supplied_signature = str(value).split(".", 1)
        payload = json.loads(_b64decode(body).decode("utf-8"))
        if payload.get("v") != AUTH_COOKIE_VERSION:
            return None
        if int(payload.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()):
            return None

        user = get_user_by_id(int(payload["uid"]))
        if user is None:
            return None
        if str(_user_value(user, "username", "")).lower() != str(payload.get("username", "")).lower():
            return None

        expected_signature = _b64encode(
            hmac.new(
                _signing_key(user),
                body.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None

        return {
            "id": _user_value(user, "id"),
            "username": _user_value(user, "username"),
            "is_admin": _user_value(user, "is_admin", 0),
            "password_hash": _user_value(user, "password_hash", ""),
            "created_at": _user_value(user, "created_at", ""),
        }
    except Exception:
        return None


def _restore_user_state(user) -> None:
    st.session_state["user_id"] = _user_value(user, "id")
    st.session_state["username"] = _user_value(user, "username")
    _remember_last_username(_user_value(user, "username", ""))
    st.session_state.pop(COOKIE_LOAD_WAIT_KEY, None)
    st.session_state.pop(COOKIE_LOAD_ATTEMPTS_KEY, None)


def _write_persistent_auth_cookie(cc, user) -> None:
    cc.set(
        SIGNED_COOKIE_NAME,
        _encode_signed_auth_cookie(user),
        **_cookie_kwargs(),
    )


def _refresh_auth_cookies(cc, user, token: str | None = None) -> None:
    full_user = get_user_by_id(int(_user_value(user, "id"))) or user
    if token:
        cc.set(COOKIE_NAME, token, **_cookie_kwargs())
    _write_persistent_auth_cookie(cc, full_user)


def _remember_last_username(username: str) -> None:
    clean_username = (username or "").strip()
    if not clean_username:
        return
    st.session_state["last_login_username"] = clean_username
    try:
        cc = _get_cookie_controller()
        cc.set(
            LAST_USERNAME_COOKIE_NAME,
            clean_username,
            **_cookie_kwargs(),
        )
    except Exception:
        pass


def get_last_login_username() -> str:
    username = st.session_state.get("last_login_username")
    if username:
        return str(username)
    try:
        username = _get_cookie_controller().get(LAST_USERNAME_COOKIE_NAME)
    except Exception:
        username = None
    if username:
        st.session_state["last_login_username"] = str(username)
        return str(username)
    return ""


# ── Public session helpers ────────────────────────────────────────────────────

def is_logged_in() -> bool:
    """True when session_state has a validated user_id for this Streamlit run."""
    return "user_id" in st.session_state


def restore_session_from_cookie() -> bool:
    """
    Called at the top of every page entry point. If session_state already
    has a user_id, only pending cookie writes are flushed. Otherwise the cookie is
    read and, if the token is valid, session_state is repopulated so the user
    does not have to log in again after a browser refresh.

    Returns True if the session is (now) authenticated, False otherwise.

    Wait for an explicit browser response before interpreting missing cookies
    as signed out. Pending writes survive reruns until acknowledged.
    """
    if sync_cookies():
        st.caption("Saving your sign-in preference...")
        st.stop()
    if st.session_state.get(ERROR_KEY):
        st.warning(st.session_state[ERROR_KEY])
    if st.session_state.get(SIGNED_OUT_KEY):
        return False
    if is_logged_in():
        st.session_state.pop(COOKIE_LOAD_ATTEMPTS_KEY, None)
        return True

    try:
        cc = _get_cookie_controller()
        token = cc.get(COOKIE_NAME)
        signed_cookie = cc.get(SIGNED_COOKIE_NAME)
        if not token and not signed_cookie:
            return False

        user = validate_session_token(token) if token else None
        if not user:
            if signed_cookie:
                user = _decode_signed_auth_cookie(signed_cookie)
                if user:
                    new_token = None
                    try:
                        new_token = create_session_token(user["id"], days=SESSION_DAYS)
                    except Exception:
                        pass
                    _restore_user_state(user)
                    try:
                        _refresh_auth_cookies(cc, user, new_token)
                    except Exception:
                        pass
                    st.rerun()
                    return True
            # Token expired or revoked — remove the stale cookie
            try:
                _remove_cookie(cc, COOKIE_NAME)
                _remove_cookie(cc, SIGNED_COOKIE_NAME)
            except Exception:
                pass
            return False

        # ── Restore session state ─────────────────────────────────────────────
        st.session_state["user_id"]  = user["id"]
        st.session_state["username"] = user["username"]
        _remember_last_username(user["username"])
        st.session_state.pop(COOKIE_LOAD_WAIT_KEY, None)
        st.session_state.pop(COOKIE_LOAD_ATTEMPTS_KEY, None)
        try:
            _refresh_auth_cookies(cc, user, token)
        except Exception:
            pass
        # Flush renewed cookies before presenting controls, so the subsequent
        # acknowledgement cannot interrupt the user's first action on the page.
        st.rerun()
        return True

    except Exception:
        # Never crash the app if cookie machinery fails — just show login page
        return False


def cookie_load_is_pending() -> bool:
    """Empty and not-yet-loaded are distinct, even on a slow connection."""
    return not is_logged_in() and not st.session_state.get(LOADED_KEY, False)


def wait_for_cookie_load() -> None:
    """
    Wait for the browser cookie component's explicit read acknowledgement.
    Callers should use this before rendering the login UI after a refresh.
    """
    if not cookie_load_is_pending():
        return

    st.session_state[COOKIE_LOAD_WAIT_KEY] = True
    st.session_state[COOKIE_LOAD_ATTEMPTS_KEY] = (
        int(st.session_state.get(COOKIE_LOAD_ATTEMPTS_KEY, 0)) + 1
    )
    st.caption("Restoring your saved sign-in...")
    st.stop()


def require_login() -> int:
    """
    Ensure the current user is authenticated, restoring from cookie if needed.
    Returns the user_id.  Calls st.stop() and shows a warning if not logged in.
    """
    restore_session_from_cookie()
    if not is_logged_in():
        wait_for_cookie_load()
        st.warning("Please log in from the Home page.")
        st.stop()
    st.session_state.pop(COOKIE_LOAD_WAIT_KEY, None)
    st.session_state.pop(COOKIE_LOAD_ATTEMPTS_KEY, None)
    user_id = st.session_state["user_id"]
    run_practice_daily_rollover(user_id)
    return user_id


def run_practice_daily_rollover(user_id: int) -> list[dict]:
    """Finalize yesterday's practice once a signed-in user returns."""
    from src.exam_engine import (
        _st,
        clear_quiz,
        finalize_stale_practice_drafts,
    )

    finalized = finalize_stale_practice_drafts(user_id)
    if not finalized:
        return []
    finalized_ids = {row["attempt_id"] for row in finalized}
    if _st("attempt_id") in finalized_ids:
        clear_quiz(delete_draft=False)
    existing = st.session_state.get("_practice_daily_rollover", [])
    st.session_state["_practice_daily_rollover"] = [*existing, *finalized]
    return finalized


# ── Login / logout ────────────────────────────────────────────────────────────

def login_user(
    username: str,
    password: str,
    remember_me: bool = True,
) -> tuple[bool, str]:
    """
    Validate credentials.  On success:
      - Populates st.session_state with user_id and username.
      - Creates a DB session token and writes it to a browser cookie when
        remember_me is enabled.
    """
    user = get_user_by_username(username)
    if not user:
        return False, "Username not found."
    if user["password_hash"] != _hash(password):
        return False, "Incorrect password."

    # ── Populate session state ────────────────────────────────────────────────
    st.session_state.pop(SIGNED_OUT_KEY, None)
    st.session_state["user_id"]  = user["id"]
    st.session_state["username"] = user["username"]
    _remember_last_username(user["username"])

    if not remember_me:
        try:
            cc = _get_cookie_controller()
            _remove_cookie(cc, COOKIE_NAME)
            _remove_cookie(cc, SIGNED_COOKIE_NAME)
        except Exception:
            pass
        return True, "Logged in."

    # ── Create persistent token and set cookie ────────────────────────────────
    try:
        token   = create_session_token(user["id"], days=SESSION_DAYS)
        cc      = _get_cookie_controller()
        _refresh_auth_cookies(cc, user, token)
    except Exception:
        # Cookie creation failing should NOT prevent login — the session will
        # just be non-persistent for this browser session.
        pass

    return True, "Logged in."


def logout() -> None:
    """
    Explicitly log out: delete the DB token, remove the browser cookie, and
    clear session state.  Only called when the user clicks the Logout button.
    """
    st.session_state[SIGNED_OUT_KEY] = True
    try:
        cc    = _get_cookie_controller()
        token = cc.get(COOKIE_NAME)
        if token:
            delete_session_token(token)
        _remove_cookie(cc, COOKIE_NAME)
        _remove_cookie(cc, SIGNED_COOKIE_NAME)
    except Exception:
        pass

    # Clear all auth-related session state keys
    for key in (
        "user_id",
        "username",
        "admin_view_mode",
        COOKIE_LOAD_WAIT_KEY,
        COOKIE_LOAD_ATTEMPTS_KEY,
    ):
        st.session_state.pop(key, None)


# ── Registration ──────────────────────────────────────────────────────────────

def register_user(username: str, password: str) -> tuple[bool, str]:
    if not username or not password:
        return False, "Username and password cannot be empty."
    if len(password) < 4:
        return False, "Password must be at least 4 characters."
    ok = create_user(username, _hash(password))
    if ok:
        return True, "Account created! You can now log in."
    return False, "Username already taken. Please choose another."


# ── Security question / password reset ───────────────────────────────────────

def save_security_question(user_id: int, question: str,
                            answer: str) -> tuple[bool, str]:
    if not question or not answer:
        return False, "Both a question and an answer are required."
    if len(answer.strip()) < 2:
        return False, "Answer must be at least 2 characters."
    set_security_question(user_id, question, _hash(answer))
    return True, "Security question saved."


def do_password_reset(username: str, answer: str,
                      new_password: str) -> tuple[bool, str]:
    if not username:
        return False, "Please enter your username."
    user = get_user_by_username(username)
    if not user:
        return False, "Username not found."
    if not user["security_answer_hash"]:
        return False, (
            "No security question is set for this account. "
            "Ask the account owner to set one in Settings → Account."
        )
    if not verify_security_answer(username, _hash(answer)):
        return False, "Incorrect answer. Please try again."
    if len(new_password) < 4:
        return False, "New password must be at least 4 characters."
    ok = reset_password(username, _hash(new_password))
    if ok:
        # Invalidate all existing sessions after a password change
        try:
            delete_all_sessions_for_user(user["id"])
        except Exception:
            pass
        return True, "Password reset successfully! You can now log in."
    return False, "Something went wrong. Please try again."


# ── Login / register / forgot-password UI form ────────────────────────────────

def login_register_form() -> None:
    tab_login, tab_register, tab_forgot = st.tabs(
        ["🔑 Log In", "✨ Create Account", "🔒 Forgot Password?"]
    )

    with tab_login:
        with st.form("login_form"):
            uname = st.text_input(
                "Username",
                value=get_last_login_username(),
                key="login_username",
            )
            pwd   = st.text_input("Password", type="password")
            remember_me = st.checkbox("Keep me signed in", value=True)
            sub   = st.form_submit_button("Log In", use_container_width=True)
        if sub:
            ok, msg = login_user(uname, pwd, remember_me=remember_me)
            if ok:
                st.success(msg)
                st.rerun()
                st.stop()
            else:
                st.error(msg)
                if "Incorrect password" in msg:
                    st.caption("Forgot your password? Use the **Forgot Password?** tab above.")

    with tab_register:
        st.markdown("Create your account below. You can set a security question "
                    "afterwards in **Settings → Account**.")
        with st.form("register_form"):
            new_u  = st.text_input("Choose a username")
            new_p  = st.text_input("Choose a password (min 4 characters)", type="password")
            new_p2 = st.text_input("Confirm password", type="password")
            sub2   = st.form_submit_button("Create Account", use_container_width=True)
        if sub2:
            if new_p != new_p2:
                st.error("Passwords do not match.")
            else:
                ok, msg = register_user(new_u, new_p)
                if ok:
                    st.success(msg)
                    st.info("💡 Tip: After logging in, go to **Settings → Account** "
                            "to set a security question so you can recover your password.")
                else:
                    st.error(msg)

    with tab_forgot:
        st.markdown("### Reset Your Password")
        st.markdown(
            "Enter your username to look up your security question. "
            "If you never set one, you will need to reset your password manually."
        )
        reset_uname = st.text_input("Username", key="reset_uname")

        if st.button("Look Up My Question", use_container_width=True):
            if not reset_uname:
                st.warning("Enter your username first.")
            else:
                q = get_security_question(reset_uname)
                if q:
                    st.session_state["reset_question"] = q
                    st.session_state["reset_username"] = reset_uname
                else:
                    user = get_user_by_username(reset_uname)
                    if not user:
                        st.error("Username not found.")
                    else:
                        st.error(
                            "No security question is set for this account. "
                            "Set one in **Settings → Account** while logged in."
                        )

        if st.session_state.get("reset_question") and \
           st.session_state.get("reset_username") == reset_uname:
            q = st.session_state["reset_question"]
            st.info(f"**Security Question:** {q}")
            with st.form("reset_form"):
                answer   = st.text_input("Your Answer",      type="password")
                new_pwd  = st.text_input("New Password",     type="password")
                new_pwd2 = st.text_input("Confirm Password", type="password")
                do_reset = st.form_submit_button("Reset Password",
                                                  use_container_width=True)
            if do_reset:
                if new_pwd != new_pwd2:
                    st.error("New passwords do not match.")
                else:
                    ok, msg = do_password_reset(reset_uname, answer, new_pwd)
                    if ok:
                        st.success(f"✅ {msg}")
                        st.session_state.pop("reset_question", None)
                        st.session_state.pop("reset_username", None)
                    else:
                        st.error(msg)
