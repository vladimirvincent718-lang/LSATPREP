"""
pages/10_Settings.py — Study preferences, account settings, and backup.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import sqlite3
import hashlib

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, get_effective_admin, DIFFICULTY_LABELS
from src.database import (
    get_all_settings, set_setting, get_connection, DB_PATH,
    get_app_settings, set_app_setting,
)

st.set_page_config(page_title="Settings · StudyForge", page_icon="⚙️", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
page_header("⚙️ Settings", "Configure difficulty, timing, and your account")

settings = get_all_settings(user_id)
real_admin, admin = get_effective_admin(user_id)

tab_general, tab_hard, tab_account, tab_backup = st.tabs(
    ["🎛 General", "⚡ Hard Mode", "👤 Account", "💾 Backup"]
)

# ── General settings ──────────────────────────────────────────────────────────
with tab_general:
    st.markdown("### General Settings")
    with st.form("general_settings"):
        sec_time = st.slider(
            "Default Section Time (minutes)",
            min_value=5, max_value=120,
            value=int(settings.get("section_time_minutes", "35")),
            help="Used for Timed Exam when hard mode is off.",
        )
        diff_range = st.select_slider(
            "Difficulty Range (for question selection)",
            options=[1, 2, 3, 4, 5],
            value=(
                int(settings.get("min_difficulty", "1")),
                int(settings.get("max_difficulty", "5")),
            ),
            format_func=lambda x: f"{x} - {DIFFICULTY_LABELS.get(x, x)}",
        )
        show_exp = st.selectbox(
            "Show Explanations",
            options=["always", "after_section", "after_exam"],
            index=["always", "after_section", "after_exam"].index(
                settings.get("show_explanations", "always")
            ),
            help=(
                "always = instant feedback after each answer  \n"
                "after_section = only at end of section  \n"
                "after_exam = only after full exam"
            ),
        )
        q_mix = st.selectbox(
            "Default Question Mix",
            options=["balanced", "weakness"],
            index=0 if settings.get("question_mix", "balanced") == "balanced" else 1,
            format_func=lambda value: {
                "balanced": "Balanced",
                "weakness": "Smart Review Queue",
            }.get(value, value),
            help=(
                "Smart Review Queue brings missed or due questions back sooner "
                "and spaces them out after repeated correct answers."
            ),
        )
        save_general = st.form_submit_button("💾 Save General Settings",
                                              use_container_width=True)

    if save_general:
        set_setting(user_id, "section_time_minutes", str(sec_time))
        set_setting(user_id, "min_difficulty",       str(diff_range[0]))
        set_setting(user_id, "max_difficulty",       str(diff_range[1]))
        set_setting(user_id, "show_explanations",    show_exp)
        set_setting(user_id, "question_mix",         q_mix)
        st.success("General settings saved.")

# ── Hard mode settings ────────────────────────────────────────────────────────
with tab_hard:
    st.markdown("### ⚡ Hard Mode")
    st.markdown(
        "Hard Mode makes practice harder than normal — like training with ankle weights. "
        "Affects Practice Mode, Timed Exam, and Full Exam."
    )
    current_hard = settings.get("hard_mode", "false") == "true"

    with st.form("hard_mode_settings"):
        hard_on   = st.toggle("Enable Hard Mode", value=current_hard)
        hard_time = st.slider(
            "Hard Mode Timer (minutes per section)",
            min_value=5, max_value=35,
            value=int(settings.get("hard_mode_time_minutes", "30")),
        )
        st.divider()
        st.markdown("**What Hard Mode does:**")
        st.markdown("""
        - ⏱ Shorter timer (set above)
        - 💪 Biases toward Advanced Calculations and Stretch Problems
        - 🚫 Disables the Quit button during timed sessions
        - 🔒 Hides explanations until the section is submitted
        """)
        save_hard = st.form_submit_button("💾 Save Hard Mode Settings",
                                           use_container_width=True)

    if save_hard:
        set_setting(user_id, "hard_mode",              "true" if hard_on else "false")
        set_setting(user_id, "hard_mode_time_minutes", str(hard_time))
        status = "ON 🔥" if hard_on else "OFF"
        st.success(f"Hard Mode is now **{status}**.")
        st.rerun()

    if current_hard:
        st.warning(
            f"⚡ Hard Mode is currently **ON** — "
            f"{settings.get('hard_mode_time_minutes', '30')} minutes per section."
        )

# ── Account settings ──────────────────────────────────────────────────────────
with tab_account:
    from src.database import get_user_by_username
    from src.auth import SECURITY_QUESTIONS, save_security_question

    st.markdown(f"### Account: `{username}`")

    if admin:
        st.markdown("#### Resource Discovery Integrations")
        st.caption(
            "These app-wide keys are used by admins to find course videos and articles. "
            "Learners cannot see or edit them."
        )
        integration_keys = [
            "youtube_api_key",
            "google_custom_search_api_key",
            "google_custom_search_engine_id",
        ]
        app_settings = get_app_settings(integration_keys)
        with st.form("resource_discovery_integrations"):
            youtube_key = st.text_input(
                "YouTube Data API key",
                value=app_settings.get("youtube_api_key", ""),
                type="password",
                help="Used for YouTube video search and duration metadata.",
            )
            google_key = st.text_input(
                "Google Custom Search API key",
                value=app_settings.get("google_custom_search_api_key", ""),
                type="password",
                help="Used for article discovery.",
            )
            google_cx = st.text_input(
                "Google Custom Search Engine ID",
                value=app_settings.get("google_custom_search_engine_id", ""),
                help="The Programmable Search Engine ID (cx).",
            )
            save_integrations = st.form_submit_button(
                "Save Integration Settings",
                use_container_width=True,
            )

        if save_integrations:
            set_app_setting("youtube_api_key", youtube_key.strip())
            set_app_setting("google_custom_search_api_key", google_key.strip())
            set_app_setting("google_custom_search_engine_id", google_cx.strip())
            st.success("Integration settings saved.")

        st.divider()

    # Change password
    st.markdown("#### 🔑 Change Password")
    with st.form("change_password"):
        old_pwd  = st.text_input("Current Password",     type="password")
        new_pwd  = st.text_input("New Password",         type="password")
        new_pwd2 = st.text_input("Confirm New Password", type="password")
        change_btn = st.form_submit_button("Update Password", use_container_width=True)

    if change_btn:
        user     = get_user_by_username(username)
        old_hash = hashlib.sha256(old_pwd.strip().lower().encode()).hexdigest()
        if not user or user["password_hash"] != old_hash:
            st.error("Current password is incorrect.")
        elif new_pwd != new_pwd2:
            st.error("New passwords do not match.")
        elif len(new_pwd) < 4:
            st.error("New password must be at least 4 characters.")
        else:
            new_hash = hashlib.sha256(new_pwd.strip().lower().encode()).hexdigest()
            conn = get_connection()
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (new_hash, user_id))
            conn.commit(); conn.close()
            st.success("✅ Password updated successfully.")

    st.divider()

    # Security question
    st.markdown("#### 🔒 Security Question")
    st.markdown(
        "Set a security question so you can reset your password from the login screen. "
        "Your answer is stored securely and is **not** case-sensitive."
    )

    user_row  = get_user_by_username(username)
    current_q = user_row["security_question"] if user_row else None
    if current_q:
        st.success(f"✅ Security question is set: *{current_q}*")
    else:
        st.warning("⚠️ No security question set.")

    with st.form("security_question_form"):
        chosen_q = st.selectbox(
            "Choose a security question", options=SECURITY_QUESTIONS,
            index=SECURITY_QUESTIONS.index(current_q)
            if current_q in SECURITY_QUESTIONS else 0,
        )
        sec_answer  = st.text_input("Your answer",        type="password")
        sec_answer2 = st.text_input("Confirm your answer", type="password")
        save_sq = st.form_submit_button("💾 Save Security Question",
                                         use_container_width=True)

    if save_sq:
        if sec_answer != sec_answer2:
            st.error("Answers do not match.")
        else:
            ok, msg = save_security_question(user_id, chosen_q, sec_answer)
            if ok:
                st.success(f"✅ {msg}"); st.rerun()
            else:
                st.error(msg)

    st.divider()

    # Danger zone
    st.markdown("#### ⚠️ Danger Zone")
    if st.checkbox("I want to clear all my score history for ALL courses"):
        if st.button("🗑 Delete All My Score History", type="secondary"):
            conn = get_connection()
            conn.execute(
                "DELETE FROM user_answers WHERE attempt_id IN "
                "(SELECT id FROM exam_attempts WHERE user_id = ?)", (user_id,)
            )
            conn.execute("DELETE FROM exam_attempts WHERE user_id = ?",  (user_id,))
            conn.execute("DELETE FROM mistake_journal WHERE user_id = ?", (user_id,))
            conn.commit(); conn.close()
            st.success("Score history cleared.")

# ── Backup ────────────────────────────────────────────────────────────────────
with tab_backup:
    st.markdown("### 💾 Database Backup")
    st.markdown(
        "Download a copy of the SQLite database. "
        "Keep it safe — it contains all your courses, questions, and scores."
    )

    try:
        with open(str(DB_PATH), "rb") as f:
            db_bytes = f.read()
        st.download_button(
            "⬇️ Download lsat_app.db",
            data=db_bytes,
            file_name="lsat_app.db",
            mime="application/octet-stream",
            use_container_width=True,
        )
        size_kb = os.path.getsize(str(DB_PATH)) // 1024
        st.caption(f"Database size: {size_kb} KB  ·  Path: {DB_PATH}")
    except FileNotFoundError:
        st.warning("Database file not found.")

    st.divider()
    st.markdown("### ♻️ Restore from Backup")
    st.warning("⚠️ This will **replace** the current database. All current data will be lost.")
    restore_file = st.file_uploader("Upload lsat_app.db", type=["db"])
    if restore_file:
        if st.button("♻️ Restore Database", type="secondary"):
            with open(str(DB_PATH), "wb") as f:
                f.write(restore_file.read())
            st.success("Database restored. Please refresh the app.")
