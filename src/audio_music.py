"""Private background music and ordered playlists, separate from study telemetry."""
from pathlib import Path

import streamlit as st
from streamlit import runtime
from src.audio_study import connection, MIMES

MAX_BYTES = 50 * 1024 * 1024


def init_music():
    with connection() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS audio_music_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT NOT NULL, mime TEXT NOT NULL, content BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS audio_music_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT NOT NULL, UNIQUE(user_id, name));
        CREATE TABLE IF NOT EXISTS audio_music_items (
            playlist_id INTEGER NOT NULL, track_id INTEGER NOT NULL,
            position INTEGER NOT NULL, PRIMARY KEY(playlist_id, position));
        ''')


def tracks(user_id):
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id,title,mime FROM audio_music_tracks WHERE user_id=? ORDER BY id', (user_id,))]


def upload_tracks(user_id, files):
    prepared = []
    if not files or len(files) > 20:
        raise ValueError('Choose between 1 and 20 music files.')
    for name, content in files:
        mime = MIMES.get(Path(name).suffix.lower())
        if not mime or not content or len(content) > MAX_BYTES:
            raise ValueError('Use nonempty MP3, WAV, M4A or OGG files up to 50 MB each.')
        prepared.append((user_id, Path(name).name, mime, content))
    with connection() as conn:
        conn.executemany('INSERT INTO audio_music_tracks(user_id,title,mime,content) VALUES(?,?,?,?)', prepared)


def playlists(user_id):
    with connection() as conn:
        result = [dict(row) for row in conn.execute(
            'SELECT id,name FROM audio_music_playlists WHERE user_id=? ORDER BY name', (user_id,))]
        for playlist in result:
            playlist['tracks'] = [row['track_id'] for row in conn.execute(
                'SELECT track_id FROM audio_music_items WHERE playlist_id=? ORDER BY position', (playlist['id'],))]
        return result


def save_playlist(user_id, name, track_ids):
    name = name.strip()
    if not name or len(name) > 100 or not 1 <= len(track_ids) <= 20:
        raise ValueError('Give the playlist a name (up to 100 characters) and choose 1–20 tracks.')
    with connection() as conn:
        owned = {row['id'] for row in conn.execute('SELECT id FROM audio_music_tracks WHERE user_id=?', (user_id,))}
        if any(track_id not in owned for track_id in track_ids):
            raise ValueError('Choose music from your own library.')
        conn.execute('INSERT OR IGNORE INTO audio_music_playlists(user_id,name) VALUES(?,?)', (user_id, name))
        playlist_id = conn.execute('SELECT id FROM audio_music_playlists WHERE user_id=? AND name=?', (user_id, name)).fetchone()['id']
        conn.execute('DELETE FROM audio_music_items WHERE playlist_id=?', (playlist_id,))
        conn.executemany('INSERT INTO audio_music_items VALUES(?,?,?)',
                         [(playlist_id, track_id, i) for i, track_id in enumerate(track_ids)])


def delete_playlist(user_id, playlist_id):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM audio_music_playlists WHERE id=? AND user_id=?', (playlist_id, user_id)).fetchone():
            raise ValueError('Playlist is not available.')
        conn.execute('DELETE FROM audio_music_items WHERE playlist_id=?', (playlist_id,))
        conn.execute('DELETE FROM audio_music_playlists WHERE id=? AND user_id=?', (playlist_id, user_id))


def delete_track(user_id, track_id):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM audio_music_tracks WHERE id=? AND user_id=?', (track_id, user_id)).fetchone():
            raise ValueError('Music is not available.')
        conn.execute('DELETE FROM audio_music_items WHERE track_id=?', (track_id,))
        conn.execute('DELETE FROM audio_music_tracks WHERE id=? AND user_id=?', (track_id, user_id))


def music_bytes(user_id, track_id):
    with connection() as conn:
        row = conn.execute('SELECT content FROM audio_music_tracks WHERE id=? AND user_id=?', (track_id, user_id)).fetchone()
        if row is None:
            raise ValueError('Music is not available.')
        return bytes(row['content'])


def media_tracks(user_id, selected):
    # Keep only the active selection in session memory; never a cross-user cache.
    owned = {track['id']: track for track in tracks(user_id)}
    selected = [track_id for track_id in selected if track_id in owned]
    cache = st.session_state.setdefault('background_music_bytes', {})
    keep = {(user_id, track_id) for track_id in selected}
    for key in list(cache):
        if key not in keep:
            del cache[key]
    result = []
    for track_id in selected:
        key = (user_id, track_id)
        if key not in cache:
            cache[key] = music_bytes(user_id, track_id)
        track = owned[track_id]
        src = runtime.get_instance().media_file_mgr.add(cache[key], track['mime'], f'music_{user_id}_{track_id}')
        result.append({**track, 'src': src})
    return result


def render_music_library(user_id):
    init_music()
    library = tracks(user_id)
    by_id = {track['id']: track for track in library}
    saved = playlists(user_id)
    with st.expander('Background music · uploads and saved playlists'):
        st.caption('Your music is private and available across courses. Music never counts as study listening. Changes here may pause playback.')
        with st.form(f'music_upload_{user_id}', clear_on_submit=True):
            files = st.file_uploader('Add instrumental tracks', type=['mp3','wav','m4a','ogg'], accept_multiple_files=True, max_upload_size=50, key=f'music_files_{user_id}')
            if st.form_submit_button('Save music'):
                try:
                    upload_tracks(user_id, [(file.name, file.getvalue()) for file in files])
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        st.caption('Up to 20 files per upload, 50 MB each. Select playlist tracks in the order you want them played.')
        if library:
            editable = [None] + [p['id'] for p in saved]
            if st.session_state.get(f'music_edit_{user_id}') not in editable:
                st.session_state[f'music_edit_{user_id}'] = None
            edit = st.selectbox('Create or edit playlist', editable,
                                format_func=lambda pid: 'New playlist' if pid is None else next(p['name'] for p in saved if p['id']==pid), key=f'music_edit_{user_id}')
            current = next((p for p in saved if p['id']==edit), None)
            with st.form(f'music_playlist_{user_id}_{edit}'):
                name = st.text_input('Playlist name', value=current['name'] if current else '', max_chars=100)
                ids = st.multiselect('Tracks in playback order', list(by_id), default=current['tracks'] if current else [], format_func=lambda tid: by_id[tid]['title'])
                st.caption(' → '.join(by_id[tid]['title'] for tid in ids))
                if st.form_submit_button('Save playlist'):
                    try:
                        save_playlist(user_id, name, ids)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            if current and st.button('Delete this playlist', key=f'music_delete_playlist_{user_id}'):
                delete_playlist(user_id, current['id'])
                st.rerun()
            if st.session_state.get(f'music_remove_{user_id}') not in by_id:
                st.session_state[f'music_remove_{user_id}'] = None
            remove = st.selectbox('Remove music from library', [None] + list(by_id), format_func=lambda tid: 'Choose a track' if tid is None else by_id[tid]['title'], key=f'music_remove_{user_id}')
            if remove is not None and st.button('Remove selected music', key=f'music_delete_track_{user_id}'):
                delete_track(user_id, remove)
                st.rerun()
    options = ['off'] + [f'p:{p["id"]}' for p in saved if p['tracks']] + [f't:{t["id"]}' for t in library]
    labels = {'off': 'No background music', **{f'p:{p["id"]}': f'Playlist · {p["name"]}' for p in saved}, **{f't:{t["id"]}': f'Track · {t["title"]}' for t in library}}
    if st.session_state.get(f'music_source_{user_id}', 'off') not in options:
        st.session_state[f'music_source_{user_id}'] = 'off'
    selected = st.selectbox('Music source', options, format_func=labels.get, key=f'music_source_{user_id}')
    if selected.startswith('p:'):
        return next(p['tracks'] for p in saved if p['id']==int(selected[2:]))
    return [int(selected[2:])] if selected.startswith('t:') else []
