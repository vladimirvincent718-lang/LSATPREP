"""Shared modern visual theme for the StudyForge learning platform."""

from __future__ import annotations

from html import escape

import streamlit as st


_MODERN_THEME_CSS = """
<style>
:root {
    --sf-ink: #111827;
    --sf-muted: #64748b;
    --sf-soft: #f6f8fb;
    --sf-panel: #ffffff;
    --sf-line: #dbe3ef;
    --sf-line-soft: #e8edf5;
    --sf-blue: #1d4ed8;
    --sf-blue-dark: #1e3a8a;
    --sf-teal: #0f766e;
    --sf-amber: #d97706;
    --sf-good: #0f766e;
    --sf-danger: #b91c1c;
    --sf-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
    --sf-shadow-soft: 0 4px 14px rgba(15, 23, 42, 0.06);
    --sf-radius: 8px;
}

.stApp {
    background:
        radial-gradient(circle at top left, rgba(29, 78, 216, 0.08), transparent 30rem),
        linear-gradient(180deg, #f8fafc 0%, var(--sf-soft) 42%, #eef3f8 100%) !important;
    color: var(--sf-ink) !important;
}

.main .block-container {
    max-width: 1220px;
    padding-top: 2.1rem;
    padding-bottom: 4.5rem;
}

h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    color: var(--sf-ink);
    letter-spacing: 0;
}

p, li, label, [data-testid="stMarkdownContainer"] {
    color: #253044;
}

hr {
    margin: 1.35rem 0 !important;
    border-color: var(--sf-line-soft) !important;
}

a {
    color: var(--sf-blue);
    text-decoration-thickness: 1px;
    text-underline-offset: 3px;
}

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #111827 100%) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
    box-shadow: 12px 0 30px rgba(15, 23, 42, 0.12);
}

section[data-testid="stSidebar"] * {
    color: #e5edf7 !important;
}

section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    color: #b8c5d8 !important;
}

[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNavItems"] a {
    border-radius: var(--sf-radius) !important;
    margin: 2px 8px !important;
    transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

[data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebarNavItems"] a:hover {
    background: rgba(255, 255, 255, 0.10) !important;
    transform: translateX(2px);
}

button,
.stButton > button,
.stDownloadButton > button,
[data-testid="baseButton-secondary"],
[data-testid="baseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"],
[data-testid="baseButton-secondaryFormSubmit"] {
    border-radius: var(--sf-radius) !important;
    border: 1px solid var(--sf-line) !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05) !important;
    font-weight: 650 !important;
    letter-spacing: 0 !important;
    min-height: 2.45rem !important;
    transition: transform 0.14s ease, box-shadow 0.14s ease, border-color 0.14s ease, background 0.14s ease !important;
}

.stButton > button:hover,
.stDownloadButton > button:hover {
    transform: translateY(-1px);
    box-shadow: var(--sf-shadow-soft) !important;
    border-color: #b9c7da !important;
}

[data-testid="baseButton-primary"],
[data-testid="stBaseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"],
[data-testid="stBaseButton-primaryFormSubmit"] {
    background: linear-gradient(135deg, var(--sf-blue) 0%, #0f766e 100%) !important;
    color: #ffffff !important;
    border-color: rgba(29, 78, 216, 0.45) !important;
}

[data-testid="baseButton-primary"] *,
[data-testid="stBaseButton-primary"] *,
[data-testid="baseButton-primaryFormSubmit"] *,
[data-testid="stBaseButton-primaryFormSubmit"] * {
    color: #ffffff !important;
    font-weight: 800 !important;
}

[data-testid="baseButton-primary"] svg,
[data-testid="stBaseButton-primary"] svg,
[data-testid="baseButton-primaryFormSubmit"] svg,
[data-testid="stBaseButton-primaryFormSubmit"] svg {
    color: #ffffff !important;
    fill: currentColor !important;
    stroke: currentColor !important;
}

button:focus-visible,
input:focus,
textarea:focus,
[role="combobox"]:focus,
[data-baseweb="select"] div:focus {
    outline: 3px solid rgba(29, 78, 216, 0.20) !important;
    outline-offset: 2px !important;
}

[data-testid="stForm"],
[data-testid="stExpander"],
[data-testid="stDataFrame"],
[data-testid="stTable"],
[data-testid="stPlotlyChart"],
[data-testid="stMetric"] {
    border-radius: var(--sf-radius) !important;
}

[data-testid="stForm"] {
    background: rgba(255, 255, 255, 0.82) !important;
    border: 1px solid var(--sf-line-soft) !important;
    box-shadow: var(--sf-shadow-soft) !important;
    padding: 1rem !important;
}

[data-testid="stExpander"] {
    background: rgba(255, 255, 255, 0.86) !important;
    border: 1px solid var(--sf-line-soft) !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
    overflow: hidden;
}

[data-testid="stMetric"] {
    background: linear-gradient(180deg, #ffffff 0%, #f9fbfd 100%);
    border: 1px solid var(--sf-line-soft);
    box-shadow: var(--sf-shadow-soft);
    padding: 1rem 1.05rem;
}

[data-testid="stMetricLabel"] p {
    color: var(--sf-muted) !important;
    font-size: 0.76rem !important;
    font-weight: 750 !important;
    letter-spacing: 0.02em !important;
    text-transform: uppercase;
}

[data-testid="stMetricValue"] {
    color: var(--sf-ink) !important;
    font-weight: 800 !important;
}

[data-testid="stMetricDelta"] {
    font-weight: 700 !important;
}

[data-testid="stAlert"] {
    border-radius: var(--sf-radius) !important;
    border: 1px solid var(--sf-line-soft) !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

[data-baseweb="input"],
[data-baseweb="textarea"],
[data-baseweb="select"] > div,
[data-baseweb="slider"] {
    border-radius: var(--sf-radius) !important;
}

input, textarea {
    color: var(--sf-ink) !important;
}

[data-testid="stTabBar"] {
    gap: 0.35rem !important;
    border-bottom: 1px solid var(--sf-line-soft);
}

[data-testid="stTab"] {
    border-radius: var(--sf-radius) var(--sf-radius) 0 0 !important;
    font-weight: 700 !important;
}

[data-testid="stPlotlyChart"] {
    background: rgba(255, 255, 255, 0.86);
    border: 1px solid var(--sf-line-soft);
    box-shadow: var(--sf-shadow-soft);
    padding: 0.65rem;
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
    border: 1px solid var(--sf-line-soft);
    box-shadow: var(--sf-shadow-soft);
    overflow: hidden;
}

.sf-page-header {
    margin: 0 0 1.25rem;
    padding: 1.05rem 1.15rem;
    border: 1px solid rgba(219, 227, 239, 0.92);
    border-radius: var(--sf-radius);
    background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.90)),
        linear-gradient(90deg, rgba(29, 78, 216, 0.10), rgba(15, 118, 110, 0.08));
    box-shadow: var(--sf-shadow-soft);
}

.sf-page-eyebrow {
    margin: 0 0 0.35rem;
    color: var(--sf-teal);
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.sf-page-title {
    margin: 0;
    color: var(--sf-ink);
    font-size: clamp(1.55rem, 2.5vw, 2.25rem);
    line-height: 1.08;
    font-weight: 850;
}

.sf-page-subtitle {
    margin: 0.45rem 0 0;
    color: var(--sf-muted);
    font-size: 0.98rem;
    line-height: 1.45;
}

.sf-hero {
    border: 1px solid rgba(219, 227, 239, 0.90);
    border-radius: var(--sf-radius);
    background:
        linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 58, 138, 0.88)),
        linear-gradient(90deg, rgba(15, 118, 110, 0.30), rgba(217, 119, 6, 0.22));
    box-shadow: var(--sf-shadow);
    padding: clamp(1.2rem, 3vw, 2rem);
    margin-bottom: 1rem;
}

.sf-hero h1 {
    margin: 0;
    color: #ffffff;
    font-size: clamp(2rem, 5vw, 3.8rem);
    line-height: 0.98;
    font-weight: 900;
}

.sf-hero p {
    max-width: 62rem;
    margin: 0.85rem 0 0;
    color: #cbd5e1;
    font-size: clamp(1rem, 2vw, 1.15rem);
    line-height: 1.6;
}

.sf-feature-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 1rem 0;
}

.sf-feature-card,
.sf-score-shell,
.sf-question-meta,
.sf-stimulus-card,
.sf-timer-card {
    border-radius: var(--sf-radius);
    border: 1px solid var(--sf-line-soft);
    background: rgba(255, 255, 255, 0.88);
    box-shadow: var(--sf-shadow-soft);
}

.sf-feature-card {
    padding: 0.95rem;
}

.sf-feature-kicker {
    color: var(--sf-teal);
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.sf-feature-title {
    margin: 0.25rem 0;
    color: var(--sf-ink);
    font-weight: 820;
}

.sf-feature-copy {
    color: var(--sf-muted);
    font-size: 0.9rem;
    line-height: 1.45;
}

.sf-score-shell {
    padding: 1rem;
    margin: 0.5rem 0 1rem;
}

.sf-score-title {
    margin: 0 0 0.75rem;
    color: var(--sf-ink);
    font-size: 1.2rem;
    font-weight: 850;
}

.sf-question-meta {
    padding: 0.75rem 0.9rem;
    margin-bottom: 0.85rem;
    color: var(--sf-muted);
    font-size: 0.85rem;
    font-weight: 700;
}

.sf-stimulus-card {
    padding: 1rem;
    margin: 0.8rem 0 0.9rem;
    color: var(--sf-ink);
    line-height: 1.7;
    white-space: pre-wrap;
}

.sf-timer-card {
    padding: 0.8rem 0.9rem;
    margin: 0.5rem 0;
}

.sf-timer-label {
    color: var(--sf-ink);
    font-weight: 800;
    margin-bottom: 0.35rem;
}

.stProgress > div > div > div > div {
    background: linear-gradient(90deg, var(--sf-blue), var(--sf-teal)) !important;
}

#sf-sb-btn {
    border-radius: var(--sf-radius) !important;
    border-color: rgba(219, 227, 239, 0.95) !important;
    box-shadow: var(--sf-shadow-soft) !important;
}

#sf-feedback-fab,
#sf-feedback-fab-container button {
    background: linear-gradient(135deg, var(--sf-blue) 0%, var(--sf-teal) 100%) !important;
    border-radius: 999px !important;
    box-shadow: 0 12px 28px rgba(29, 78, 216, 0.26) !important;
}

@media (max-width: 760px) {
    .main .block-container {
        padding-left: 1rem;
        padding-right: 1rem;
        padding-top: 1.15rem;
    }
    .sf-feature-grid {
        grid-template-columns: 1fr;
    }
    [data-testid="column"] {
        min-width: 0 !important;
    }
    [data-testid="stMetric"] {
        padding: 0.8rem !important;
    }
    button,
    .stButton > button,
    .stDownloadButton > button {
        min-height: 44px !important;
        white-space: normal !important;
    }
}

@media (prefers-color-scheme: dark) {
    :root {
        --sf-ink: #f8fafc;
        --sf-muted: #aebbd0;
        --sf-soft: #0f172a;
        --sf-panel: #111827;
        --sf-line: rgba(255, 255, 255, 0.16);
        --sf-line-soft: rgba(255, 255, 255, 0.10);
    }
    .stApp {
        background: linear-gradient(180deg, #0b1120 0%, #111827 100%) !important;
    }
    p, li, label, [data-testid="stMarkdownContainer"] {
        color: #d7deea;
    }
    [data-testid="stForm"],
    [data-testid="stExpander"],
    [data-testid="stMetric"],
    [data-testid="stPlotlyChart"],
    .sf-page-header,
    .sf-feature-card,
    .sf-score-shell,
    .sf-question-meta,
    .sf-stimulus-card,
    .sf-timer-card {
        background: rgba(17, 24, 39, 0.88) !important;
        border-color: rgba(255, 255, 255, 0.10) !important;
    }
}
</style>
"""


