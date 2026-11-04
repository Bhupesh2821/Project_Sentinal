"""Small read-only ONVIF Media/Media2 client; no camera configuration changes."""
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import secrets
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import (Request, build_opener, ProxyHandler, HTTPRedirectHandler,
                            HTTPPasswordMgrWithDefaultRealm, HTTPDigestAuthHandler,
                            HTTPBasicAuthHandler)
from xml.sax.saxutils import escape

from .network_discovery import (NetworkCameraError, MAX_XML_BYTES, parse_xml,
                                validated_device_url, children_named, clean_name)

DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
MEDIA2_NS = "http://www.onvif.org/ver20/media/wsdl"
SCHEMA_NS = "http://www.onvif.org/ver10/schema"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never send a camera password to an address selected by a redirect.
        raise NetworkCameraError("The camera redirected its ONVIF service. Enter the camera's final device address manually.")


@dataclass(frozen=True, repr=False)
class CameraStream:
    name: str
    uri: str = field(repr=False)
    token: str = field(repr=False)
    width: int = 0
    height: int = 0
    encoding: str = ""

    @property
    def description(self):
        detail = " · ".join(x for x in (self.encoding, f"{self.width}×{self.height}" if self.width and self.height else "") if x)
        return f"{self.name} · {detail}" if detail else self.name

    def __repr__(self):
        return f"CameraStream(name={self.name!r}, resolution=({self.width}, {self.height}))"


