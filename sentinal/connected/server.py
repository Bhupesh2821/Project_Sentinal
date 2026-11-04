"""Authenticated same-origin web/API service. No source capture starts here."""
import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import hmac
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import mimetypes
from pathlib import Path
import re
import signal
import ssl
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit
from sentinal.config import ROOT
from .protocol import (INGEST_PATH, PREVIEW_PATH, MAX_BODY, NONCE_RE, ProtocolError,
                       canonical_json, device_identifier, signing_message, strict_json, timestamp)
from .store import Store, StoreError, SESSION_SECONDS

LOG = logging.getLogger(__name__)
COOKIE = 'sentinal_session'


def csrf_token(token):
    return hmac.new(token.encode('utf-8'), b'SENTINAL browser CSRF v1', hashlib.sha256).hexdigest()


def loopback(host):
    if host.casefold() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ConnectedServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 32

    def __init__(self, address, store, web_root, tls=False, public_origin=None, allow_local_preview=False):
        self.store = store
        self.web_root = Path(web_root).resolve()
        self.tls = tls
        self.public_origin = public_origin
        self.allow_local_preview = allow_local_preview
        self.previews = {}
        self.preview_lock = threading.Lock()
        self._request_slots = threading.BoundedSemaphore(32)
        super().__init__(address, Handler)
        self.allowed_hosts = {f'{address[0]}:{self.server_port}', f'localhost:{self.server_port}', f'127.0.0.1:{self.server_port}'} if loopback(address[0]) else {f'{address[0]}:{self.server_port}'}
        if public_origin:
            self.allowed_hosts.add(urlsplit(public_origin).netloc)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def preview_available(self, organization, camera_id):
        with self.preview_lock:
            entry = self.previews.get((organization, camera_id))
            return bool(entry and time.time() - entry['received'] <= 3)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'SENTINAL'
    sys_version = ''

    def log_message(self, fmt, *args):
        # Request paths, bodies, cookie values and credentials stay out of logs.
        LOG.debug('HTTP request completed from %s', self.client_address[0])

    def _headers(self, status, content_type='application/json; charset=utf-8', length=0, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; worker-src 'self'; manifest-src 'self'")
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if self.server.tls or self.server.public_origin:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')
        if status == 429:
            self.send_header('Retry-After', '60')
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def _json(self, value, status=200, extra=None):
        raw = canonical_json(value)
        self._headers(status, length=len(raw), extra=extra)
        self.wfile.write(raw)

    def _body(self, maximum=MAX_BODY):
        if self.headers.get('Transfer-Encoding') is not None:
            raise StoreError('Transfer encoding is not accepted', 400)
        lengths = self.headers.get_all('Content-Length') or []
        if len(lengths) != 1 or not lengths[0].isdigit():
            raise StoreError('Content-Length is required', 411)
        length = int(lengths[0])
        if length < 1 or length > maximum:
            self.close_connection = True
            raise StoreError('Request body exceeds its size limit', 413)
        if self.headers.get_content_type() != 'application/json':
            raise StoreError('Use application/json', 415)
        data = self.rfile.read(length)
        if len(data) != length:
            raise StoreError('Incomplete request body')
        return data

    def _cookie(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            return cookies[COOKIE].value if COOKIE in cookies else ''
        except Exception:
            return ''

    def _user(self, admin=False, mutation=False):
        token = self._cookie()
        user = self.server.store.session(token)
        if user is None:
            raise StoreError('Sign in to access this information', 401)
        if admin and user['role'] != 'admin':
            raise StoreError('Administrator access required', 403)
        if mutation:
            self._check_origin()
            supplied = self.headers.get('X-CSRF-Token', '')
            if not hmac.compare_digest(supplied, csrf_token(token)):
                raise StoreError('Refresh the session before making changes', 403)
        return user

    def _check_host(self):
        if len(self.headers.get_all('Host') or []) != 1 or self.headers.get('Host') not in self.server.allowed_hosts:
            raise StoreError('Unrecognized service host', 421)

    def _check_origin(self):
        host = self.headers.get('Host', '')
        expected = self.server.public_origin or ('https' if self.server.tls else 'http') + '://' + host
        if self.headers.get('Origin') != expected or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise StoreError('This change must originate from the SENTINAL dashboard', 403)

    def _edge_auth(self, body, path):
        names = ('X-Sentinal-Device', 'X-Sentinal-Timestamp', 'X-Sentinal-Nonce', 'X-Sentinal-Signature')
        if any(len(self.headers.get_all(name) or []) != 1 for name in names):
            raise StoreError('Signed device authentication is required', 401)
        device_id, stamp, nonce, signature = (self.headers.get(name) for name in names)
        try:
            device_identifier(device_id)
            if not stamp.isdigit() or len(stamp) > 12 or abs(time.time() - int(stamp)) > 90 or not NONCE_RE.fullmatch(nonce) or not re.fullmatch(r'[0-9a-f]{64}', signature):
                raise ValueError()
        except (ValueError, TypeError):
            raise StoreError('Device authentication expired or is invalid', 401) from None
        device = self.server.store.device(device_id)
        if not device:
            raise StoreError('Device authentication is invalid', 401)
        expected = hmac.new(device['signing_key'], signing_message(device_id, stamp, nonce, body, path), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise StoreError('Device authentication is invalid', 401)
        self.server.store.rate_limit('device:' + device_id, 300, 60)
        self.server.store.accept_nonce(device_id, nonce)
        return device

    def do_OPTIONS(self):
        # Private data never participates in cross-origin reads or writes.
        self._json({'error': 'Cross-origin access is disabled'}, 403)

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def do_PATCH(self):
        self._dispatch('PATCH')

    def _dispatch(self, method):
        try:
            self._check_host()
            self.server.store.rate_limit('http:' + self.client_address[0], 600, 60)
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or len(self.path) > 2048:
                raise StoreError('Invalid request target')
            path = unquote(parsed.path)
            if method == 'POST' and path in {INGEST_PATH, PREVIEW_PATH}:
                if parsed.query:
                    raise StoreError('Signed endpoints do not accept query parameters')
                if path == PREVIEW_PATH and not self.server.allow_local_preview:
                    raise StoreError('Local preview is disabled; no video is transferred', 409)
                raw = self._body(524288 if path == PREVIEW_PATH else MAX_BODY)
                device = self._edge_auth(raw, path)
                if path == PREVIEW_PATH:
                    self._preview_upload(strict_json(raw), device)
                else:
                    result = self.server.store.ingest(strict_json(raw), hashlib.sha256(raw).hexdigest(), device)
                    self._json(result, 200 if result['duplicate'] else 201)
                return
            if method == 'GET' and path == '/api/health':
                self._json({'status': 'ok', 'service': 'SENTINAL connected API', 'schema_version': 1, 'local_preview_enabled': self.server.allow_local_preview})
                return
            if method == 'POST' and path == '/api/login':
                self._check_origin()
                value = strict_json(self._body(4096))
                if not isinstance(value, dict) or set(value) != {'username', 'password'}:
                    raise StoreError('Username and password are required')
                token, user = self.server.store.login(value['username'], value['password'], self.client_address[0])
                secure = '; Secure' if self.server.tls or self.server.public_origin else ''
                self._json({'user': user, 'csrf_token': csrf_token(token)}, extra={'Set-Cookie': f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}{secure}'})
                return
            if path.startswith('/api/'):
                self._api(method, path, parsed.query)
            elif method == 'GET':
                self._static(path)
            else:
                raise StoreError('Endpoint not found', 404)
        except (StoreError, ProtocolError, ValueError) as exc:
            self.close_connection = True
            self._json({'error': str(exc)}, getattr(exc, 'status', 400))
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            LOG.exception('Connected API operation failed')
            self.close_connection = True
            self._json({'error': 'The local service could not complete this request'}, 500)

    def _api(self, method, path, query):
        user = self._user(mutation=method != 'GET')
        organization = user['organization']
        if path == '/api/session' and method == 'GET':
            self._json({'user': user, 'csrf_token': csrf_token(self._cookie())})
        elif path == '/api/logout' and method == 'POST':
            if self.headers.get('Content-Length') not in {None, '0'}:
                if strict_json(self._body(1024)) != {}:
                    raise StoreError('Logout does not accept additional fields')
            self.server.store.logout(self._cookie())
            self._json({'ok': True}, extra={'Set-Cookie': f'{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
        elif method == 'GET' and path == '/api/summary':
            self._json(self.server.store.summary(organization))
        elif method == 'GET' and path == '/api/devices':
            self._json({'items': self.server.store.devices(organization)})
        elif method == 'POST' and path.startswith('/api/devices/') and path.endswith('/disable'):
            self._user(admin=True)
            ident = path.removeprefix('/api/devices/').removesuffix('/disable')
            if self.headers.get('Content-Length') not in {None, '0'} and strict_json(self._body(1024)) != {}:
                raise StoreError('Device disable does not accept additional fields')
            result = self.server.store.disable_device(user, ident)
            with self.server.preview_lock:
                cameras = {camera['camera_id'] for camera in self.server.store.cameras(organization) if camera['device_id'] == ident}
                self.server.previews = {key: value for key, value in self.server.previews.items() if not (key[0] == organization and key[1] in cameras)}
            self._json(result)
        elif method == 'GET' and path == '/api/cameras':
            items = self.server.store.cameras(organization)
            for camera in items:
                camera['preview_available'] = self.server.allow_local_preview and camera['status'] in {'online', 'running', 'paused'} and self.server.preview_available(organization, camera['camera_id'])
            self._json({'items': items, 'local_preview_enabled': self.server.allow_local_preview})
        elif method == 'GET' and path == '/api/models':
            self._json({'items': self.server.store.models(organization)})
        elif method == 'GET' and path == '/api/incidents':
            parsed = parse_qs(query, keep_blank_values=True, max_num_fields=8)
            if any(len(value) != 1 for value in parsed.values()):
                raise StoreError('Duplicate filters are not accepted')
            self._json({'items': self.server.store.incidents(organization, {key: value[0] for key, value in parsed.items()})})
        elif path.startswith('/api/incidents/'):
            tail = path.removeprefix('/api/incidents/').split('/')
            ident = tail[0]
            if method == 'GET' and len(tail) == 1:
                row = self.server.store.incident(organization, ident)
                if not row:
                    raise StoreError('Incident not found', 404)
                self._json(row)
            elif method == 'GET' and tail[1:] == ['audit']:
                self._json({'items': self.server.store.audit(organization, ident)})
            elif method == 'POST' and tail[1:] == ['review']:
                value = strict_json(self._body(8192))
                if not isinstance(value, dict) or set(value) != {'status', 'note', 'expected_version'}:
                    raise StoreError('Review requires status, note and expected version')
                self._json(self.server.store.review(user, ident, value['status'], value['note'], value['expected_version']))
            else:
                raise StoreError('Endpoint not found', 404)
        elif path.startswith('/api/cameras/') and path.endswith('/preview.jpg') and method == 'GET':
            self._preview_get(organization, path.removeprefix('/api/cameras/').removesuffix('/preview.jpg'))
        elif path == '/api/users':
            self._user(admin=True)
            if method == 'GET':
                self._json({'items': self.server.store.users(organization)})
            elif method == 'POST':
                value = strict_json(self._body(4096))
                if not isinstance(value, dict) or set(value) != {'username', 'password', 'role'}:
                    raise StoreError('Username, password and role are required')
                self._json(self.server.store.create_user(value['username'], value['password'], value['role'], organization), 201)
            else:
                raise StoreError('Endpoint not found', 404)
        elif path == '/api/audit' and method == 'GET':
            self._user(admin=True)
            self._json({'items': self.server.store.audit(organization)})
        elif path == '/api/settings':
            self._user(admin=True)
            if method == 'GET':
                self._json(self.server.store.settings(organization))
            elif method in {'POST', 'PATCH'}:
                self._json(self.server.store.update_settings(user, strict_json(self._body(4096))))
            else:
                raise StoreError('Endpoint not found', 404)
        else:
            raise StoreError('Endpoint not found', 404)

    def _preview_upload(self, value, device):
        if not isinstance(value, dict) or set(value) != {'device_id', 'camera_id', 'captured_at', 'jpeg_base64'} or value['device_id'] != device['device_id']:
            raise StoreError('Invalid local preview metadata')
        timestamp(value['captured_at'])
        captured = datetime.fromisoformat(value['captured_at']).timestamp()
        if abs(time.time() - captured) > 3:
            raise StoreError('Preview frame is stale', 409)
        camera = next((camera for camera in self.server.store.cameras(device['organization']) if camera['camera_id'] == value['camera_id']), None)
        if not camera or camera['device_id'] != device['device_id'] or camera['status'] not in {'online', 'running', 'paused'}:
            raise StoreError('A currently active camera owned by this device is required', 404)
        try:
            data = base64.b64decode(value['jpeg_base64'], validate=True)
        except (ValueError, TypeError):
            raise StoreError('Invalid JPEG encoding') from None
        if not 4 < len(data) <= 393216 or not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
            raise StoreError('Only a bounded JPEG preview is accepted')
        with self.server.preview_lock:
            now = time.time()
            self.server.previews = {key: entry for key, entry in self.server.previews.items() if now - entry['received'] <= 3}
            key = (device['organization'], value['camera_id'])
            if key not in self.server.previews and len(self.server.previews) >= 32:
                raise StoreError('Local preview capacity is busy', 429)
            self.server.previews[key] = {'received': now, 'captured_at': value['captured_at'], 'jpeg': data}
        self._json({'ok': True, 'camera_id': value['camera_id'], 'expires_in_s': 3})

    def _preview_get(self, organization, camera_id):
        if not self.server.allow_local_preview:
            raise StoreError('Local preview is disabled', 404)
        camera = next((camera for camera in self.server.store.cameras(organization) if camera['camera_id'] == camera_id), None)
        if not camera or camera['status'] not in {'online', 'running', 'paused'}:
            raise StoreError('No active authorized preview', 404)
        with self.server.preview_lock:
            entry = self.server.previews.get((organization, camera_id))
            if not entry or time.time() - entry['received'] > 3:
                self.server.previews.pop((organization, camera_id), None)
                raise StoreError('No fresh preview is available', 404)
            data, captured = entry['jpeg'], entry['captured_at']
        self._headers(200, 'image/jpeg', len(data), {'X-Sentinal-Captured-At': captured})
        self.wfile.write(data)

    def _static(self, path):
        # An explicit allowlist prevents source/config/database/download exposure.
        aliases = {'/': 'index.html', '/app': 'app.html', '/app/': 'app.html', '/login': 'app.html'}
        relative = aliases.get(path, path.lstrip('/'))
        allowed = {'index.html', 'app.html', 'styles.css', 'app.js', 'public.js', 'manifest.webmanifest', 'sw.js', 'icon.svg', 'offline.html', 'demo.png'}
        if relative not in allowed:
            raise StoreError('Page not found', 404)
        target = self.server.web_root / relative
        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(self.server.web_root):
            raise StoreError('Page not available', 404)
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if target.suffix in {'.html', '.css', '.js', '.svg', '.webmanifest'}:
            content_type += '; charset=utf-8'
        extra = {'Service-Worker-Allowed': '/'} if relative == 'sw.js' else {}
        self._headers(200, content_type, len(data), extra)
        self.wfile.write(data)


def build_server(store, host='127.0.0.1', port=0, web_root=None, tls_cert=None, tls_key=None, public_origin=None, allow_local_preview=False):
    if not isinstance(host, str) or not host:
        raise ValueError('Explicit host is required')
    if bool(tls_cert) != bool(tls_key):
        raise ValueError('TLS certificate and private key are both required')
    if not loopback(host) and not tls_cert:
        raise ValueError('Non-loopback serving requires TLS; no unrestricted HTTP exposure is allowed')
    if public_origin:
        origin = urlsplit(public_origin)
        if origin.scheme != 'https' or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username or origin.password:
            raise ValueError('Public origin must be an HTTPS origin without credentials or path')
    if allow_local_preview and (not loopback(host) or public_origin):
        raise ValueError('Preview is available only on the explicit local loopback service')
    server = ConnectedServer((host, port), store, web_root or ROOT / 'web', bool(tls_cert), public_origin, allow_local_preview)
    if tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls_cert, tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def _database(path):
    directory = Path(path).resolve()
    if not directory.is_relative_to(ROOT):
        raise ValueError('Connected data must remain in the project folder')
    return directory / 'server.sqlite3'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    for name in ('init', 'device', 'serve'):
        item = sub.add_parser(name)
        item.add_argument('--data-dir', default=str(ROOT / 'recordings/connected'))
        if name == 'init':
            item.add_argument('--username', required=True)
            item.add_argument('--password-file')
            item.add_argument('--role', choices=sorted(ROLES), default='admin')
            item.add_argument('--organization', default='default')
        elif name == 'device':
            item.add_argument('--device-id', required=True)
            item.add_argument('--name', required=True)
            item.add_argument('--secret-file', required=True)
            item.add_argument('--organization', default='default')
        else:
            item.add_argument('--host', default='127.0.0.1')
            item.add_argument('--port', type=int, default=8765)
            item.add_argument('--tls-cert')
            item.add_argument('--tls-key')
            item.add_argument('--public-origin')
            item.add_argument('--allow-local-preview', action='store_true')
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    store = Store(_database(args.data_dir))
    try:
        if args.command == 'init':
            password = Path(args.password_file).read_text().rstrip('\r\n') if args.password_file else getpass.getpass('New SENTINAL account password (12+ characters): ')
            value = store.create_user(args.username, password, args.role, args.organization)
            print(json.dumps({'created': value}))
        elif args.command == 'device':
            value = store.register_device(args.device_id, args.name, Path(args.secret_file).read_text().strip(), args.organization)
            print(json.dumps({'registered': value}))
        else:
            server = build_server(store, args.host, args.port, tls_cert=args.tls_cert, tls_key=args.tls_key, public_origin=args.public_origin, allow_local_preview=args.allow_local_preview)
            print(f'SENTINAL website/dashboard listening on {"https" if server.tls else "http"}://{args.host}:{server.server_port}; camera capture remains off until explicitly started.', flush=True)
            try:
                server.serve_forever(poll_interval=.2)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    finally:
        store.close()
    return 0


from .store import ROLES
if __name__ == '__main__':
    raise SystemExit(main())
