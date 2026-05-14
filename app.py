"""
app.py — StudyForge entry point.
Run with:  python -m streamlit run app.py
"""

import subprocess
import sys, os
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
from src.database import init_database
from src.auth     import (
    cookie_load_is_pending,
    is_logged_in,
    login_register_form,
    logout,
    restore_session_from_cookie,
)
from src.utils import inject_sidebar_page_labels

if __name__ == "__main__" and get_script_run_ctx() is None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            os.path.abspath(__file__),
            "--server.headless=false",
        ],
        check=False,
    )
    sys.exit()

st.set_page_config(
    page_title="Sign In · StudyForge",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_database()
inject_sidebar_page_labels()


def main():
    # ── Restore session from persistent cookie (survives browser refresh) ─────
    # This must run BEFORE is_logged_in() so a returning user with a valid
    # cookie gets their session_state repopulated automatically.
    restore_session_from_cookie()
    if cookie_load_is_pending() and not st.session_state.get("_sf_waited_for_cookie_load"):
        st.session_state["_sf_waited_for_cookie_load"] = True
        st.rerun()
        st.stop()

    if not is_logged_in():
        st.markdown("# 🔐 Sign In to StudyForge")
        st.markdown(
            "Your shared study platform — enroll in courses, practise with shared "
            "question banks, track your own progress, and master any subject."
        )
        st.divider()
        st.info(
            "📌 **How it works:** Courses and question banks are shared for everyone. "
            "Your scores, progress, and mistakes are always private to you."
        )
        st.divider()
        login_register_form()
    else:
        username = st.session_state.get("username", "")
        user_id  = st.session_state.get("user_id")

        with st.sidebar:
            st.markdown(f"**👤 {username}**")
            if user_id:
                from src.database import is_admin
                from src.utils import get_effective_admin, _inject_feedback_button
                real_adm, eff_adm = get_effective_admin(user_id)
                if real_adm:
                    view_mode = st.session_state.get("admin_view_mode", "Admin View")
                    if view_mode == "Admin View":
                        st.caption("🔑 Admin")
                    else:
                        st.caption("🔑 Admin · 👁 User Preview")
                    st.markdown("**View Mode**")
                    st.radio(
                        "view_mode_radio_home",
                        options=["Admin View", "User View"],
                        index=0 if view_mode == "Admin View" else 1,
                        key="admin_view_mode",
                        label_visibility="collapsed",
                    )
                    if st.session_state.get("admin_view_mode") == "User View":
                        st.caption(
                            "👁 Previewing as regular user.  "
                            "Admin permissions are not removed."
                        )
            if st.button("Log Out", use_container_width=True):
                logout()
                st.rerun()

        from src.utils import _inject_feedback_button, get_effective_admin
        _inject_feedback_button()

        st.markdown(f"# 🎓 Welcome back, {username}!")

        if user_id:
            _, eff_adm = get_effective_admin(user_id)
            if eff_adm:
                st.info(
                    "🔑 You are an **admin**. You can upload question banks and "
                    "add materials for the active course."
                )

        st.markdown(
            "Courses are **shared** — everyone enrolled in a course studies the "
            "same materials and question bank. Your scores and progress are always **private to you**."
        )
        st.markdown("Use the **sidebar** to navigate.")
        st.divider()

        col1, col2, col3 = st.columns(3)
        col1.info("📊 **Dashboard**\nYour private progress per course")
        col2.info("📖 **Course Materials**\nShared readings & videos")
        col3.info("🗂 **Question Bank**\nShared questions per course")

        st.markdown("")
        col5, col6, col7, col8 = st.columns(4)
        col5.info("✏️ **Practice Mode**\nDrill questions at your pace")
        col6.info("⏱ **Timed Exam**\nTimed section simulation")
        col7.info("📋 **Full Exam**\nMulti-section simulation")
        col8.info("🔍 **Review Mistakes**\nYour private mistake journal")


if __name__ == "__main__":
    main()
