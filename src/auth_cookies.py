"""Browser cookie transport with acknowledged, batched writes.

Keep writes in session state until the browser confirms them, so an immediate
Streamlit rerun after login/logout cannot discard the cookie operation.
"""

from pathlib import Path
import secrets

import streamlit as st
import streamlit.components.v1 as components


CACHE_KEY = "_sf_cookies"
LOADED_KEY = "_sf_cookies_loaded"
PENDING_KEY = "_sf_cookie_operations"
REVISION_KEY = "_sf_cookie_revision"
ERROR_KEY = "_sf_cookie_error"

_bridge = components.declare_component(
    "studyforge_auth_cookies", path=str(Path(__file__).with_name("auth_cookie_component"))
)


class CookieController:
    def get(self, name):
        return st.session_state.get(CACHE_KEY, {}).get(name)

    def set(self, name, value, *, expires, same_site="lax"):
        self._queue(name, {"value": value, "expires": expires.isoformat()})

    def remove(self, name):
        self._queue(name, {"value": None})

    def _queue(self, name, operation):
        pending = dict(st.session_state.get(PENDING_KEY, {}))
        pending[name] = operation
        st.session_state[PENDING_KEY] = pending
        st.session_state[REVISION_KEY] = secrets.token_hex(16)
        cache = dict(st.session_state.get(CACHE_KEY, {}))
        if operation["value"] is None:
            cache.pop(name, None)
        else:
            cache[name] = operation["value"]
        st.session_state[CACHE_KEY] = cache


def sync_cookies():
    """Render once per run, returning whether a write still needs confirmation."""
    pending = st.session_state.get(PENDING_KEY, {})
    revision = st.session_state.get(REVISION_KEY, "read")
    result = _bridge(operations=pending, revision=revision,
                     key="_sf_auth_cookie_bridge", default=None)
    # A previous component result can arrive while a newer write is pending.
    if isinstance(result, dict) and result.get("revision") == revision:
        st.session_state[CACHE_KEY] = result.get("cookies", {})
        st.session_state[LOADED_KEY] = True
        st.session_state[ERROR_KEY] = result.get("error", "")
        st.session_state.pop(PENDING_KEY, None)
        return False
    return bool(pending)
