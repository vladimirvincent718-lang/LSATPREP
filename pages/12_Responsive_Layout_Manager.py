"""
pages/12_Responsive_Layout_Manager.py — Visual Responsive Layout Editor.

Admin-only page. Provides:
  • Live device preview (phone/tablet/desktop frames)
  • Per-breakpoint CSS property editor for every StudyForge component
  • Breakpoint width editor
  • Save draft / Publish / Reset / Version history
  • Responsive debug tools (overflow, touch-target, overlap warnings)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import streamlit as st
import streamlit.components.v1 as components

from src.auth             import require_login
from src.utils            import page_header, sidebar_nav, get_effective_admin
from src.responsive_layout import (
    init_responsive_tables,
    get_active_config,
    get_all_configs,
    get_config_by_id,
    save_draft,
    publish_config,
    snapshot_history,
    get_history,
    restore_from_history,
    reset_to_defaults,
    generate_css,
    generate_preview_css,
    DEFAULT_CONFIG,
)

st.set_page_config(
    page_title="Responsive Layout Manager · StudyForge",
    page_icon="📐",
    layout="wide",
)

user_id  = require_login()
username = st.session_state.get("username", "")
sidebar_nav(username)

real_admin, eff_admin = get_effective_admin(user_id)
if not real_admin:
    st.error("🔒 Admin access required.")
    st.stop()

init_responsive_tables()

page_header("📐 Responsive Layout Manager",
            "Visual mobile & tablet layout editor — preview, edit, publish responsive CSS")

# ════════════════════════════════════════════════════════════════════════════════
# Session-state initialisation
# ════════════════════════════════════════════════════════════════════════════════

def _init_state():
    if "rlm_config" not in st.session_state:
        st.session_state["rlm_config"]    = get_active_config()
    if "rlm_config_id" not in st.session_state:
        all_cfgs = get_all_configs()
        active = next((c for c in all_cfgs if c["is_active"]), None)
        st.session_state["rlm_config_id"] = active["id"] if active else None
    if "rlm_device" not in st.session_state:
        st.session_state["rlm_device"] = "iphone14"
    if "rlm_breakpoint" not in st.session_state:
        st.session_state["rlm_breakpoint"] = "mobile"
    if "rlm_component" not in st.session_state:
        st.session_state["rlm_component"] = list(
            st.session_state["rlm_config"]["components"].keys())[0]
    if "rlm_undo_stack" not in st.session_state:
        st.session_state["rlm_undo_stack"] = []
    if "rlm_redo_stack" not in st.session_state:
        st.session_state["rlm_redo_stack"] = []

_init_state()

cfg: dict  = st.session_state["rlm_config"]
cfg_id     = st.session_state["rlm_config_id"]

# ════════════════════════════════════════════════════════════════════════════════
# Undo / Redo helpers
# ════════════════════════════════════════════════════════════════════════════════

def _push_undo():
    st.session_state["rlm_undo_stack"].append(json.dumps(st.session_state["rlm_config"]))
    st.session_state["rlm_redo_stack"].clear()
    if len(st.session_state["rlm_undo_stack"]) > 50:
        st.session_state["rlm_undo_stack"].pop(0)

def _undo():
    if st.session_state["rlm_undo_stack"]:
        st.session_state["rlm_redo_stack"].append(
            json.dumps(st.session_state["rlm_config"])
        )
        st.session_state["rlm_config"] = json.loads(
            st.session_state["rlm_undo_stack"].pop()
        )

def _redo():
    if st.session_state["rlm_redo_stack"]:
        st.session_state["rlm_undo_stack"].append(
            json.dumps(st.session_state["rlm_config"])
        )
        st.session_state["rlm_config"] = json.loads(
            st.session_state["rlm_redo_stack"].pop()
        )


def _parse_css_number(value: str, default_unit: str = "px") -> tuple[float | None, str]:
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*(px|rem|em|%|vh|vw)?\s*$", str(value or ""))
    if not match:
        return None, default_unit
    return float(match.group(1)), match.group(2) or default_unit


def _format_css_number(value: float, unit: str) -> str:
    if abs(value - round(value)) < 0.001:
        return f"{int(round(value))}{unit}"
    return f"{value:.2f}".rstrip("0").rstrip(".") + unit


def _slider_spec(prop: str) -> tuple[float, float, float, str] | None:
    specs = {
        "font-size": (8, 64, 1, "px"),
        "line-height": (0.8, 3, 0.05, ""),
        "letter-spacing": (-2, 8, 0.1, "px"),
        "padding": (0, 96, 1, "px"),
        "padding-top": (0, 96, 1, "px"),
        "padding-right": (0, 96, 1, "px"),
        "padding-bottom": (0, 96, 1, "px"),
        "padding-left": (0, 96, 1, "px"),
        "margin": (-48, 96, 1, "px"),
        "margin-top": (-48, 96, 1, "px"),
        "margin-right": (-48, 96, 1, "px"),
        "margin-bottom": (-48, 96, 1, "px"),
        "margin-left": (-48, 96, 1, "px"),
        "gap": (0, 64, 1, "px"),
        "width": (0, 100, 1, "%"),
        "min-width": (0, 640, 4, "px"),
        "max-width": (0, 1600, 10, "px"),
        "height": (0, 640, 4, "px"),
        "min-height": (0, 160, 1, "px"),
        "max-height": (0, 1000, 10, "px"),
        "border-radius": (0, 48, 1, "px"),
        "opacity": (0, 1, 0.05, ""),
        "order": (-10, 10, 1, ""),
    }
    return specs.get(prop)


def _value_control(prop: str, cur_val: str, key_base: str) -> str:
    spec = _slider_spec(prop)
    if not spec:
        return st.text_input(
            prop, value=cur_val, placeholder="e.g. 1rem, 100%, auto", key=f"{key_base}_text"
        )

    mn, mx, step, default_unit = spec
    parsed_value, parsed_unit = _parse_css_number(cur_val, default_unit)
    if parsed_value is None:
        return st.text_input(
            prop,
            value=cur_val,
            placeholder=f"e.g. {_format_css_number(mn, default_unit) if default_unit else mn}, 1rem, auto",
            key=f"{key_base}_text",
        )

    slider_value = parsed_value if parsed_value is not None else mn
    slider_value = min(max(slider_value, mn), mx)
    uses_float = any(isinstance(n, float) and not n.is_integer() for n in (mn, mx, step, slider_value))
    if uses_float:
        slider_min = float(mn)
        slider_max = float(mx)
        slider_step = float(step)
        slider_value = float(slider_value)
    else:
        slider_min = int(mn)
        slider_max = int(mx)
        slider_step = int(step)
        slider_value = int(round(slider_value))

    left, right = st.columns([3, 2])
    with left:
        new_number = st.slider(
            prop,
            min_value=slider_min,
            max_value=slider_max,
            value=slider_value,
            step=slider_step,
            key=f"{key_base}_slider",
        )
    with right:
        text_val = st.text_input(
            "Value",
            value=cur_val,
            placeholder=_format_css_number(new_number, parsed_unit),
            key=f"{key_base}_text",
            label_visibility="collapsed",
        )

    return text_val if text_val != cur_val else _format_css_number(new_number, parsed_unit)


# ════════════════════════════════════════════════════════════════════════════════
# Top toolbar — device selector + actions
# ════════════════════════════════════════════════════════════════════════════════

DEVICES = {
    "iphone_se":  {"label": "📱 iPhone SE",        "w": 375,  "h": 667,  "scale": 0.60},
    "iphone14":   {"label": "📱 iPhone 14",         "w": 390,  "h": 844,  "scale": 0.58},
    "iphone14pm": {"label": "📱 iPhone 14 Pro Max", "w": 430,  "h": 932,  "scale": 0.55},
    "android":    {"label": "🤖 Android (Pixel)",   "w": 412,  "h": 915,  "scale": 0.56},
    "ipad":       {"label": "📟 iPad",              "w": 768,  "h": 1024, "scale": 0.50},
    "ipad_pro":   {"label": "📟 iPad Pro 12.9\"",   "w": 1024, "h": 1366, "scale": 0.42},
    "laptop":     {"label": "💻 Laptop (1280px)",   "w": 1280, "h": 800,  "scale": 0.42},
    "desktop":    {"label": "🖥️ Desktop (1440px)",  "w": 1440, "h": 900,  "scale": 0.38},
}

toolbar_l, toolbar_r = st.columns([6, 4])

with toolbar_l:
    dev_keys   = list(DEVICES.keys())
    dev_labels = [DEVICES[k]["label"] for k in dev_keys]
    cur_dev_idx = dev_keys.index(st.session_state["rlm_device"])
    chosen = st.selectbox("🖥️ Preview Device",
                          options=dev_keys,
                          format_func=lambda k: DEVICES[k]["label"],
                          index=cur_dev_idx,
                          key="rlm_device_picker")
    st.session_state["rlm_device"] = chosen

with toolbar_r:
    ta, tb, tc, td, te = st.columns(5)
    with ta:
        if st.button("↩ Undo", use_container_width=True,
                     disabled=not st.session_state["rlm_undo_stack"]):
            _undo(); st.rerun()
    with tb:
        if st.button("↪ Redo", use_container_width=True,
                     disabled=not st.session_state["rlm_redo_stack"]):
            _redo(); st.rerun()
    with tc:
        if st.button("💾 Draft", use_container_width=True):
            new_id = save_draft(st.session_state["rlm_config"],
                                config_id=cfg_id, name="Draft")
            st.session_state["rlm_config_id"] = new_id
            st.success("Draft saved.")
    with td:
        if st.button("🚀 Publish", type="primary", use_container_width=True):
            if cfg_id:
                snapshot_history(cfg_id, label="(before publish)")
                save_draft(st.session_state["rlm_config"],
                           config_id=cfg_id, name="Published")
                publish_config(cfg_id)
                st.success("✅ Layout published and live on all pages!")
                st.session_state.pop("_rlm_css_injected", None)
                st.rerun()
    with te:
        if st.button("🔄 Reset", use_container_width=True):
            if st.session_state.get("_reset_confirm"):
                _push_undo()
                if cfg_id:
                    reset_to_defaults(cfg_id)
                st.session_state["rlm_config"] = get_active_config()
                st.session_state.pop("_reset_confirm", None)
                st.rerun()
            else:
                st.session_state["_reset_confirm"] = True
                st.warning("Click Reset again to confirm.")

st.divider()

# ════════════════════════════════════════════════════════════════════════════════
# Main layout: Preview (left) | Editor (right)
# ════════════════════════════════════════════════════════════════════════════════

col_preview, col_editor = st.columns([5, 4], gap="large")

# ────────────────────────────────────────────────────────────────────────────────
# LEFT: Device Preview
# ────────────────────────────────────────────────────────────────────────────────
with col_preview:
    dev = DEVICES[st.session_state["rlm_device"]]
    dw, dh, scale = dev["w"], dev["h"], dev["scale"]
    css_output = generate_preview_css(st.session_state["rlm_config"])
    # Strip the outer <style> tags — we'll embed them in the preview HTML
    css_inner = css_output.replace("<style>", "").replace("</style>", "").strip()

    # ── Build preview HTML ────────────────────────────────────────────────────
    preview_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: #0f0f23;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    padding: 20px 10px;
    gap: 12px;
  }}

  .device-meta {{
    color: rgba(255,255,255,0.5);
    font-size: 12px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }}

  /* ── Device shell ── */
  .device-shell {{
    position: relative;
    border-radius: 44px;
    background: #1c1c1e;
    padding: 12px 12px 16px;
    box-shadow:
      0 0 0 2px #3a3a3c,
      0 0 0 4px #1c1c1e,
      0 40px 80px rgba(0,0,0,0.7),
      inset 0 1px 0 rgba(255,255,255,0.08);
    width: {int(dw * scale) + 24}px;
    flex-shrink: 0;
  }}

  .device-shell.tablet-shell {{
    border-radius: 24px;
  }}

  .device-shell.laptop-shell,
  .device-shell.desktop-shell {{
    border-radius: 12px;
    padding: 8px 8px 4px;
  }}

  /* Notch (phones only) */
  .device-notch {{
    position: absolute;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    width: 120px;
    height: 28px;
    background: #1c1c1e;
    border-radius: 0 0 20px 20px;
    z-index: 10;
  }}

  /* Home indicator */
  .device-home {{
    width: 100px;
    height: 5px;
    background: rgba(255,255,255,0.25);
    border-radius: 3px;
    margin: 8px auto 0;
  }}

  /* Screen */
  .device-screen {{
    width: {int(dw * scale)}px;
    height: {int(dh * scale)}px;
    border-radius: 32px;
    overflow: hidden;
    background: #fff;
    position: relative;
  }}

  .device-shell.tablet-shell .device-screen {{ border-radius: 16px; }}
  .device-shell.laptop-shell .device-screen,
  .device-shell.desktop-shell .device-screen {{ border-radius: 6px; }}

  /* ── Scaled StudyForge mockup inside the screen ── */
  .sf-app {{
    width: {dw}px;
    height: {dh}px;
    transform: scale({scale});
    transform-origin: top left;
    background: #fff;
    display: flex;
    overflow: hidden;
  }}

  .sf-sidebar {{
    width: 280px;
    min-width: 280px;
    background: #f7f8fa;
    border-right: 1px solid #e5e7eb;
    padding: 20px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex-shrink: 0;
  }}

  .sf-sidebar-logo {{
    font-size: 18px;
    font-weight: 700;
    color: #1f2937;
    padding: 4px 8px;
    margin-bottom: 8px;
  }}

  .sf-sidebar-link {{
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 13px;
    color: #4b5563;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .sf-sidebar-link.active {{
    background: #eff6ff;
    color: #2563eb;
    font-weight: 600;
  }}

  .sf-main {{
    flex: 1;
    overflow-y: auto;
    padding: 20px 24px;
    background: #ffffff;
    min-width: 0;
  }}

  .sf-page-title {{
    font-size: 28px;
    font-weight: 700;
    color: #111827;
    margin-bottom: 4px;
  }}

  .sf-page-sub {{
    font-size: 13px;
    color: #6b7280;
    margin-bottom: 16px;
  }}

  .sf-divider {{
    height: 1px;
    background: #e5e7eb;
    margin: 12px 0;
  }}

  .sf-kpi-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-bottom: 16px;
  }}

  .sf-kpi-card {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 14px;
  }}

  .sf-kpi-label {{
    font-size: 11px;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
  }}

  .sf-kpi-value {{
    font-size: 22px;
    font-weight: 700;
    color: #111827;
  }}

  .sf-tabs {{
    display: flex;
    gap: 4px;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 16px;
  }}

  .sf-tab {{
    padding: 8px 14px;
    font-size: 13px;
    color: #6b7280;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    cursor: pointer;
    white-space: nowrap;
  }}

  .sf-tab.active {{
    color: #2563eb;
    border-bottom-color: #2563eb;
    font-weight: 600;
  }}

  .sf-btn-row {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 16px;
  }}

  .sf-btn {{
    padding: 8px 16px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
    border: 1px solid #d1d5db;
    background: #fff;
    color: #374151;
    cursor: pointer;
  }}

  .sf-btn.primary {{
    background: #2563eb;
    color: white;
    border-color: #2563eb;
  }}

  .sf-info-box {{
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 12px;
    color: #1d4ed8;
    margin-bottom: 12px;
  }}

  .sf-table-header {{
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 8px;
    padding: 8px 12px;
    background: #f3f4f6;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}

  .sf-table-row {{
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 8px;
    padding: 10px 12px;
    border-bottom: 1px solid #f3f4f6;
    font-size: 12px;
    color: #374151;
    align-items: center;
  }}

  .sf-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 99px;
    font-size: 10px;
    font-weight: 600;
  }}

  .sf-badge.green {{ background: #d1fae5; color: #065f46; }}
  .sf-badge.blue  {{ background: #dbeafe; color: #1e40af; }}
  .sf-badge.gray  {{ background: #f3f4f6; color: #6b7280; }}

  /* ── INJECTED USER CSS ── */
  {css_inner}
</style>
</head>
<body>

<div class="device-meta">{dev['label']} — {dw}×{dh}px @ {int(scale*100)}%</div>

<div class="device-shell {'tablet-shell' if dw >= 768 and dw < 1024 else 'laptop-shell' if dw >= 1024 else ''}">
  {'<div class="device-notch"></div>' if dw < 600 else ''}
  <div class="device-screen">
    <div class="sf-app">

      <!-- Sidebar -->
      <div class="sf-sidebar" data-testid="stSidebar">
        <div class="sf-sidebar-logo">🎓 StudyForge</div>
        <div class="sf-sidebar-link active">📊 Dashboard</div>
        <div class="sf-sidebar-link">📚 Courses</div>
        <div class="sf-sidebar-link">📖 Materials</div>
        <div class="sf-sidebar-link">🗂 Question Bank</div>
        <div class="sf-sidebar-link">✏️ Practice</div>
        <div class="sf-sidebar-link">⏱ Timed Exam</div>
        <div class="sf-sidebar-link">🔍 Mistakes</div>
        <div class="sf-sidebar-link">⚙️ Settings</div>
      </div>

      <!-- Main content -->
      <div class="sf-main main">
        <div class="sf-page-title">📊 Dashboard</div>
        <div class="sf-page-sub">Course: LSAT Master Class</div>
        <div class="sf-divider"></div>

        <!-- KPI Grid -->
        <div class="sf-kpi-grid" data-testid="column-grid">
          <div class="sf-kpi-card" data-testid="stMetric">
            <div class="sf-kpi-label">Questions in Bank</div>
            <div class="sf-kpi-value">284</div>
          </div>
          <div class="sf-kpi-card" data-testid="stMetric">
            <div class="sf-kpi-label">Sessions Done</div>
            <div class="sf-kpi-value">12</div>
          </div>
          <div class="sf-kpi-card" data-testid="stMetric">
            <div class="sf-kpi-label">Latest Score</div>
            <div class="sf-kpi-value">74%</div>
          </div>
        </div>

        <!-- Tabs -->
        <div class="sf-tabs" data-testid="stTabBar">
          <div class="sf-tab active">Score Trend</div>
          <div class="sf-tab">Weak Areas</div>
          <div class="sf-tab">By Type</div>
          <div class="sf-tab">History</div>
        </div>

        <!-- Info box -->
        <div class="sf-info-box stAlert">
          📈 Your score improved <strong>+6%</strong> over the last 5 sessions. Keep it up!
        </div>

        <!-- Button row -->
        <div class="sf-btn-row">
          <div class="stButton"><button class="sf-btn primary">Start Practice</button></div>
          <div class="stButton"><button class="sf-btn">Timed Exam</button></div>
          <div class="stButton"><button class="sf-btn">Review Mistakes</button></div>
        </div>

        <!-- Table -->
        <div class="sf-table-header stDataFrame" data-testid="stDataFrame">
          <span>Question Type</span><span>Correct</span><span>Total</span><span>Rate</span>
        </div>
        <div class="sf-table-row">
          <span>Strengthen</span><span>18</span><span>22</span>
          <span><span class="sf-badge green">82%</span></span>
        </div>
        <div class="sf-table-row">
          <span>Weaken</span><span>14</span><span>20</span>
          <span><span class="sf-badge blue">70%</span></span>
        </div>
        <div class="sf-table-row">
          <span>Flaw</span><span>8</span><span>16</span>
          <span><span class="sf-badge gray">50%</span></span>
        </div>
        <div class="sf-table-row">
          <span>Assumption</span><span>12</span><span>18</span>
          <span><span class="sf-badge blue">67%</span></span>
        </div>
      </div>

    </div>
  </div>
  {'<div class="device-home"></div>' if dw < 600 else ''}
</div>

</body>
</html>
"""

    frame_h = int(dh * scale) + 120  # extra space for shell + meta
    components.html(preview_html, height=frame_h, scrolling=False)

