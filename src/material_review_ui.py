"""Course-material slide viewer and spaced-review controls."""
from datetime import date
from pathlib import Path

import streamlit as st

from src import material_reviews as reviews

ROOT = Path(__file__).resolve().parent.parent


def material_file(material):
    raw = material.get('stored_file_path')
    if not raw:
        return None
    path = (ROOT / raw).resolve()
    if path.is_relative_to((ROOT / 'data/material_files').resolve()) and path.is_file():
        return path
    return None


@st.cache_data(show_spinner=False, max_entries=32)
def pdf_slide(path, modified, page):
    import fitz
    with fitz.open(path) as doc:
        return doc[page].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).tobytes('png'), len(doc)


def render_slide_view_counts(user_id, material_id, page, count):
    history = reviews.slide_view_history(user_id, material_id)
    by_slide = {}
    for row in history:
        by_slide.setdefault(row['slide_number'], []).append(row)

    def view_count(slide, current=False):
        daily = by_slide.get(slide, [])
        total = sum(row['views'] for row in daily)
        label = f"{total:,} {'view' if total == 1 else 'views'}"
        if current:
            label = f'Slide {slide} · {label}'
        with st.popover(label, help='Click to see views by day'):
            st.markdown(f'**Slide {slide} — views by day**')
            st.write(f'**Total: {total:,}**')
            if daily:
                st.dataframe([{'Date': row['viewed_on'], 'Views': row['views']} for row in daily],
                             hide_index=True, width='stretch')
            else:
                st.caption('No views recorded yet.')

    view_count(page, current=True)
    st.caption('Your views: opening a slide or returning to it counts once. '
               'Counts start when tracking is enabled; earlier visits are not included. '
               'Click any count for daily details. Dates use the app’s local time.')
    with st.expander('View counts for all slides'):
        columns = st.columns(4)
        for slide in range(1, count + 1):
            with columns[(slide - 1) % len(columns)]:
                st.markdown(f'**Slide {slide}**')
                view_count(slide)


def render_slide_viewer(path, key_prefix, user_id=None, material_id=None):
    """Show the actual slide first; navigation never requires a download."""
    try:
        # Streamlit removes widget state after navigating away. This distinguishes
        # reopening the viewer from resize/report/rating reruns of the same slide.
        reopening = f'{key_prefix}_previous' not in st.session_state
        _, count = pdf_slide(str(path), path.stat().st_mtime_ns, 0)
        slide_key = f'{key_prefix}_slide'
        st.session_state[slide_key] = min(count, max(1, st.session_state.get(slide_key, 1)))

        def step(delta):
            st.session_state[slide_key] = min(count, max(1, st.session_state[slide_key] + delta))

        previous, position, next_button = st.columns([1, 2, 1])
        previous.button('← Previous', key=f'{key_prefix}_previous',
                        disabled=st.session_state[slide_key] == 1, on_click=step, args=(-1,),
                        use_container_width=True)
        with position:
            page = st.number_input('Slide', min_value=1, max_value=count, step=1, key=slide_key)
        next_button.button('Next →', key=f'{key_prefix}_next',
                           disabled=st.session_state[slide_key] == count, on_click=step, args=(1,),
                           use_container_width=True)
        view = st.radio('Slide size', ['Fit whole slide', 'Larger text'], horizontal=True,
                        key=f'{key_prefix}_size')
        image, _ = pdf_slide(str(path), path.stat().st_mtime_ns, int(page) - 1)
        frame_key = f'{key_prefix}_frame'
        # Scope sizing to this viewer, leaving every other app image untouched.
        fit = view == 'Fit whole slide'
        st.markdown(f'''<style>
        .st-key-{frame_key} {{height:min(65vh, 720px); min-height:220px; overflow:auto;
            background:#111827; border-radius:12px; touch-action:pan-y; cursor:grab;}}
        .st-key-{frame_key}:focus-visible {{outline:3px solid #2563eb; outline-offset:3px;}}
        .st-key-{frame_key} [data-testid="stImage"] {{width:100%;}}
        .st-key-{frame_key} img {{width:100% !important; object-fit:contain;
            height:{'min(65vh, 720px)' if fit else 'auto'} !important;
            max-height:{'min(65vh, 720px)' if fit else 'none'} !important;
            user-select:none; -webkit-user-drag:none;}}
        </style>''', unsafe_allow_html=True)
        with st.container(key=frame_key):
            st.image(image, use_container_width=True)
        if user_id is not None and material_id is not None:
            try:
                reviews.init_reviews()
                visit = (user_id, material_id, int(page))
                if reopening or st.session_state.get('_material_slide_visit') != visit:
                    reviews.record_slide_view(user_id, material_id, int(page))
                    st.session_state['_material_slide_visit'] = visit
                render_slide_view_counts(user_id, material_id, int(page), count)
            except Exception:
                st.warning('Slide view counts are unavailable right now. Try reopening this material.')
        left, middle, right = st.columns([1, 2, 1])
        left.button('← Previous slide', key=f'{key_prefix}_previous_bottom',
                    disabled=page == 1, on_click=step, args=(-1,), use_container_width=True)
        middle.markdown(f'**Slide {page} of {count}**')
        right.button('Next slide →', key=f'{key_prefix}_next_bottom',
                     disabled=page == count, on_click=step, args=(1,), use_container_width=True)
        st.caption('Drag or swipe left for the next slide, right for the previous slide. Click the slide to use ← / → keys. Fit whole slide shows every edge; Larger text lets you scroll for detail.')
        import json
        import streamlit.components.v1 as components
        script = Path(__file__).with_name('material_slide_gestures.js').read_text(encoding='utf-8')
        config = json.dumps({'prefix': key_prefix, 'page': int(page)})
        components.html(f'<script>window.slideViewerConfig={config};{script}</script>', height=0)
    except Exception:
        st.warning('The slide preview could not be loaded. Try reopening this material.')