class OnvifClient:
    def __init__(self, device_url, username="", password="", timeout_s=3.0, cancel_event=None):
        self.device_url = validated_device_url(device_url)
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 1024 or len(password) > 1024:
            raise NetworkCameraError("Camera credentials are too long or invalid.")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not .2 <= timeout_s <= 10:
            raise ValueError("Camera timeout must be between 0.2 and 10 seconds")
        self._username, self._password = username, password
        self.timeout_s, self.cancel_event = float(timeout_s), cancel_event
        self._deadline = 0.0

    def __repr__(self):
        return "OnvifClient(credentials=hidden)"

    def _check_cancel(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise NetworkCameraError("Camera setup cancelled.")
        if self._deadline and monotonic() >= self._deadline:
            raise NetworkCameraError("Camera setup timed out. Check its address and connection, then retry.")

    def _endpoint(self, value):
        url = validated_device_url(value)
        if urlsplit(url).hostname.casefold() != urlsplit(self.device_url).hostname.casefold():
            raise NetworkCameraError("The camera advertised a different server. Enter its video address directly if this is your NVR's expected configuration.")
        if urlsplit(self.device_url).scheme == "https" and urlsplit(url).scheme != "https":
            raise NetworkCameraError("The camera advertised an insecure ONVIF service. Enter the correct HTTPS service or the video address directly.")
        return url

    def _security_header(self):
        if not self._username and not self._password:
            return ""
        nonce = secrets.token_bytes(20)
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        digest = b64encode(hashlib.sha1(nonce + created.encode() + self._password.encode()).digest()).decode()
        return f'''<wsse:Security s:mustUnderstand="1" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><wsse:UsernameToken><wsse:Username>{escape(self._username)}</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password><wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{b64encode(nonce).decode()}</wsse:Nonce><wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>'''

    def _post(self, endpoint, namespace, operation, body=""):
        self._check_cancel()
        endpoint = self._endpoint(endpoint)
        envelope = f'''<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:t="{namespace}" xmlns:tt="{SCHEMA_NS}"><s:Header>{self._security_header()}</s:Header><s:Body><t:{operation}>{body}</t:{operation}></s:Body></s:Envelope>'''.encode("utf-8")
        manager = HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, endpoint, self._username, self._password)
        opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPDigestAuthHandler(manager), HTTPBasicAuthHandler(manager))
        action = f"{namespace}/{operation}"
        request = Request(endpoint, data=envelope, headers={
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "SOAPAction": f'"{action}"', "User-Agent": "SENTINAL-ONVIF/0.1",
        }, method="POST")
        try:
            remaining = self._deadline - monotonic() if self._deadline else self.timeout_s
            with opener.open(request, timeout=max(.1, min(self.timeout_s, remaining))) as response:
                content = bytearray()
                while True:
                    self._check_cancel()
                    # read1 returns after one buffered/underlying receive. A peer
                    # slowly dripping bytes cannot hide inside a full-size read
                    # indefinitely and bypass the overall setup deadline.
                    chunk = response.read1(min(65536, MAX_XML_BYTES + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > MAX_XML_BYTES:
                        raise NetworkCameraError("The camera returned an oversized response.")
            root = parse_xml(bytes(content))
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code in {401, 403}:
                raise NetworkCameraError("Camera sign-in failed. Check the ONVIF account and password; some cameras require ONVIF access to be enabled.") from None
            raise NetworkCameraError("The ONVIF request was rejected. Check its service address, account and camera compatibility.") from None
        except (OSError, URLError, ValueError):
            raise NetworkCameraError("The camera could not be reached. Check its ONVIF address, network connection and certificate, then retry.") from None
        if children_named(root, "Fault"):
            # Raw fault text may echo secrets, addresses or request bodies.
            raise NetworkCameraError("The camera rejected this ONVIF operation. Check the ONVIF account, camera clock and supported media service, or use its video address directly.")
        return root

    def _media_services(self):
        services = []
        try:
            root = self._post(self.device_url, DEVICE_NS, "GetCapabilities", "<t:Category>Media</t:Category>")
            for media in children_named(root, "Media"):
                for address in children_named(media, "XAddr"):
                    if address.text:
                        services.append((self._endpoint(address.text.strip()), MEDIA_NS))
        except NetworkCameraError:
            self._check_cancel()
        if not services:
            root = self._post(self.device_url, DEVICE_NS, "GetServices", "<t:IncludeCapability>false</t:IncludeCapability>")
            for service in children_named(root, "Service")[:32]:
                namespaces = children_named(service, "Namespace")
                addresses = children_named(service, "XAddr")
                if namespaces and addresses and namespaces[0].text in {MEDIA_NS, MEDIA2_NS} and addresses[0].text:
                    services.append((self._endpoint(addresses[0].text.strip()), namespaces[0].text))
        if not services:
            raise NetworkCameraError("No supported ONVIF Media service was advertised. Enter the camera's RTSP or HTTP video address directly.")
        return list(dict.fromkeys(services))[:2]

    def _stream_uri(self, uri):
        try:
            parts = urlsplit(uri)
            if parts.scheme not in {"rtsp", "rtsps", "http", "https"} or not parts.hostname or len(uri) > 8192 or parts.fragment or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in uri):
                raise ValueError()
            if parts.username is not None or parts.password is not None or "\\" in parts.netloc or (parts.port is not None and not 1 <= parts.port <= 65535):
                raise ValueError()
            if parts.hostname in {"0.0.0.0", "::"}:
                device_host = urlsplit(self.device_url).hostname
                host = f"[{device_host}]" if ":" in device_host else device_host
                parts = parts._replace(netloc=host + (f":{parts.port}" if parts.port else ""))
            if parts.hostname.casefold() != urlsplit(self.device_url).hostname.casefold():
                raise ValueError()
            return urlunsplit(parts)
        except (ValueError, UnicodeError):
            raise NetworkCameraError("The camera advertised an unsupported or different-server video address. Enter its video endpoint directly instead.") from None

    def list_streams(self):
        self._deadline = monotonic() + 30.0
        self._check_cancel()
        streams = []
        for endpoint, namespace in self._media_services():
            root = self._post(endpoint, namespace, "GetProfiles")
            profiles = children_named(root, "Profiles")[:16]
            for profile in profiles:
                self._check_cancel()
                token = profile.attrib.get("token", "")
                if not token or len(token) > 256:
                    continue
                names = children_named(profile, "Name")
                name = clean_name(names[0].text if names else "", f"Video profile {len(streams) + 1}")
                widths, heights = children_named(profile, "Width"), children_named(profile, "Height")
                encodings = children_named(profile, "Encoding")
                def dimension(nodes):
                    try:
                        return max(0, min(32768, int(nodes[0].text))) if nodes else 0
                    except (TypeError, ValueError):
                        return 0
                setup = ("<t:Protocol>RTSP</t:Protocol>" if namespace == MEDIA2_NS else
                         "<t:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></t:StreamSetup>")
                try:
                    reply = self._post(endpoint, namespace, "GetStreamUri", setup + f"<t:ProfileToken>{escape(token)}</t:ProfileToken>")
                    uris = children_named(reply, "Uri")
                    if uris and uris[0].text:
                        uri = self._stream_uri(uris[0].text.strip())
                        if not any(s.uri == uri for s in streams):
                            streams.append(CameraStream(name, uri, token, dimension(widths), dimension(heights), clean_name(encodings[0].text, "") if encodings else ""))
                except NetworkCameraError:
                    self._check_cancel()
                    continue
        if not streams:
            raise NetworkCameraError("No usable video stream was returned. Check ONVIF permissions or enter the camera's RTSP/HTTP address directly.")
        return streams
