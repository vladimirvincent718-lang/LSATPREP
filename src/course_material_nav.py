"""Shared navigation within the course materials workspace."""

import streamlit as st


def course_material_nav(active: str) -> None:
    st.caption("Course Materials")
    destinations = (
        ("library", "pages/3_Course_Materials.py", "Material Library", "📖"),
        ("flashcards", "pages/3a_Flashcards.py", "Flashcards", "🗃️"),
        ("notebook", "pages/3b_Notebook.py", "Notebook", "📓"),
        ("audio", "pages/3c_Audio_Study.py", "Audio Study", "🎧"),
        ("questions", "pages/4_Question_Bank_Manager.py", "Question Bank Manager", "🗂"),
    )
    for column, (key, path, label, icon) in zip(st.columns(len(destinations)), destinations):
        with column:
            st.page_link(path, label=label, icon=icon, disabled=key == active,
                         use_container_width=True)
