"""Opt-in outbound incident metadata. No camera pixels or stream addresses."""
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import ipaddress
import json
import logging
import math
from pathlib import Path
import queue
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler
from uuid import NAMESPACE_URL, uuid4, uuid5

from sentinal.config import ROOT
from sentinal.core.incidents import Incident
from .outbox import Outbox, OutboxDestinationError, local_file, private_parent
from .protocol import INGEST_PATH, MAX_BODY, canonical_json, device_identifier, secret_key, sign_request, strict_json, validate_event

log = logging.getLogger(__name__)


def _safe_text(value):
    """A semantic identifier/message must not accidentally contain an endpoint."""
    if not isinstance(value, str) or '://' in value or '@' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Outbound metadata cannot contain camera addresses or credentials')
    return value


@dataclass(frozen=True)
class EdgeConfig:
    server_url: str
    device_id: str
    secret: str = field(repr=False)
    allow_loopback_http: bool = False
    ca_file: str | None = None
    request_timeout_s: float = 4.0
    max_attempts: int = 8
    ingest_path: str = INGEST_PATH

    def __post_init__(self):
        if not isinstance(self.ingest_path,str) or self.ingest_path not in {INGEST_PATH, '/functions/ingest'}:
            raise ValueError('Unsupported signed event endpoint')
        if not isinstance(self.server_url,str) or len(self.server_url)>2048 or any(ord(c)<=32 or ord(c)==127 for c in self.server_url):
            raise ValueError('Enter a valid backend origin')
        parsed = urlsplit(self.server_url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
            raise ValueError('Enter an HTTPS backend origin without credentials, path or query')
        try:
            port = parsed.port
        except ValueError:
            raise ValueError('Invalid backend port') from None
        if port is not None and not 1 <= port <= 65535:
            raise ValueError('Invalid backend port')
        if type(self.allow_loopback_http) is not bool:
            raise ValueError('Loopback development mode must be explicit')
        if parsed.scheme == 'http':
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = False
            if not self.allow_loopback_http or not loopback:
                raise ValueError('HTTPS is required; HTTP is restricted to explicit loopback development')
        device_identifier(self.device_id)
        secret_key(self.secret)
        if type(self.request_timeout_s) not in (int, float) or not math.isfinite(self.request_timeout_s) or not .25 <= self.request_timeout_s <= 10:
            raise ValueError('Request timeout must be .25 to 10 seconds')
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 32:
            raise ValueError('Retry attempts must be 1 to 32')
        if self.ca_file is not None:
            if not isinstance(self.ca_file,str):raise ValueError('The local CA path must be text')
            path = local_file(self.ca_file)
            if not path.is_file():
                raise ValueError('The configured local CA file is unavailable')

    @property
    def endpoint(self):
        return self.server_url.rstrip('/') + self.ingest_path

    @property
    def destination_key(self):
        parsed=urlsplit(self.server_url)
        context={'scheme':parsed.scheme,'host':parsed.hostname.lower(),
            'port':parsed.port or (443 if parsed.scheme=='https' else 80),
            'device_id':self.device_id,'ingest_path':self.ingest_path,'credential_fingerprint':hashlib.sha256(secret_key(self.secret)).hexdigest()}
        return hashlib.sha256(canonical_json(context)).hexdigest()

    def save(self, path=None):
        path = private_parent(path or ROOT / 'config/connected/edge-credentials.json')
        temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.part')
        try:
            with temporary.open('x', encoding='utf-8') as handle:
                temporary.chmod(0o600)
                json.dump(asdict(self), handle, indent=2)
                handle.write('\n')
            temporary.replace(path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path=None):
        path = local_file(path or ROOT / 'config/connected/edge-credentials.json')
        if path.stat().st_mode & 0o077:
            raise ValueError('Device credentials must be readable only by the local owner')
        if path.stat().st_size > 8192:
            raise ValueError('Device credentials file is unexpectedly large')
        value = strict_json(path.read_bytes())
        if not isinstance(value, dict) or set(value) - {entry.name for entry in fields(cls)}:
            raise ValueError('Invalid device connection preferences')
        return cls(**value)


def incident_event(row, device_id, allowed_statuses=('ALERTED',)):
    """Strip local persistence/review fields; do not forward notes or evidence."""
    if not isinstance(row, dict):
        raise ValueError('Expected structured incident metadata')
    if row.get('status') not in allowed_statuses:
        return None
    values = {entry.name: row[entry.name] for entry in fields(Incident) if entry.name in row}
    incident = Incident(**values)
    for key in ('incident_id', 'source_id', 'session_id', 'model_id', 'model_version'):
        _safe_text(values[key])
    if incident.status not in {'OBSERVED', 'CANDIDATE', 'ALERTED'}:
        return None
    event = {'schema_version': 1,
        'event_id': str(uuid5(NAMESPACE_URL, f'sentinal:{device_id}:{incident.incident_id}:{incident.status}')),
        'kind': 'incident', 'device_id': device_id, 'occurred_at': incident.last_seen,
        'incident': incident.to_dict()}
    validate_event(event)
    return event


def heartbeat_event(device_id, health, cameras=(), models=()):
    if not isinstance(health, dict):
        raise ValueError('Expected actual device health')
    allowed_health = {'status', 'processing_fps', 'inference_ms', 'memory_rss_mb', 'message'}
    if set(health) - allowed_health:
        raise ValueError('Unexpected health metadata; no video or camera addresses are accepted')
    health = {name: value for name, value in health.items() if value is not None}
    if 'message' in health:
        _safe_text(health['message'])
    cameras = [dict(value) for value in cameras]
    models = [dict(value) for value in models]
    for camera in cameras:
        for key in ('camera_id', 'name'):
            _safe_text(camera.get(key))
    for model in models:
        for key in ('model_id', 'version'):
            _safe_text(model.get(key))
        for label in model.get('classes', ()):
            _safe_text(label)
    event = {'schema_version': 1, 'event_id': str(uuid4()), 'kind': 'heartbeat',
        'device_id': device_id, 'occurred_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'health': health, 'cameras': cameras, 'models': models}
    validate_event(event)
    return event


@dataclass(frozen=True)
class DeliveryResult:
    accepted: bool
    retryable: bool = False
    retry_after_s: float | None = None
    message: str = ''


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _retry_after(value):
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError, AttributeError):
            return None
    return max(0, min(3600, delay)) if math.isfinite(delay) else None


class HTTPTransport:
    """Fixed-origin verified TLS. Redirects never receive device credentials."""
    def __init__(self, config):
        self.config = config
        context = ssl.create_default_context(cafile=str(local_file(config.ca_file)) if config.ca_file else None)
        self.opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))

    def send(self, pending):
        headers = sign_request(self.config.secret, self.config.device_id, pending.payload)
        headers.update({'Content-Type': 'application/json', 'Accept': 'application/json'})
        request = Request(self.config.endpoint, data=pending.payload, headers=headers, method='POST')
        try:
            with self.opener.open(request, timeout=self.config.request_timeout_s) as response:
                code = response.status
                raw = response.read(8193)
                content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
            if not 200 <= code < 300 or len(raw) > 8192 or content_type != 'application/json':
                return DeliveryResult(False, True, message='Backend returned an invalid acknowledgment')
            value = strict_json(raw)
            if not isinstance(value, dict) or value.get('ok') is not True or value.get('event_id') != pending.event_id:
                return DeliveryResult(False, True, message='Backend acknowledgment does not match the event')
            return DeliveryResult(True)
        except HTTPError as exc:
            # Do not display/retain the response body, which may contain provider
            # diagnostics or confidential information from an upstream service.
            retryable = exc.code in {408, 425, 429} or 500 <= exc.code <= 599
            result = DeliveryResult(False, retryable, _retry_after(exc.headers.get('Retry-After')),
                'Backend request will be retried' if retryable else f'Backend rejected delivery (HTTP {exc.code})')
            exc.close()
            return result
        except (URLError, OSError, TimeoutError, ssl.SSLError):
            return DeliveryResult(False, True, message='Backend connection unavailable; delivery will be retried')
        except (ValueError, TypeError, RecursionError):
            return DeliveryResult(False, True, message='Backend returned an invalid acknowledgment')


