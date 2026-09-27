"""Touch navigation layered over the normal question renderer and scoring flow."""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


def skip_pass_indices(total, reached, answers):
    answered = {int(i) for i in answers if str(i).isdigit()}
    return sorted({int(i) for i in reached if str(i).isdigit()
                   and 0 <= int(i) < total} - answered)


def install_swipe_view():
    st.markdown("""<style>
    [data-testid="stMainBlockContainer"] {width:100%; max-width: 36rem;
        padding: 1rem clamp(.5rem, 3vw, 1rem) 3rem; min-width:0;}
    [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {gap:.65rem;}
    .st-key-practice_dashboard_summary {display:none;}
    .st-key-practice_swipe_card {border:1px solid #94a3b855; border-radius:20px;
        padding:1rem; box-shadow:0 8px 28px #0f172a0c; touch-action:pan-y;
        scroll-margin-top:64px;}
    .st-key-practice_swipe_card [role="radiogroup"] {width:100%; align-items:stretch;}
    .st-key-practice_swipe_card [data-testid="stRadio"] label[data-baseweb="radio"] {
        min-height:52px; padding:10px; border:1px solid #94a3b866;
        border-radius:12px; margin:5px 0; width:100%; box-sizing:border-box;}
    .st-key-practice_swipe_card .sf-question-meta {font-size:.8rem; line-height:1.5;
        padding:0; margin:0; background:transparent; border:0; box-shadow:none;
        overflow-wrap:break-word; word-break:normal;}
    .st-key-practice_swipe_card [data-testid="stPopover"] button {
        min-height:2.75rem; white-space:normal; word-break:normal; overflow-wrap:normal;}
    .st-key-practice_swipe_card [data-testid="stPopover"] button p {
        white-space:normal; word-break:normal; overflow-wrap:normal;}
    [data-testid="stPopoverBody"] {min-width:0; max-width:calc(100vw - 2rem);}
    .st-key-practice_swipe_card textarea[readonly] {touch-action:pan-y; cursor:grab;}
    .st-key-practice_swipe_card [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
    .st-key-practice_swipe_nav [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
    .st-key-practice_swipe_nav [data-testid="stColumn"] {min-width:min(100%, 9rem); flex:1;}
    .st-key-practice_swipe_nav button {min-height:48px;}
    </style>""", unsafe_allow_html=True)


def install_swipe_gestures(current_idx):
    script = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    # Changing srcdoc re-arms gestures after navigation, including consecutive swipes.
    components.html(f'<script>window.practiceSwipeQuestion = {int(current_idx)};{script}</script>', height=0)