# ────────────────────────────────────────────────────────────────────────────────
# RIGHT: Editor panel with tabs
# ────────────────────────────────────────────────────────────────────────────────
with col_editor:
    (
        tab_components,
        tab_breakpoints,
        tab_debug,
        tab_history,
        tab_raw,
    ) = st.tabs(["🧩 Components", "📏 Breakpoints", "🔍 Debug", "📜 History", "{ } Raw CSS"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: Component editor
    # ══════════════════════════════════════════════════════════════════════════
    with tab_components:
        cfg = st.session_state["rlm_config"]
        comp_keys   = list(cfg["components"].keys())
        comp_labels = [cfg["components"][k].get("label", k) for k in comp_keys]

        # Group by category
        groups: dict[str, list] = {}
        for k in comp_keys:
            g = cfg["components"][k].get("group", "Other")
            groups.setdefault(g, []).append(k)

        # Component selector
        sel_group = st.selectbox("Category", options=sorted(groups.keys()),
                                 key="rlm_group_picker")
        group_keys   = groups.get(sel_group, [])
        group_labels = [cfg["components"][k].get("label", k) for k in group_keys]

        sel_key = st.selectbox("Component", options=group_keys,
                               format_func=lambda k: cfg["components"][k].get("label", k),
                               key="rlm_component")

        st.caption(f"CSS selector: `{sel_key}`")
        st.divider()

        # Breakpoint selector
        bp_choice = st.radio(
            "Edit breakpoint",
            options=["desktop", "laptop", "tablet", "mobile"],
            horizontal=True,
            key="rlm_breakpoint",
        )
        st.caption({
            "desktop": "≥1200px — baseline styles",
            "laptop":  "992–1199px",
            "tablet":  "768–991px",
            "mobile":  "≤480px",
        }[bp_choice])

        comp_cfg = cfg["components"].get(sel_key, {})
        bp_props = comp_cfg.get(bp_choice, {}).copy()

        # ── Property editor ───────────────────────────────────────────────────
        st.markdown("**CSS Properties** *(add / edit / remove)*")

        PROP_GROUPS = [
            ("Typography",
             ["font-size", "font-weight", "line-height", "letter-spacing",
              "text-align", "color"]),
            ("Spacing",
             ["padding", "padding-top", "padding-right", "padding-bottom",
              "padding-left", "margin", "margin-top", "margin-bottom",
              "margin-left", "margin-right", "gap"]),
            ("Sizing",
             ["width", "min-width", "max-width", "height", "min-height",
              "max-height"]),
            ("Layout",
             ["display", "flex-direction", "align-items", "justify-content",
              "flex-wrap", "flex", "grid-template-columns", "overflow",
              "overflow-x", "overflow-y", "order"]),
            ("Visual",
             ["background", "border", "border-radius", "box-shadow",
              "opacity", "visibility", "transform"]),
        ]

        COMMON_VALUES = {
            "display":         ["block", "flex", "grid", "inline-flex",
                                "inline-block", "none"],
            "flex-direction":  ["row", "column", "row-reverse",
                                "column-reverse"],
            "align-items":     ["flex-start", "center", "flex-end",
                                "stretch", "baseline"],
            "justify-content": ["flex-start", "center", "flex-end",
                                "space-between", "space-around",
                                "space-evenly"],
            "flex-wrap":       ["nowrap", "wrap", "wrap-reverse"],
            "visibility":      ["visible", "hidden"],
            "overflow":        ["auto", "hidden", "visible", "scroll"],
            "overflow-x":      ["auto", "hidden", "visible", "scroll"],
            "font-weight":     ["400", "500", "600", "700", "bold"],
            "text-align":      ["left", "center", "right", "justify"],
        }

        changed = False
        edited_props: dict = {}

        for grp_name, prop_list in PROP_GROUPS:
            with st.expander(grp_name, expanded=(grp_name in ("Spacing", "Typography", "Layout"))):
                for prop in prop_list:
                    cur_val = bp_props.get(prop, "")
                    if prop in COMMON_VALUES:
                        options = ["(not set)"] + COMMON_VALUES[prop] + (
                            [cur_val] if cur_val and cur_val not in COMMON_VALUES[prop] else []
                        )
                        disp_idx = options.index(cur_val) if cur_val in options else 0
                        new_val = st.selectbox(
                            prop, options=options, index=disp_idx,
                            key=f"prop_{sel_key}_{bp_choice}_{prop}",
                        )
                        if new_val == "(not set)":
                            new_val = ""
                    else:
                        new_val = _value_control(
                            prop,
                            cur_val,
                            f"prop_{sel_key}_{bp_choice}_{prop}",
                        )
                    if new_val:
                        edited_props[prop] = new_val
                    if new_val != cur_val:
                        changed = True

        # Custom property
        st.divider()
        with st.expander("➕ Add custom property"):
            cc1, cc2 = st.columns(2)
            custom_prop = cc1.text_input("Property name", key="custom_prop_name",
                                         placeholder="e.g. border-top")
            custom_val  = cc2.text_input("Value", key="custom_prop_val",
                                          placeholder="e.g. 2px solid #e5e7eb")
            if st.button("Add property", key="add_custom_prop"):
                if custom_prop and custom_val:
                    edited_props[custom_prop] = custom_val
                    changed = True

        # Apply changes
        if changed:
            _push_undo()
            cfg["components"][sel_key][bp_choice] = edited_props
            st.session_state["rlm_config"] = cfg
            st.rerun()

        # ── Quick presets ──────────────────────────────────────────────────────
        st.divider()
        st.markdown("**Quick Presets**")
        p1, p2, p3 = st.columns(3)
        with p1:
            if st.button("📵 Hide on mobile", use_container_width=True,
                          key="preset_hide_mobile"):
                _push_undo()
                cfg["components"][sel_key].setdefault("mobile", {})["display"] = "none"
                st.session_state["rlm_config"] = cfg
                st.rerun()
        with p2:
            if st.button("📏 Full width btn", use_container_width=True,
                          key="preset_full_btn"):
                _push_undo()
                cfg["components"][sel_key].setdefault("mobile", {}).update(
                    {"width": "100%", "min-height": "44px"}
                )
                st.session_state["rlm_config"] = cfg
                st.rerun()
        with p3:
            if st.button("🔤 Larger font", use_container_width=True,
                          key="preset_large_font"):
                _push_undo()
                cfg["components"][sel_key].setdefault("mobile", {})["font-size"] = "16px"
                st.session_state["rlm_config"] = cfg
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2: Breakpoints
    # ══════════════════════════════════════════════════════════════════════════
    with tab_breakpoints:
        st.markdown("### Responsive Breakpoints")
        st.caption("Width (px) below which each breakpoint activates. Desktop is the baseline.")

        bp = cfg.get("breakpoints", {})
        changed_bp = False

        bp_defs = [
            ("desktop", "🖥️ Desktop (baseline ≥)", None, None),
            ("laptop",  "💻 Laptop max-width",     600, 1400),
            ("tablet",  "📟 Tablet max-width",      400, 1100),
            ("mobile",  "📱 Mobile max-width",      300, 800),
        ]

        for key, label, mn, mx in bp_defs:
            if key == "desktop":
                st.number_input(label, value=bp.get(key, 1200),
                                min_value=1000, max_value=2560,
                                key=f"bp_{key}", disabled=True,
                                help="Desktop is always the baseline — CSS written without a media query.")
            else:
                current_bp = int(bp.get(key, {"laptop": 992, "tablet": 768, "mobile": 480}[key]))
                bc1, bc2 = st.columns([3, 1])
                with bc1:
                    slider_val = st.slider(
                        label,
                        value=current_bp,
                        min_value=mn,
                        max_value=mx,
                        step=4,
                        key=f"bp_{key}_slider",
                        help=f"Styles in the '{key}' column apply below this width.",
                    )
                with bc2:
                    typed_val = st.number_input(
                        "px",
                        value=current_bp,
                        min_value=mn,
                        max_value=mx,
                        step=4,
                        key=f"bp_{key}_number",
                        label_visibility="collapsed",
                    )
                new_val = typed_val if typed_val != current_bp else slider_val
                if new_val != bp.get(key):
                    changed_bp = True
                    bp[key] = new_val

        if changed_bp:
            _push_undo()
            cfg["breakpoints"] = bp
            st.session_state["rlm_config"] = cfg
            st.rerun()

        st.divider()
        st.markdown("**Current Breakpoint Map**")
        bps = cfg.get("breakpoints", {})
        components.html(f"""
<style>
  body {{ font-family: -apple-system, sans-serif; background: transparent; margin: 0; }}
  .bp-bar {{ display: flex; height: 36px; border-radius: 8px; overflow: hidden;
             border: 1px solid #e5e7eb; margin-top: 8px; }}
  .bp-seg {{ display: flex; align-items: center; justify-content: center;
             font-size: 11px; font-weight: 600; color: white; }}
</style>
<div class="bp-bar">
  <div class="bp-seg" style="background:#6366f1;flex:{bps.get('desktop',1200)-bps.get('laptop',992)}">
    Desktop
  </div>
  <div class="bp-seg" style="background:#8b5cf6;flex:{bps.get('laptop',992)-bps.get('tablet',768)}">
    Laptop
  </div>
  <div class="bp-seg" style="background:#a78bfa;flex:{bps.get('tablet',768)-bps.get('mobile',480)}">
    Tablet
  </div>
  <div class="bp-seg" style="background:#c4b5fd;flex:{bps.get('mobile',480)}">
    Mobile
  </div>
</div>
<div style="display:flex;justify-content:space-between;font-size:10px;
            color:#9ca3af;margin-top:4px;">
  <span>{bps.get('mobile',480)}px</span>
  <span>{bps.get('tablet',768)}px</span>
  <span>{bps.get('laptop',992)}px</span>
  <span>{bps.get('desktop',1200)}px+</span>
</div>
        """, height=70)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3: Debug Tools
    # ══════════════════════════════════════════════════════════════════════════
    with tab_debug:
        st.markdown("### 🔍 Responsive Debug Analysis")
        st.caption("Static analysis of the current layout configuration.")

        issues = []
        warnings = []
        passed  = []

        comp_data = cfg.get("components", {})

        # ── Touch target check ────────────────────────────────────────────────
        for sel, settings in comp_data.items():
            label = settings.get("label", sel)
            if "button" in sel.lower() or "btn" in sel.lower():
                mob = settings.get("mobile", {})
                min_h = mob.get("min-height", "")
                if not min_h:
                    warnings.append(
                        f"⚠️ **{label}**: No `min-height` on mobile. "
                        "WCAG requires 44×44 px touch targets."
                    )
                else:
                    try:
                        val = int("".join(filter(str.isdigit, min_h)))
                        if val < 44:
                            warnings.append(
                                f"⚠️ **{label}**: Mobile `min-height: {min_h}` is below "
                                "the recommended 44px touch target."
                            )
                        else:
                            passed.append(f"✅ **{label}**: Touch target ≥44px ({min_h}).")
                    except ValueError:
                        pass

        # ── iOS font-size zoom check ──────────────────────────────────────────
        for sel, settings in comp_data.items():
            label = settings.get("label", sel)
            if any(x in sel for x in ["select", "input", "textarea"]):
                mob_fs = settings.get("mobile", {}).get("font-size", "")
                if mob_fs:
                    try:
                        val = int("".join(filter(str.isdigit, mob_fs)))
                        if val < 16:
                            issues.append(
                                f"🔴 **{label}**: Mobile `font-size: {mob_fs}` will "
                                "trigger iOS auto-zoom. Use 16px or larger."
                            )
                        else:
                            passed.append(
                                f"✅ **{label}**: Input font-size ≥16px ({mob_fs}) — no iOS zoom."
                            )
                    except ValueError:
                        pass

        # ── Overflow check ────────────────────────────────────────────────────
        for sel, settings in comp_data.items():
            label = settings.get("label", sel)
            for bp_name in ["tablet", "mobile"]:
                props = settings.get(bp_name, {})
                width = props.get("width", "")
                if "vw" in width or "%" in width:
                    passed.append(f"✅ **{label}** ({bp_name}): Fluid width `{width}`.")
                elif "px" in width:
                    try:
                        val = int("".join(filter(str.isdigit, width)))
                        bp_max = cfg["breakpoints"].get(bp_name, 480)
                        if val > bp_max:
                            issues.append(
                                f"🔴 **{label}** ({bp_name}): Width `{width}` exceeds "
                                f"breakpoint {bp_max}px — will cause horizontal scroll!"
                            )
                    except ValueError:
                        pass

        # ── Horizontal scroll risk ────────────────────────────────────────────
        for sel, settings in comp_data.items():
            label = settings.get("label", sel)
            if "data-frame" in sel.lower() or "table" in sel.lower():
                mob = settings.get("mobile", {})
                if "overflow-x" not in mob:
                    warnings.append(
                        f"⚠️ **{label}**: Table/DataFrame has no `overflow-x` on mobile. "
                        "Consider `overflow-x: auto`."
                    )

        # ── Hidden elements check ─────────────────────────────────────────────
        for sel, settings in comp_data.items():
            label = settings.get("label", sel)
            if settings.get("mobile", {}).get("display") == "none":
                warnings.append(
                    f"ℹ️ **{label}**: Hidden on mobile. "
                    "Verify this content is accessible elsewhere."
                )

        # ── Sidebar collapse check ────────────────────────────────────────────
        sidebar_mob = comp_data.get("[data-testid='stSidebar']", {}).get("mobile", {})
        if not sidebar_mob.get("max-width") == "0":
            warnings.append(
                "⚠️ **Sidebar Navigation**: Not collapsed on mobile. "
                "This typically causes layout overflow on small screens."
            )

        # ── Render results ────────────────────────────────────────────────────
        if issues:
            st.error(f"**{len(issues)} critical issue(s) found:**")
            for iss in issues:
                st.markdown(iss)
            st.divider()

        if warnings:
            st.warning(f"**{len(warnings)} warning(s):**")
            for w in warnings:
                st.markdown(w)
            st.divider()

        if passed:
            with st.expander(f"✅ {len(passed)} check(s) passed", expanded=False):
                for p in passed:
                    st.markdown(p)

        if not issues and not warnings:
            st.success("🎉 No responsive issues detected in the current configuration.")

        st.divider()
        st.markdown("**Generated CSS Preview**")
        generated = generate_css(st.session_state["rlm_config"])
        st.code(generated, language="css")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4: Version History
    # ══════════════════════════════════════════════════════════════════════════
    with tab_history:
        st.markdown("### 📜 Version History")
        st.caption("Auto-snapshotted before every publish, reset, or restore.")

        if not cfg_id:
            st.info("Save a draft first to enable version history.")
        else:
            history = get_history(cfg_id, limit=20)
            if not history:
                st.info("No history snapshots yet. Publish or Reset to create one.")
            else:
                for entry in history:
                    hcol1, hcol2 = st.columns([4, 1])
                    hcol1.markdown(f"**{entry['label']}** — *{entry['created_at']}*")
                    with hcol2:
                        if st.button("↩ Restore", key=f"restore_{entry['id']}",
                                      use_container_width=True):
                            restore_from_history(entry["id"], cfg_id)
                            st.session_state["rlm_config"] = get_config_by_id(cfg_id)
                            st.success(f"Restored snapshot from {entry['created_at']}")
                            st.rerun()

        st.divider()
        st.markdown("**Available Configs**")
        all_cfgs = get_all_configs()
        for c in all_cfgs:
            status = "🟢 Active" if c["is_active"] else ("📝 Draft" if c["is_draft"] else "📦 Saved")
            ccol1, ccol2, ccol3 = st.columns([3, 2, 2])
            ccol1.markdown(f"**{c['name']}** — {status}")
            ccol2.caption(c["updated_at"][:16] if c["updated_at"] else "")
            with ccol3:
                if not c["is_active"]:
                    if st.button("Load", key=f"load_cfg_{c['id']}",
                                  use_container_width=True):
                        loaded = get_config_by_id(c["id"])
                        if loaded:
                            _push_undo()
                            st.session_state["rlm_config"]    = loaded
                            st.session_state["rlm_config_id"] = c["id"]
                            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 5: Raw CSS / JSON
    # ══════════════════════════════════════════════════════════════════════════
    with tab_raw:
        st.markdown("### Generated CSS")
        st.code(generate_css(st.session_state["rlm_config"]), language="css")
        st.divider()
        st.markdown("### Config JSON")
        st.json(st.session_state["rlm_config"])

        st.divider()
        st.markdown("### Import JSON")
        st.caption("Paste a complete config JSON to overwrite the current working config.")
        raw_import = st.text_area("JSON", height=200, key="rlm_import_json")
        if st.button("Import & Apply", key="rlm_do_import"):
            try:
                parsed = json.loads(raw_import)
                assert "components" in parsed and "breakpoints" in parsed
                _push_undo()
                st.session_state["rlm_config"] = parsed
                st.success("Config imported.")
                st.rerun()
            except Exception as e:
                st.error(f"Invalid JSON: {e}")
