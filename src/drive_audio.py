"""Private Drive blobs; credentials live only in Windows Credential Manager."""
import hashlib
import io
import json
from pathlib import Path
from src import database

SCOPE = 'https://www.googleapis.com/auth/drive.file'
LIMIT = 200 * 1024**2

class DriveError(ValueError):
    pass

def vault():
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()

def namespace(user_id):
    instance = hashlib.sha256(str(Path(database.DB_PATH).resolve()).encode()).hexdigest()[:16]
    return f'StudyForge.Drive.{instance}.{int(user_id)}'

def read_secret(user_id, kind):
    try:
        return vault().get_password(namespace(user_id), kind)
    except Exception:
        raise DriveError('Windows Credential Manager is unavailable. Install the Drive dependencies and run locally on Windows.') from None

def write_secret(user_id, kind, value):
    vault().set_password(namespace(user_id), kind, value)

def configured(user_id):
    return bool(read_secret(user_id, 'token'))

def configure(user_id, content):
    try:
        config = json.loads(content)
        client = config['installed']
        if not client['client_id'] or not client['client_secret']:
            raise ValueError()
        # Never accept caller-controlled OAuth endpoints.
        client['auth_uri'] = 'https://accounts.google.com/o/oauth2/auth'
        client['token_uri'] = 'https://oauth2.googleapis.com/token'
        clean = {'installed': client}
    except (ValueError, KeyError, TypeError):
        raise DriveError('Upload the Google OAuth client JSON for a Desktop app.') from None
    write_secret(user_id, 'client', json.dumps(clean))

def connect(user_id):
    from google_auth_oauthlib.flow import InstalledAppFlow
    config = read_secret(user_id, 'client')
    if not config:
        raise DriveError('Upload your Desktop app OAuth client JSON first.')
    try:
        flow = InstalledAppFlow.from_client_config(json.loads(config), [SCOPE], autogenerate_code_verifier=True)
        credentials = flow.run_local_server(host='127.0.0.1', port=0, timeout_seconds=120,
            access_type='offline', prompt='consent', authorization_prompt_message='',
            success_message='StudyForge connected. You can close this tab.')
        if not credentials.refresh_token:
            raise ValueError()
        write_secret(user_id, 'token', credentials.to_json())
    except Exception:
        raise DriveError('Google connection did not finish. Retry and approve access in the browser on this Windows computer.') from None

def disconnect(user_id):
    # Revoke at Google too; do not claim success if revocation fails.
    from google.auth.transport.requests import AuthorizedSession
    creds = credentials(user_id)
    response = AuthorizedSession(creds).post('https://oauth2.googleapis.com/revoke',
        data={'token': creds.refresh_token or creds.token}, timeout=30)
    if response.status_code not in (200, 400):
        raise DriveError('Google could not revoke access. Try again later.')
    vault().delete_password(namespace(user_id), 'token')

def credentials(user_id):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    raw = read_secret(user_id, 'token')
    if not raw:
        raise DriveError('Connect Google Drive before saving or playing Drive recordings.')
    try:
        creds = Credentials.from_authorized_user_info(json.loads(raw), [SCOPE])
        if not creds.valid:
            creds.refresh(Request())
            write_secret(user_id, 'token', creds.to_json())
        return creds
    except Exception:
        raise DriveError('Google authorization expired or was revoked. Reconnect Google Drive.') from None

def service(user_id):
    from googleapiclient.discovery import build
    import google_auth_httplib2
    import httplib2
    return build('drive', 'v3', http=google_auth_httplib2.AuthorizedHttp(credentials(user_id),
        http=httplib2.Http(timeout=60)), cache_discovery=False)

def upload(user_id, name, mime, content):
    from googleapiclient.http import MediaIoBaseUpload
    try:
        api = service(user_id)
        result = api.files().create(body={'name': 'StudyForge ' + name},
            media_body=MediaIoBaseUpload(io.BytesIO(content), mimetype=mime, chunksize=4*1024**2, resumable=True),
            fields='id,md5Checksum,size').execute()
        if int(result['size']) != len(content) or result['md5Checksum'] != hashlib.md5(content).hexdigest():
            delete(user_id, result['id'])
            raise DriveError('Drive upload verification failed. The recording was not saved.')
        return result['id']
    except DriveError:
        raise
    except Exception:
        raise DriveError('Drive upload failed. Check connection, available storage and Google authorization; then retry.') from None

def download(user_id, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    try:
        api = service(user_id)
        metadata = api.files().get(fileId=file_id, fields='size,md5Checksum').execute()
        if int(metadata['size']) > LIMIT:
            raise DriveError('This Drive recording exceeds the 200 MB playback limit.')
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, api.files().get_media(fileId=file_id), chunksize=4*1024**2)
        done = False
        while not done:
            _, done = downloader.next_chunk()
            if buffer.tell() > LIMIT:
                raise DriveError('This Drive recording exceeds the 200 MB playback limit.')
        content = buffer.getvalue()
        if len(content) != int(metadata['size']) or hashlib.md5(content).hexdigest() != metadata['md5Checksum']:
            raise DriveError('Drive download verification failed; retry playback.')
        return content
    except DriveError:
        raise
    except Exception:
        raise DriveError('Drive recording is unavailable. Check the owner’s connection and that the file still exists.') from None

def delete(user_id, file_id):
    service(user_id).files().delete(fileId=file_id).execute()
