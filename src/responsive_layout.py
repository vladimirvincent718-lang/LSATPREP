"""
src/responsive_layout.py — Responsive Layout Manager data layer.

Provides:
  - DB schema (responsive_configs, responsive_history tables)
  - CRUD for layout configurations
  - CSS generator from JSON config
  - Version history management
  - Streamlit CSS injection helper

Architecture
────────────
A "layout config" is a JSON document with two top-level keys:

    {
      "breakpoints": {
        "desktop": 1200,
        "laptop":  992,
        "tablet":  768,
        "mobile":  480
      },
      "components": {
        "<selector>": {
          "desktop": { "<css-property>": "<value>", ... },
          "laptop":  { ... },
          "tablet":  { ... },
          "mobile":  { ... }
        },
        ...
      }
    }

The `generate_css()` function converts that JSON into a single <style> block
ready for st.markdown(unsafe_allow_html=True).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from src.database import get_connection

# ── Default component catalogue ───────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "breakpoints": {
        "desktop": 1200,
        "laptop":  992,
        "tablet":  768,
        "mobile":  480,
    },
    "components": {
        # ── Sidebar ──────────────────────────────────────────────────────────
        "[data-testid='stSidebar']": {
            "label":   "Sidebar Navigation",
            "group":   "Layout",
            "desktop": {"min-width": "280px", "max-width": "280px"},
            "laptop":  {"min-width": "240px", "max-width": "240px"},
            "tablet":  {"min-width": "200px", "max-width": "200px"},
            "mobile":  {"min-width": "0",     "max-width": "0",
                        "transform": "translateX(-300px)",
                        "visibility": "hidden"},
        },
        # ── Main content wrapper ─────────────────────────────────────────────
        ".main .block-container": {
            "label":   "Page Container",
            "group":   "Layout",
            "desktop": {"max-width": "1220px", "padding": "2.1rem 2.6rem 4.5rem"},
            "laptop":  {"max-width": "100%",   "padding": "1.6rem 2rem 4rem"},
            "tablet":  {"padding": "1.25rem 1.35rem 3.5rem"},
            "mobile":  {"padding": "1rem 0.9rem 3rem"},
        },
        # ── Page headings (h1/h2) ────────────────────────────────────────────
        ".main h1, .main h2": {
            "label":   "Page Headers",
            "group":   "Typography",
            "desktop": {"font-size": "2rem", "margin-bottom": "0.55rem", "font-weight": "800"},
            "laptop":  {"font-size": "1.75rem"},
            "tablet":  {"font-size": "1.5rem"},
            "mobile":  {"font-size": "1.28rem", "margin-bottom": "0.25rem"},
        },
        # ── Subheadings (h3) ─────────────────────────────────────────────────
        ".main h3": {
            "label":   "Section Headers",
            "group":   "Typography",
            "desktop": {"font-size": "1.25rem"},
            "tablet":  {"font-size": "1.1rem"},
            "mobile":  {"font-size": "1rem"},
        },
        # ── Buttons ──────────────────────────────────────────────────────────
        ".stButton > button": {
            "label":   "Buttons",
            "group":   "Controls",
            "desktop": {"min-height": "40px", "font-size": "14px",
                        "padding": "0.5rem 0.85rem", "border-radius": "8px"},
            "tablet":  {"min-height": "40px"},
            "mobile":  {"min-height": "44px", "font-size": "15px",
                        "padding": "0.5rem 1rem", "width": "100%"},
        },
        # ── Metric cards ─────────────────────────────────────────────────────
        "[data-testid='stMetric']": {
            "label":   "KPI Metric Cards",
            "group":   "Cards",
            "desktop": {"padding": "1rem", "font-size": "14px", "border-radius": "8px"},
            "tablet":  {"padding": "0.8rem"},
            "mobile":  {"padding": "0.75rem", "font-size": "12px"},
        },
        # ── Column grid ──────────────────────────────────────────────────────
        "[data-testid='column']": {
            "label":   "Column Layout",
            "group":   "Layout",
            "desktop": {"flex": "1 1 0%"},
            "tablet":  {"flex": "1 1 45%"},
            "mobile":  {"flex": "1 1 100%", "max-width": "100%"},
        },
        # ── Tabs ─────────────────────────────────────────────────────────────
        "[data-testid='stTabBar']": {
            "label":   "Tab Bar",
            "group":   "Controls",
            "desktop": {"font-size": "14px", "gap": "0.5rem"},
            "tablet":  {"font-size": "13px", "gap": "0.25rem"},
            "mobile":  {"font-size": "12px", "overflow-x": "auto",
                        "white-space": "nowrap", "gap": "0.1rem"},
        },
        # ── Data tables ──────────────────────────────────────────────────────
        "[data-testid='stDataFrame']": {
            "label":   "Data Tables",
            "group":   "Data",
            "desktop": {"width": "100%"},
            "tablet":  {"overflow-x": "auto", "display": "block"},
            "mobile":  {"overflow-x": "auto", "display": "block",
                        "font-size": "12px"},
        },
        # ── Select/Input controls ─────────────────────────────────────────────
        ".stSelectbox, .stTextInput, .stTextArea": {
            "label":   "Form Controls",
            "group":   "Controls",
            "desktop": {"font-size": "14px"},
            "tablet":  {"font-size": "15px"},
            "mobile":  {"font-size": "16px"},   # Prevents iOS auto-zoom
        },
        # ── Alert / info boxes ────────────────────────────────────────────────
        ".stAlert": {
            "label":   "Alert / Info Boxes",
            "group":   "Cards",
            "desktop": {"padding": "0.75rem 1rem", "font-size": "14px", "border-radius": "8px"},
            "mobile":  {"padding": "0.6rem 0.75rem", "font-size": "13px"},
        },
    },
}


# ── Database helpers ──────────────────────────────────────────────────────────

def init_responsive_tables() -> None:
    """Create responsive layout tables (idempotent)."""
    conn = get_connection()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS responsive_configs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL DEFAULT 'Default',
        config_json TEXT    NOT NULL,
        is_active   INTEGER NOT NULL DEFAULT 0,
        is_draft    INTEGER NOT NULL DEFAULT 1,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS responsive_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        config_id   INTEGER NOT NULL REFERENCES responsive_configs(id),
        config_json TEXT    NOT NULL,
        label       TEXT    NOT NULL DEFAULT '',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    _seed_default_if_empty(conn)


def _seed_default_if_empty(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) FROM responsive_configs").fetchone()
    if row[0] == 0:
        conn.execute(
            "INSERT INTO responsive_configs (name, config_json, is_active, is_draft) VALUES (?, ?, 1, 0)",
            ("Default", json.dumps(DEFAULT_CONFIG)),
        )
        conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_active_config() -> dict[str, Any]:
    conn = get_connection()
    row = conn.execute(
        "SELECT config_json FROM responsive_configs WHERE is_active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        return json.loads(row[0])
    return DEFAULT_CONFIG


def get_all_configs() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, is_active, is_draft, updated_at FROM responsive_configs ORDER BY id DESC"
    ).fetchall()
    return [{"id": r[0], "name": r[1], "is_active": bool(r[2]),
             "is_draft": bool(r[3]), "updated_at": r[4]} for r in rows]


def get_config_by_id(config_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT config_json FROM responsive_configs WHERE id=?", (config_id,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def save_draft(config: dict[str, Any], config_id: int | None = None,
               name: str = "Draft") -> int:
    """Save (or update) a draft config. Returns the config id."""
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    cfg_str = json.dumps(config)
    if config_id:
        conn.execute(
            "UPDATE responsive_configs SET config_json=?, name=?, updated_at=? WHERE id=?",
            (cfg_str, name, now, config_id),
        )
        conn.commit()
        return config_id
    else:
        cur = conn.execute(
            "INSERT INTO responsive_configs (name, config_json, is_active, is_draft, updated_at) "
            "VALUES (?, ?, 0, 1, ?)",
            (name, cfg_str, now),
        )
        conn.commit()
        return cur.lastrowid


def publish_config(config_id: int) -> None:
    """Publish a config: deactivate all others, activate this one."""
    conn = get_connection()
    conn.execute("UPDATE responsive_configs SET is_active=0")
    conn.execute(
        "UPDATE responsive_configs SET is_active=1, is_draft=0 WHERE id=?",
        (config_id,),
    )
    conn.commit()


def snapshot_history(config_id: int, label: str = "") -> None:
    """Save a version-history snapshot before a destructive change."""
    conn = get_connection()
    row = conn.execute(
        "SELECT config_json FROM responsive_configs WHERE id=?", (config_id,)
    ).fetchone()
    if row:
        conn.execute(
            "INSERT INTO responsive_history (config_id, config_json, label) VALUES (?, ?, ?)",
            (config_id, row[0], label or datetime.utcnow().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()


def get_history(config_id: int, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, label, created_at FROM responsive_history "
        "WHERE config_id=? ORDER BY id DESC LIMIT ?",
        (config_id, limit),
    ).fetchall()
    return [{"id": r[0], "label": r[1], "created_at": r[2]} for r in rows]


def restore_from_history(history_id: int, config_id: int) -> None:
    conn = get_connection()
    row = conn.execute(
        "SELECT config_json FROM responsive_history WHERE id=?", (history_id,)
    ).fetchone()
    if row:
        snapshot_history(config_id, label="(before restore)")
        conn.execute(
            "UPDATE responsive_configs SET config_json=?, updated_at=? WHERE id=?",
            (row[0], datetime.utcnow().isoformat(), config_id),
        )
        conn.commit()


def reset_to_defaults(config_id: int) -> None:
    snapshot_history(config_id, label="(before reset)")
    conn = get_connection()
    conn.execute(
        "UPDATE responsive_configs SET config_json=? WHERE id=?",
        (json.dumps(DEFAULT_CONFIG), config_id),
    )
    conn.commit()


# ── CSS Generator ─────────────────────────────────────────────────────────────

def generate_css(config: dict[str, Any]) -> str:
    """
    Convert a layout config dict into a complete <style> block.

    Generates:
      1. Base (desktop-first) styles for each component
      2. Laptop media query
      3. Tablet media query
      4. Mobile media query
      5. Streamlit-specific overrides for touch targets
    """
    bp = config.get("breakpoints", DEFAULT_CONFIG["breakpoints"])
    components = config.get("components", {})

    parts: list[str] = ["<style>\n/* StudyForge Responsive Layout Manager — auto-generated */\n"]

    # ── Desktop / base styles ─────────────────────────────────────────────────
    for selector, settings in components.items():
        props = settings.get("desktop", {})
        if props:
            rules = _props_to_css(props)
            if rules:
                parts.append(f"{selector} {{\n{rules}}}\n")

    # ── Laptop ────────────────────────────────────────────────────────────────
    laptop_rules = _build_mq_block(components, "laptop")
    if laptop_rules:
        parts.append(f"@media (max-width: {bp.get('laptop', 992) - 1}px) {{\n{laptop_rules}}}\n")

    # ── Tablet ────────────────────────────────────────────────────────────────
    tablet_rules = _build_mq_block(components, "tablet")
    if tablet_rules:
        parts.append(f"@media (max-width: {bp.get('tablet', 768) - 1}px) {{\n{tablet_rules}}}\n")

    # ── Mobile ────────────────────────────────────────────────────────────────
    mobile_rules = _build_mq_block(components, "mobile")
    if mobile_rules:
        parts.append(f"@media (max-width: {bp.get('mobile', 480) - 1}px) {{\n{mobile_rules}}}\n")

    parts.append("</style>")
    return "\n".join(parts)


def generate_preview_css(config: dict[str, Any]) -> str:
    """
    Generate CSS for the in-admin mock preview.

    The live app uses Streamlit selectors, but the preview is a lightweight
    static mockup with sf-* classes. This duplicates each matching rule onto a
    preview selector so edits are visible immediately while preserving the real
    published selectors.
    """
    mapped = json.loads(json.dumps(config))
    mapped_components: dict[str, Any] = {}

    for selector, settings in config.get("components", {}).items():
        preview_selector = _preview_selector_for(selector)
        mapped_components[selector] = settings
        if preview_selector and preview_selector != selector:
            mapped_components[preview_selector] = settings

    mapped["components"] = mapped_components
    return generate_css(mapped)


def _preview_selector_for(selector: str) -> str | None:
    preview_selectors = {
        "[data-testid='stSidebar']": ".sf-sidebar[data-testid='stSidebar']",
        ".main .block-container": ".sf-main",
        ".main h1, .main h2": ".sf-page-title",
        ".main h3": ".sf-section-title",
        ".stButton > button": ".sf-btn",
        "[data-testid='stMetric']": ".sf-kpi-card[data-testid='stMetric']",
        "[data-testid='column']": ".sf-kpi-card",
        "[data-testid='stTabBar']": ".sf-tabs[data-testid='stTabBar'], .sf-tab",
        "[data-testid='stDataFrame']": ".sf-table-header, .sf-table-row",
        ".stSelectbox, .stTextInput, .stTextArea": ".sf-form-control",
        ".stAlert": ".sf-info-box.stAlert",
    }
    return preview_selectors.get(selector)


def _props_to_css(props: dict) -> str:
    return "".join(f"    {k}: {v} !important;\n" for k, v in props.items()
                   if k not in ("label", "group"))


def _build_mq_block(components: dict, breakpoint: str) -> str:
    block = ""
    for selector, settings in components.items():
        props = settings.get(breakpoint, {})
        if props:
            rules = _props_to_css(props)
            if rules:
                block += f"  {selector} {{\n"
                # indent each rule one more level for media query
                block += "".join(f"  {line}" for line in rules.splitlines(keepends=True))
                block += "  }\n"
    return block


# ── Streamlit injection helper ────────────────────────────────────────────────

def inject_responsive_css() -> None:
    """
    Call once per page (e.g., from sidebar_nav) to inject the active
    responsive CSS into the Streamlit app.
    """
    import streamlit as st

    try:
        init_responsive_tables()
        config = get_active_config()
        css = generate_css(config)
        st.markdown(css, unsafe_allow_html=True)
    except Exception:
        pass  # Never crash the app over CSS
