"""
pages/10_Settings.py — Study preferences, account settings, and backup.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import sqlite3
import hashlib

from src.app_status import (
    backup_receipt,
    create_database_backup,
    deployment_caption,
    format_local_timestamp,
    get_deployment_status,
)

from src.auth     import require_login
from src.utils    import page_header, sidebar_nav, get_effective_admin, DIFFICULTY_LABELS
from src.database import (
    get_all_settings, set_setting, get_connection, DB_PATH,
    get_app_settings, set_app_setting,
)
from src.email_notifications import (
    EMAIL_NOTIFICATIONS_KEY,
    REQUIRED_SMTP_FIELDS,
    SMTP_SETTING_KEYS,
    TEST_START_COUNT_KEY,
    USER_EMAIL_KEY,
)
from src.professional_specialty import (
    DEFAULT_SPECIALTY,
    PROFESSIONAL_SPECIALTY_SETTING,
    normalize_specialty,
    specialty_label,
)
from src.exam_engine import persist_current_exam

st.set_page_config(page_title="Settings · StudyForge", page_icon="⚙️", layout="wide")

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)
page_header("⚙️ Settings", "Configure learning preferences, timing, and your account")

settings = get_all_settings(user_id)
real_admin, admin = get_effective_admin(user_id)

tab_general, tab_learning, tab_hard, tab_account, tab_backup = st.tabs(
    ["🎛 General", "💼 Learning", "⚡ Hard Mode", "👤 Account", "💾 Backup"]
)

# ── General settings ──────────────────────────────────────────────────────────
with tab_general:
    st.markdown("### General Settings")
    with st.expander("Phone access"):
        from src.mobile_access import PUBLIC_APP_URL, phone_links
        from src.desktop_publisher import is_local_publish_session
        from src.remote_phone_access import (
            PhoneAccessError, connect_ngrok, live_phone_url, ngrok_is_configured,
            phone_access_password, start_live_phone_access, stop_live_phone_access,
        )
        phone_link, hostname_link = phone_links()
        live_url = live_phone_url() if is_local_publish_session(st.context.headers) else ""
        if live_url:
            st.success("Live phone access is on. This link uses the same app and study records as this computer, even away from home Wi-Fi.")
            st.link_button("Open the live desktop app on your phone", live_url)
            st.code(live_url, language=None)
            st.caption("Keep this computer on, awake, and connected to the internet.")
            if st.button("Show phone access password", key="show_phone_access_password"):
                st.write("Username: `studyforge`")
                st.code(phone_access_password(), language=None)
            if real_admin and admin and st.button("Turn off live phone access", key="stop_live_phone_access"):
                try:
                    stop_live_phone_access()
                    st.rerun()
                except PhoneAccessError as exc:
                    st.error(str(exc))
        else:
            st.info("The Streamlit Cloud link has its own saved data. For the same mocks, courses, scores, and mistakes anywhere, turn on live phone access to this computer.")
            if real_admin and admin and is_local_publish_session(st.context.headers):
                if not ngrok_is_configured():
                    st.link_button("Open ngrok account setup", "https://dashboard.ngrok.com/get-started/your-authtoken")
                    token = st.text_input("ngrok authtoken", type="password", key="ngrok_authtoken")
                    if st.button("Connect ngrok", key="connect_ngrok"):
                        try:
                            connect_ngrok(token)
                            del st.session_state["ngrok_authtoken"]
                            st.rerun()
                        except PhoneAccessError as exc:
                            st.error(str(exc))
                elif st.button("Start live phone access", key="start_live_phone_access", type="primary"):
                    try:
                        with st.spinner("Starting a secure phone link..."):
                            start_live_phone_access()
                        st.rerun()
                    except PhoneAccessError as exc:
                        st.error(str(exc))
        st.markdown("**Separate Streamlit Cloud copy**")
        st.link_button("Open the separate online app", PUBLIC_APP_URL)
        st.code(PUBLIC_APP_URL, language=None)
        st.caption("Publish code update changes this Streamlit Cloud copy's program, but does not copy the desktop study database or uploads.")
        st.markdown("**Home Wi-Fi link to this computer**")
        st.caption("Connect your phone to this computer's home Wi-Fi. Keep the computer on and awake.")
        if phone_link:
            st.link_button("Open StudyForge on your phone", phone_link)
            st.code(phone_link, language=None)
        st.caption("Alternative link (if your network supports computer names):")
        st.code(hostname_link, language=None)
        st.caption("On your phone, use Safari's Share → Add to Home Screen or Chrome's menu → Add to Home screen.")
    if real_admin and admin:
        from src.desktop_publisher import is_local_publish_session, render_publish_controls

        if is_local_publish_session(st.context.headers):
            with st.expander("Publish code to separate Streamlit Cloud app", expanded=False):
                render_publish_controls()
        else:
            st.caption("To publish code updates, open Settings in the desktop StudyForge app on this computer.")
    from src.study_progress import METHODS, preferences
    progress_prefs = preferences(settings)
    with st.expander("Progress colors"):
        with st.form("progress_colors"):
            progress_method = st.selectbox("Score used for colors", list(METHODS),
                index=list(METHODS).index(progress_prefs["method"]), format_func=METHODS.get, key="progress_method_input")
            st.caption("The last 3 sessions balance recent improvement with stability. Averages are weighted by questions answered. Only completed sessions count.")
            progress_yellow = st.number_input("Yellow starts at (%)", 0, 99, progress_prefs["yellow"], key="progress_yellow_input")
            progress_green = st.number_input("Green starts at (%)", 1, 100, progress_prefs["green"], key="progress_green_input")
            st.caption("Below yellow is red. No history is gray. Review-window activity is tracked separately from your score.")
            save_progress = st.form_submit_button("Save Progress Colors")
        if save_progress:
            if progress_yellow >= progress_green:
                st.error("Green must start above yellow.")
            else:
                set_setting(user_id, "progress_method", progress_method)
                set_setting(user_id, "progress_yellow", str(progress_yellow))
                set_setting(user_id, "progress_green", str(progress_green))
                st.success("Progress colors saved across courses and modules.")

    with st.form("general_settings"):
        sec_time = st.slider(
            "Default Section Time (minutes)",
            min_value=5, max_value=120,
            value=int(settings.get("section_time_minutes", "35")),
            help="Used for Timed Exam when hard mode is off.",
        )
        question_time = st.number_input(
            "Default Time Per Question (seconds)",
            min_value=15,
            max_value=600,
            value=int(settings.get("question_time_seconds", "120")),
            step=5,
            help=(
                "Used as the default per-question timer in Practice Mode. "
                "You can still adjust it during an active practice session."
            ),
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
        st.markdown("#### Question behavior")
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
        auto_submit_answers = st.toggle(
            "Practice Mode: submit multiple-choice answers on selection",
            value=settings.get("auto_submit_answers", "false") == "true",
            help=(
                "Your first option click is submitted immediately, shows whether it "
                "was right or wrong, and replaces Submit Answer with Next Question."
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
        set_setting(user_id, "question_time_seconds", str(question_time))
        set_setting(user_id, "min_difficulty",       str(diff_range[0]))
        set_setting(user_id, "max_difficulty",       str(diff_range[1]))
        set_setting(user_id, "show_explanations",    show_exp)
        set_setting(
            user_id,
            "auto_submit_answers",
            "true" if auto_submit_answers else "false",
        )
        set_setting(user_id, "question_mix",         q_mix)
        if (
            st.session_state.get("exam_active")
            and st.session_state.get("exam_mode") == "practice"
            and st.session_state.get("practice_timer_enabled")
        ):
            st.session_state["practice_timer_seconds"] = int(question_time)
            st.session_state["practice_setup_timer_seconds"] = int(question_time)
            st.session_state["exam_time_limit"] = int(question_time)
            st.session_state["exam_timer_visible"] = True
            persist_current_exam(user_id)
        st.success("General settings saved.")

# ── Learning preferences ────────────────────────────────────────────────────
with tab_learning:
    st.markdown("### Learning Preferences")
    st.markdown(
        "Choose the default question lens for Practice Mode. Manage the shared lens list "
        "in Question Bank Manager → Manage Questions → Lenses."
    )
    from src.question_lenses import get_lenses
    lens_options = list(get_lenses())
    with st.form("learning_preferences"):
        current_specialty = normalize_specialty(
            settings.get(PROFESSIONAL_SPECIALTY_SETTING, DEFAULT_SPECIALTY)
        )
        professional_specialty = st.selectbox(
            "Default question lens",
            options=lens_options,
            index=lens_options.index(current_specialty),
            format_func=specialty_label,
            help=(
                "This is preselected when you start a new Practice Mode session. "
                "You can override it for an individual session."
            ),
        )
        save_learning = st.form_submit_button(
            "💾 Save Learning Preferences",
            use_container_width=True,
        )

    if save_learning:
        set_setting(
            user_id,
            PROFESSIONAL_SPECIALTY_SETTING,
            normalize_specialty(professional_specialty),
        )
        st.session_state["practice_professional_specialty"] = normalize_specialty(
            professional_specialty
        )
        st.session_state["practice_question_lens"] = normalize_specialty(professional_specialty)
        st.success(
            f"Default question lens saved as {specialty_label(professional_specialty)}."
        )

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

    if admin:
        from src.offline_email import render_mailbox_settings
        render_mailbox_settings()
        st.markdown("#### Email Delivery")
        st.caption(
            "These app-wide SMTP settings power exam-start emails. "
            "Users only control their own recipient address and notification toggle."
        )
        email_settings = get_app_settings(SMTP_SETTING_KEYS)
        missing_smtp = [
            label
            for setting_key, label in {
                "smtp_host": REQUIRED_SMTP_FIELDS["host"],
                "smtp_port": REQUIRED_SMTP_FIELDS["port"],
                "smtp_from_email": REQUIRED_SMTP_FIELDS["from_email"],
            }.items()
            if not str(email_settings.get(setting_key) or "").strip()
        ]
        if missing_smtp:
            st.warning(
                "Email delivery is not ready. Missing: "
                + ", ".join(missing_smtp)
                + "."
            )
        with st.form("smtp_email_settings"):
            smtp_host = st.text_input(
                "SMTP host",
                value=email_settings.get("smtp_host", ""),
                placeholder="smtp.gmail.com",
            )
            smtp_port = st.text_input(
                "SMTP port",
                value=email_settings.get("smtp_port", "587") or "587",
            )
            smtp_username = st.text_input(
                "SMTP username",
                value=email_settings.get("smtp_username", ""),
            )
            smtp_password = st.text_input(
                "SMTP password",
                value=email_settings.get("smtp_password", ""),
                type="password",
            )
            smtp_from = st.text_input(
                "From email",
                value=email_settings.get("smtp_from_email", ""),
                placeholder="notifications@studyforge.local",
            )
            smtp_tls = st.toggle(
                "Use TLS",
                value=(email_settings.get("smtp_use_tls", "true") or "true") == "true",
            )
            save_smtp = st.form_submit_button(
                "Save Email Delivery Settings",
                use_container_width=True,
            )

        if save_smtp:
            set_app_setting("smtp_host", smtp_host.strip())
            set_app_setting("smtp_port", smtp_port.strip() or "587")
            set_app_setting("smtp_username", smtp_username.strip())
            set_app_setting("smtp_password", smtp_password)
            set_app_setting("smtp_from_email", smtp_from.strip())
            set_app_setting("smtp_use_tls", "true" if smtp_tls else "false")
            st.success("Email delivery settings saved.")

        st.divider()

    st.markdown("#### Exam Email Notifications")
    current_email = settings.get(USER_EMAIL_KEY, "")
    current_enabled = settings.get(EMAIL_NOTIFICATIONS_KEY, "false") == "true"
    current_count = settings.get(TEST_START_COUNT_KEY, "0")
    with st.form("exam_email_notifications"):
        profile_email = st.text_input(
            "Email on file",
            value=current_email,
            placeholder="you@example.com",
            help="StudyForge sends exam-start notifications to this address.",
        )
        notifications_on = st.toggle(
            "Email me when an exam starts",
            value=current_enabled,
        )
        st.caption(f"Current test count: {current_count}")
        save_email_notifications = st.form_submit_button(
            "Save Exam Email Settings",
            use_container_width=True,
        )

    if save_email_notifications:
        cleaned_email = profile_email.strip()
        if cleaned_email and ("@" not in cleaned_email or "." not in cleaned_email.split("@")[-1]):
            st.error("Enter a valid email address, or leave it blank.")
        else:
            set_setting(user_id, USER_EMAIL_KEY, cleaned_email)
            set_setting(user_id, EMAIL_NOTIFICATIONS_KEY, "true" if notifications_on else "false")
            st.success("Exam email settings saved.")
            st.rerun()

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
        "Download a consistent copy of the SQLite database. "
        "The dated filename and receipt record exactly when it was prepared."
    )

    try:
        if "prepared_database_backup" not in st.session_state:
            st.session_state.prepared_database_backup = create_database_backup(DB_PATH)
        if st.button("Prepare a fresh backup", use_container_width=True):
            st.session_state.prepared_database_backup = create_database_backup(DB_PATH)

        prepared_backup = st.session_state.prepared_database_backup
        deployment = get_deployment_status()

        st.info(deployment_caption(deployment))
        created_label = format_local_timestamp(
            prepared_backup.created_at, include_seconds=True
        )
        activity_label = format_local_timestamp(
            prepared_backup.latest_activity_at, include_seconds=True
        )
        st.markdown(f"**Backup prepared:** {created_label}")
        st.markdown(f"**Latest database activity:** {activity_label}")

        st.download_button(
            "⬇️ Download dated database backup",
            data=prepared_backup.data,
            file_name=prepared_backup.database_filename,
            mime="application/octet-stream",
            use_container_width=True,
        )
        st.download_button(
            "Download backup receipt",
            data=backup_receipt(prepared_backup, deployment),
            file_name=prepared_backup.receipt_filename,
            mime="text/plain",
            use_container_width=True,
        )
        size_kb = len(prepared_backup.data) // 1024
        st.caption(
            f"Database size: {size_kb:,} KB · SHA-256: {prepared_backup.sha256}"
        )
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
            st.session_state.pop("prepared_database_backup", None)
            st.success("Database restored. Please refresh the app.")
