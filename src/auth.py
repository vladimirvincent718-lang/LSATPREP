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

import hashlib
from datetime import datetime, timedelta

import streamlit as st

from src.database import (
    create_user, get_user_by_username,
    set_security_question, get_security_question,
    verify_security_answer, reset_password,
    create_session_token, validate_session_token,
    delete_session_token, delete_all_sessions_for_user,
    SESSION_TOKEN_DAYS,
)

# ── Constants ─────────────────────────────────────────────────────────────────
COOKIE_NAME   = "sf_auth"          # browser cookie that stores the session token
LAST_USERNAME_COOKIE_NAME = "sf_last_username"
SESSION_DAYS  = SESSION_TOKEN_DAYS  # kept in sync with the DB-level expiry
COOKIE_STATE_KEY = "_sf_cookies"
COOKIE_LOAD_WAIT_KEY = "_sf_waited_for_cookie_load"
COOKIE_LOAD_ATTEMPTS_KEY = "_sf_cookie_load_attempts"
COOKIE_LOAD_MAX_ATTEMPTS = 5

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


def _get_cookie_controller():
    """
    Return a CookieController instance.

    CookieController caches values in st.session_state["_sf_cookies"].  After a
    hard refresh that cache may start as an empty dict before the browser has
    answered, so restore_session_from_cookie() can explicitly refresh it while
    the cookie-load grace window is open.
    """
    from streamlit_cookies_controller import CookieController
    # CookieController stores cookie values at st.session_state[key].
    # Creating it with the same key on every call is safe: on the first call it
    # fires the JS component; on subsequent calls it reads from session_state.
    return CookieController(key=COOKIE_STATE_KEY)


def _cookie_expires() -> datetime:
    return datetime.now() + timedelta(days=SESSION_DAYS)


def _remove_cookie(cc, name: str) -> None:
    try:
        cc.remove(name)
    except KeyError:
        # CookieController removes in the browser before popping its local cache.
        pass


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
            expires=_cookie_expires(),
            same_site="strict",
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
    Called at the top of every page entry point.  If session_state already
    has a user_id this is a cheap no-op.  Otherwise the browser cookie is
    read and, if the token is valid, session_state is repopulated so the user
    does not have to log in again after a browser refresh.

    Returns True if the session is (now) authenticated, False otherwise.

    Note on Streamlit's async component model
    ──────────────────────────────────────────
    On the very first render after a browser refresh, CookieController fires a
    JS component to read cookies from the browser.  Streamlit reruns the script
    once the component responds.  During that initial render the cookie dict may
    be empty (default ``{}``) and this function will return False — but the
    automatic rerun that follows immediately will have the real cookie data and
    will restore the session transparently.  Users will not notice the
    sub-second delay.
    """
    if is_logged_in():
        st.session_state.pop(COOKIE_LOAD_ATTEMPTS_KEY, None)
        return True

    try:
        cc    = _get_cookie_controller()
        token = cc.get(COOKIE_NAME)
        if not token:
            attempts = int(st.session_state.get(COOKIE_LOAD_ATTEMPTS_KEY, 0))
            cookie_cache = st.session_state.get(COOKIE_STATE_KEY)
            if attempts < COOKIE_LOAD_MAX_ATTEMPTS and not cookie_cache:
                try:
                    cc.refresh()
                except Exception:
                    pass
            return False

        user = validate_session_token(token)
        if not user:
            # Token expired or revoked — remove the stale cookie
            try:
                _remove_cookie(cc, COOKIE_NAME)
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
            cc.set(
                COOKIE_NAME,
                token,
                expires=_cookie_expires(),
                same_site="strict",
            )
        except Exception:
            pass
        return True

    except Exception:
        # Never crash the app if cookie machinery fails — just show login page
        return False


def cookie_load_is_pending() -> bool:
    """
    True while the browser cookie component is still likely resolving.

    CookieController may put an empty dict in session state before the browser
    has returned the actual cookie values, so "key exists" is not enough to
    prove there is no auth cookie after a hard refresh.
    """
    if is_logged_in():
        return False

    attempts = int(st.session_state.get(COOKIE_LOAD_ATTEMPTS_KEY, 0))
    if attempts >= COOKIE_LOAD_MAX_ATTEMPTS:
        return False

    cookie_cache = st.session_state.get(COOKIE_STATE_KEY)
    return COOKIE_STATE_KEY not in st.session_state or not cookie_cache


def wait_for_cookie_load() -> None:
    """
    Give the browser cookie component a few reruns to hydrate cookies.
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
    return st.session_state["user_id"]


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
    st.session_state["user_id"]  = user["id"]
    st.session_state["username"] = user["username"]
    _remember_last_username(user["username"])

    if not remember_me:
        try:
            _remove_cookie(_get_cookie_controller(), COOKIE_NAME)
        except Exception:
            pass
        return True, "Logged in."

    # ── Create persistent token and set cookie ────────────────────────────────
    try:
        token   = create_session_token(user["id"], days=SESSION_DAYS)
        expires = _cookie_expires()
        cc      = _get_cookie_controller()
        cc.set(
            COOKIE_NAME,
            token,
            expires=expires,
            same_site="strict",
            # secure=True   ← uncomment when deploying over HTTPS
        )
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
    try:
        cc    = _get_cookie_controller()
        token = cc.get(COOKIE_NAME)
        if token:
            delete_session_token(token)
        _remove_cookie(cc, COOKIE_NAME)
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
