"""Versioned, metadata-only edge protocol shared by client and server."""
from datetime import datetime
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from uuid import UUID
from sentinal.core.incidents import Incident

INGEST_PATH = '/api/edge/events'
PREVIEW_PATH = '/api/edge/preview'
MAX_BODY = 131072
DEVICE_RE = re.compile(r'^[A-Za-z0-9_.-]{1,80}$')
NONCE_RE = re.compile(r'^[0-9a-f]{32,128}$')
CORE_FIELDS = {'schema_version', 'event_id', 'kind', 'device_id', 'occurred_at'}


class ProtocolError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def device_identifier(value):
    if not isinstance(value, str) or not DEVICE_RE.fullmatch(value):
        raise ProtocolError('Device ID must contain 1–80 letters, digits, underscores, dots or hyphens')
    return value


def text(value, label, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ProtocolError(label + ' is invalid')
    return value


def timestamp(value):
    try:
        text(value, 'Timestamp', 64)
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return value
    except (TypeError, ValueError):
        raise ProtocolError('A timezone-aware timestamp is required') from None


def secret_key(secret):
    if not isinstance(secret, str) or len(secret) < 32 or len(secret) > 1024:
        raise ProtocolError('Device secret requires at least 32 characters')
    return hashlib.sha256(secret.encode('utf-8')).digest()


def signing_message(device_id, timestamp_value, nonce, body, path=INGEST_PATH):
    if path not in {INGEST_PATH, PREVIEW_PATH}:
        raise ProtocolError('Unsupported signed endpoint')
    return ('SENTINAL1\nPOST\n' + path + '\n' + device_id + '\n' + timestamp_value + '\n' + nonce + '\n' + hashlib.sha256(body).hexdigest()).encode('utf-8')


def sign_request(secret, device_id, body, timestamp=None, nonce=None, *, path=INGEST_PATH):
    device_identifier(device_id)
    if not isinstance(body, bytes) or len(body) > (524288 if path == PREVIEW_PATH else MAX_BODY):
        raise ProtocolError('Expected bounded request bytes')
    stamp = str(int(time.time())) if timestamp is None else str(timestamp)
    nonce = secrets.token_hex(16) if nonce is None else nonce
    if not stamp.isdigit() or not NONCE_RE.fullmatch(nonce):
        raise ProtocolError('Invalid signing timestamp or nonce')
    signature = hmac.new(secret_key(secret), signing_message(device_id, stamp, nonce, body, path), hashlib.sha256).hexdigest()
    return {'X-Sentinal-Device': device_id, 'X-Sentinal-Timestamp': stamp, 'X-Sentinal-Nonce': nonce, 'X-Sentinal-Signature': signature}


def strict_json(body):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ProtocolError('Duplicate JSON member')
            result[key] = value
        return result
    try:
        return json.loads(body.decode('utf-8'), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError('Non-finite JSON number')))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ProtocolError('A valid UTF-8 JSON document is required') from None


def _number(value, label, high=1000000):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > high:
        raise ProtocolError(label + ' must be a bounded nonnegative number')
    return value


def validate_event(value):
    if not isinstance(value, dict):
        raise ProtocolError('Event must be an object')
    kind = value.get('kind')
    extra = {'incident'} if kind == 'incident' else {'health', 'cameras', 'models'} if kind == 'heartbeat' else set()
    if not extra or set(value) != CORE_FIELDS | extra:
        raise ProtocolError('Unexpected event fields or kind')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ProtocolError('Unsupported schema version')
    try:
        if not isinstance(value['event_id'], str) or str(UUID(value['event_id'])) != value['event_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ProtocolError('Event ID must be a canonical UUID') from None
    device_identifier(value['device_id'])
    timestamp(value['occurred_at'])
    if kind == 'incident':
        raw = value['incident']
        if not isinstance(raw, dict):
            raise ProtocolError('Incident must be an object')
        try:
            incident = Incident(**raw)
        except (TypeError, ValueError, OverflowError, AttributeError):
            raise ProtocolError('Invalid incident metadata') from None
        if incident.status not in {'OBSERVED', 'CANDIDATE', 'ALERTED'}:
            raise ProtocolError('Edge devices cannot perform human review')
        if incident.status == 'ALERTED' and incident.alerted_at is None:
            raise ProtocolError('An alert requires its actual alert timestamp')
    else:
        health = value['health']
        allowed = {'status', 'processing_fps', 'inference_ms', 'memory_rss_mb', 'message'}
        if not isinstance(health, dict) or set(health) - allowed or health.get('status') not in {'idle', 'running', 'error', 'reconnecting'}:
            raise ProtocolError('Invalid device health')
        for name in ('processing_fps', 'inference_ms', 'memory_rss_mb'):
            if name in health:
                _number(health[name], name)
        if 'message' in health:
            text(health['message'], 'Health message', 240)
        if not isinstance(value['cameras'], list) or len(value['cameras']) > 32 or not isinstance(value['models'], list) or len(value['models']) > 16:
            raise ProtocolError('Heartbeat list exceeds device limits')
        cameras = set()
        for camera in value['cameras']:
            if not isinstance(camera, dict) or set(camera) - {'camera_id', 'name', 'status', 'last_frame_at'} or not {'camera_id', 'name', 'status'} <= set(camera):
                raise ProtocolError('Invalid camera metadata; addresses and credentials are not accepted')
            text(camera['camera_id'], 'Camera ID', 128)
            text(camera['name'], 'Camera name', 128)
            if camera['camera_id'] in cameras or camera['status'] not in {'idle', 'running', 'online', 'connecting', 'reconnecting', 'stopped', 'offline', 'error', 'eof', 'paused', 'loading'}:
                raise ProtocolError('Invalid or duplicate camera status')
            cameras.add(camera['camera_id'])
            if camera.get('last_frame_at') is not None:
                timestamp(camera['last_frame_at'])
        models = set()
        for model in value['models']:
            if not isinstance(model, dict) or set(model) - {'model_id', 'version', 'classes', 'status', 'device'} or not {'model_id', 'version', 'classes', 'status'} <= set(model):
                raise ProtocolError('Invalid detector metadata')
            text(model['model_id'], 'Model ID', 256)
            text(model['version'], 'Model version', 128)
            if model['model_id'] in models or model['status'] not in {'active', 'idle', 'pending', 'unavailable', 'disabled', 'error', 'installed'}:
                raise ProtocolError('Invalid or duplicate model status')
            models.add(model['model_id'])
            if not isinstance(model['classes'], list) or len(model['classes']) > 1000:
                raise ProtocolError('Invalid model classes')
            for label in model['classes']:
                text(label, 'Class label', 128)
            if 'device' in model and model['device'] not in {'cpu', 'mps', 'cuda', 'unavailable', 'auto'}:
                raise ProtocolError('Invalid processing device')
    return value