def due_label(row):
    if not row['review_enabled']:
        return 'Review paused' if row['last_review'] else 'Not scheduled'
    if not row['last_review']:
        return 'First review due'
    if row['is_due']:
        days = (date.today() - date.fromisoformat(row['due_date'])).days
        return f'{days} days overdue' if days else 'Due today'
    return f"Next review: {row['due_date']}"


def render_course_reviews(user_id, course_id, track_views=True):
    if not track_views:
        st.session_state.pop('_material_slide_visit', None)
    reviews.init_reviews()
    rows = reviews.list_reviews(user_id, course_id)
    st.subheader('Cheat sheets & spaced review')
    st.caption('Recall → check the material → rate your recall. Your schedule and notes are private.')
    sheets = [r for r in rows if r['is_cheat_sheet']]
    if not sheets:
        st.info('No PDF slide cheat sheet is attached to this course yet. You can still schedule any existing material below.')
    due = [r for r in rows if r['is_due']]
    st.write(f"**{len(due)} due for review** · {len(sheets)} slide cheat sheet(s)")
    st.caption('Successful reviews: 1, 3, 7, 14, 30, then 60 days. Some gaps shortens the interval; Review tomorrow restarts it. Reminders appear in this app.')
    if not rows:
        return
    due_only = st.checkbox('Show only due reviews', key=f'material_due_only_{course_id}')
    options = due if due_only else sorted(rows, key=lambda r: (not r['is_cheat_sheet'], not r['is_due'], r['due_date']))
    if not options:
        st.success('You are caught up. Turn off the filter to see upcoming reviews.')
        return
    by_id = {r['id']: r for r in options}
    selected = st.selectbox('Choose a cheat sheet or material', list(by_id),
                            format_func=lambda mid: f"{by_id[mid]['title']} · {due_label(by_id[mid])}",
                            key=f'material_review_select_{course_id}')
    row = by_id[selected]
    st.markdown(f"**{row['title']}** — {due_label(row)}")
    if st.button('Pause reminders' if row['review_enabled'] else 'Start spaced review', key=f'review_toggle_{selected}'):
        reviews.set_enabled(user_id, selected, not row['review_enabled'])
        st.rerun()
    with st.expander('1. Recreate from memory (optional)', expanded=False):
        st.caption('Before opening the slides, sketch or write the formulas, rules, and connections you remember. Compare them with the original, then note the gaps.')
        recall = st.text_area('Your recall notes', key=f'material_recall_{user_id}_{selected}', height=160,
                              help='Notes are saved when you submit a review rating below.')
    st.markdown('**2. Slides / reference material**')
    with st.container():
        path = material_file(row)
        if path:
            if path.suffix.lower() == '.pdf':
                render_slide_viewer(path, f'review_{selected}',
                                    user_id=user_id if track_views else None, material_id=selected)
            with st.expander('Save a copy (optional)'):
                st.download_button('Download original document', path.read_bytes(), file_name=path.name,
                                   key=f'review_download_{selected}')
        elif row.get('stored_file_path'):
            st.warning('The attached document could not be found. Ask an administrator to reattach it.')
        if row.get('external_url'):
            st.link_button('Open resource', row['external_url'])
        if row.get('content_text'):
            st.markdown(row['content_text'])
    st.markdown('**3. How much could you recall?**')
    if row['last_review'] == date.today().isoformat():
        st.success(f"Review saved today. Next review: {row['due_date']}.")
    elif row['review_enabled']:
        cols = st.columns(3)
        for col, rating, label in zip(cols, ('again', 'hard', 'good'),
                                      ('Review tomorrow', 'Some gaps', 'Recalled well')):
            if col.button(label, key=f'review_rate_{selected}_{rating}', use_container_width=True):
                reviews.record_review(user_id, selected, rating, recall)
                st.rerun()
        st.caption('Opening or downloading a document does not count as a review. Choose a rating to save your notes and next date.')
    else:
        st.caption('Start spaced review above to save a rating and schedule your next review.')
    with st.expander('Previous recall notes & reviews'):
        history = reviews.review_history(user_id, selected)
        if not history:
            st.caption('No reviews recorded yet.')
        for item in history:
            st.markdown(f"**{item['reviewed_on']}** · {item['rating']} · next: {item['due_date']}")
            if item['recall']:
                st.text(item['recall'])


def render_review_reminder(user_id):
    reviews.init_reviews()
    due = [r for r in reviews.list_reviews(user_id) if r['is_due']]
    if not due:
        return
    with st.container(border=True):
        st.markdown(f"**📖 {len(due)} material review(s) due across your courses**")
        by_id = {r['id']: r for r in due}
        mid = st.selectbox('Return to a due review', list(by_id),
                           format_func=lambda key: f"{by_id[key]['course_title']} · {by_id[key]['title']}",
                           key='dashboard_material_review')
        if st.button('Review course material', key='dashboard_open_material_review'):
            cid = by_id[mid]['course_id']
            st.session_state['active_course_id'] = cid
            st.session_state['sidebar_course_selector'] = cid
            st.session_state[f'material_review_select_{cid}'] = mid
            st.session_state[f'material_due_only_{cid}'] = False
            st.switch_page('pages/3_Course_Materials.py')