def inject_modern_theme() -> None:
    """Inject the global StudyForge visual system."""
    st.markdown(_MODERN_THEME_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
<div class="sf-hero">
  <h1>{escape(title)}</h1>
  <p>{escape(subtitle)}</p>
</div>
""",
        unsafe_allow_html=True,
    )


def feature_grid(features: list[tuple[str, str, str]]) -> None:
    cards = []
    for kicker, title, copy in features:
        cards.append(
            f"""
  <div class="sf-feature-card">
    <div class="sf-feature-kicker">{escape(kicker)}</div>
    <div class="sf-feature-title">{escape(title)}</div>
    <div class="sf-feature-copy">{escape(copy)}</div>
  </div>
"""
        )
    st.markdown(
        '<div class="sf-feature-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def apply_plotly_theme(fig):
    """Apply the StudyForge chart treatment to a Plotly figure."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,0.72)",
        font=dict(color="#111827", family="Arial, sans-serif"),
        colorway=["#1d4ed8", "#0f766e", "#d97706", "#7c3aed", "#b91c1c"],
        legend=dict(
            bgcolor="rgba(255,255,255,0)",
            borderwidth=0,
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(gridcolor="#e8edf5", zerolinecolor="#dbe3ef"),
        yaxis=dict(gridcolor="#e8edf5", zerolinecolor="#dbe3ef"),
    )
    return fig