class EdgePublisher(threading.Thread):
    """One background owner for disk and network. Constructor never opens either."""
    def __init__(self, config, path=None, *, on_status=None, transport=None,
            queue_size=128, max_events=500, max_age_s=7*86400):
        super().__init__(name='sentinal-outbound-events', daemon=True)
        if not isinstance(config, EdgeConfig):
            raise ValueError('Use validated device connection preferences')
        if type(queue_size) is not int or not 1 <= queue_size <= 1024:
            raise ValueError('Outbound command limit must be 1 to 1024')
        self.config = config
        self.path = local_file(path or ROOT / 'recordings/connected' / ('outbox-'+config.destination_key[:20]+'.sqlite3'))
        self._commands = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._callback = on_status
        self._transport = transport
        self._bounds = (max_events, max_age_s)
        self._state = {'state': 'disabled', 'queued': 0, 'failed': 0, 'submitted': 0,
            'delivered': 0, 'dropped': 0, 'expired': 0, 'last_error': '', 'last_delivery_at': None}

    def status(self):
        with self._lock:
            return dict(self._state)

    def _report(self, **values):
        with self._lock:
            self._state.update(values)
            snapshot = dict(self._state)
        if self._callback is not None:
            try:
                self._callback(snapshot)
            except Exception:
                log.warning('Connected status listener unavailable')

    def submit(self, event):
        if not self.is_alive() or self._stop_event.is_set():
            return False
        validate_event(event)
        if event['device_id'] != self.config.device_id:
            raise ValueError('Event belongs to another device')
        body = canonical_json(event)
        if len(body) > MAX_BODY:
            raise ValueError('Outbound metadata exceeds request size limit')
        # Serialization disconnects mutable UI-owned lists/dicts before enqueue.
        frozen = strict_json(body)
        try:
            self._commands.put_nowait(frozen)
        except queue.Full:
            count = self.status()['dropped'] + 1
            self._report(dropped=count, state='error', last_error='Outbound intake is full; event was not queued')
            return False
        self._report(submitted=self.status()['submitted'] + 1)
        self._wake.set()
        return True

    def submit_incident(self, row):
        event = incident_event(row, self.config.device_id)
        return self.submit(event) if event is not None else False

    def submit_heartbeat(self, health, cameras=(), models=()):
        return self.submit(heartbeat_event(self.config.device_id, health, cameras, models))

    def request_stop(self):
        self._stop_event.set()
        self._wake.set()

    def close(self, timeout=5):
        self.request_stop()
        if self.ident is not None and self is not threading.current_thread():
            self.join(timeout)
        return not self.is_alive()

    def run(self):
        outbox = None
        self._report(state='starting')
        try:
            outbox = Outbox(self.path, *self._bounds, destination=self.config.destination_key)
            transport = self._transport or HTTPTransport(self.config)
            self._report(**outbox.counts())
            maintenance = 0.0
            while True:
                for _ in range(32):
                    try:
                        event = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        outbox.enqueue(event)
                    except (ValueError, OverflowError):
                        self._report(state='error', dropped=self.status()['dropped'] + 1,
                            last_error='Outbound spool rejected the event; inspect capacity and event IDs')
                now = time.time()
                if now - maintenance >= 30:
                    removed = outbox.expire(now)
                    if removed:
                        self._report(expired=self.status()['expired'] + removed,
                            last_error='Expired unsent metadata was removed under outbound retention')
                    maintenance = now
                self._report(**outbox.counts())
                # Stop opts out of further transmissions. Drain already accepted
                # UI commands to disk, so they can resume after explicit reenable.
                if self._stop_event.is_set():
                    if self._commands.empty():
                        break
                    continue
                pending = outbox.ready(now)
                if pending is None:
                    self._wake.wait(.25)
                    self._wake.clear()
                    continue
                result = transport.send(pending)
                if result.accepted:
                    outbox.accepted(pending.event_id)
                    self._report(state='connected', delivered=self.status()['delivered'] + 1,
                        last_error='', last_delivery_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
                elif result.retryable and pending.attempts + 1 < self.config.max_attempts:
                    delay = result.retry_after_s if result.retry_after_s is not None else min(300, 2 ** pending.attempts)
                    delay = max(.25, delay)
                    outbox.retry(pending.event_id, delay, result.message)
                    self._report(state='retrying', last_error=result.message)
                else:
                    outbox.failed(pending.event_id, result.message)
                    self._report(state='error', last_error=result.message or 'Retry limit reached; event remains in failed spool')
                self._report(**outbox.counts())
        except OutboxDestinationError as exc:
            self._report(state='error',last_error=str(exc))
        except Exception:
            log.exception('Outbound metadata owner stopped')
            self._report(state='error', last_error='Outbound metadata service stopped; inspect connection preferences and local storage')
        finally:
            if outbox is not None:
                outbox.close()
            if self._stop_event.is_set():
                self._report(state='stopped')
