"""User-initiated ONVIF WS-Discovery; passive names do not open video feeds."""
from dataclasses import dataclass
from time import monotonic
import socket
import ipaddress
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import uuid4
import xml.etree.ElementTree as ET

MAX_XML_BYTES = 1024 * 1024
MAX_CAMERAS = 64


class NetworkCameraError(RuntimeError):
    """A curated message which never contains a credential or response body."""


def parse_xml(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_XML_BYTES:
        raise NetworkCameraError("The camera returned an empty or oversized response.")
    # Decode before scanning declarations: raw-byte searches miss UTF-16 DTDs.
    # ONVIF requests/responses here use UTF-8; reject other encodings clearly.
    try:
        document = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise NetworkCameraError("The camera returned unsupported XML encoding.") from None
    if "\x00" in document or "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
        raise NetworkCameraError("The camera returned unsupported XML content.")
    try:
        return ET.fromstring(document)
    except (ET.ParseError, ValueError):
        raise NetworkCameraError("The camera returned an unreadable response.") from None


def local_name(tag):
    return str(tag).rsplit("}", 1)[-1]


def children_named(element, name):
    return [node for node in element.iter() if local_name(node.tag) == name]


def clean_name(text, fallback="Network camera"):
    text = " ".join(str(text or "").split())
    text = "".join(c for c in text if 32 <= ord(c) != 127)
    return text[:100] or fallback


def validated_device_url(value):
    message = "Enter an HTTP or HTTPS ONVIF device address, without a password in the address."
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise NetworkCameraError(message)
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None or parts.fragment or parts.query:
            raise ValueError()
        if "\\" in parts.netloc or (parts.port is not None and not 1 <= parts.port <= 65535):
            raise ValueError()
        parts.hostname.encode("idna")
        path = parts.path if parts.path not in {"", "/"} else "/onvif/device_service"
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    except (ValueError, UnicodeError):
        raise NetworkCameraError(message) from None


@dataclass(frozen=True)
class NetworkCamera:
    name: str
    device_url: str
    endpoint_id: str = ""

    @property
    def description(self):
        parts = urlsplit(self.device_url)
        return f"{self.name} · {parts.hostname}"


@dataclass(frozen=True)
class DiscoveryInterface:
    name: str
    address: str

    @property
    def description(self):
        return f'{self.name} · {self.address}'


def discovery_interfaces():
    """Read active local IPv4 interfaces without opening a network connection.

    Interface names are shown as supplied by the OS; this does not pretend to
    enumerate Wi-Fi access points or infer that every connected device is CCTV.
    """
    import psutil
    try:
        stats=psutil.net_if_stats();addresses=psutil.net_if_addrs()
    except (OSError, psutil.Error):return ()
    result=[];seen=set()
    for name,entries in addresses.items():
        state=stats.get(name)
        if state is None or not state.isup:continue
        for entry in entries:
            if entry.family!=socket.AF_INET:continue
            try:address=ipaddress.IPv4Address(entry.address)
            except ipaddress.AddressValueError:continue
            if address.is_loopback or address.is_unspecified or address.is_multicast or str(address)=='255.255.255.255':continue
            key=(name,str(address))
            if key not in seen:
                seen.add(key);result.append(DiscoveryInterface(clean_name(name,'Network'),str(address)))
    return tuple(sorted(result,key=lambda interface:(interface.name,interface.address)))


def _interface_address(value):
    if value is None:return None
    if not isinstance(value,str):raise ValueError('Choose a local IPv4 network interface')
    try:address=ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:raise ValueError('Choose a local IPv4 network interface') from None
    if address.is_unspecified or address.is_multicast or str(address)=='255.255.255.255':raise ValueError('Choose a local IPv4 network interface')
    return str(address)


def make_probe():
    message_id = "urn:uuid:" + str(uuid4())
    envelope = f'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<s:Header><a:MessageID>{message_id}</a:MessageID><a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To><a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action></s:Header>
<s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body></s:Envelope>'''
    return message_id, envelope.encode("utf-8")


def parse_probe_matches(data, message_id=None):
    root = parse_xml(data)
    related = children_named(root, "RelatesTo")
    if message_id and related and not any((n.text or "").strip() == message_id for n in related):
        return []
    devices = []
    for match in children_named(root, "ProbeMatch")[:MAX_CAMERAS]:
        types = children_named(match, "Types")
        if types and not any("NetworkVideoTransmitter" in (node.text or "") for node in types):
            continue
        scopes = " ".join(node.text or "" for node in children_named(match, "Scopes"))
        name = next((unquote(s.split("/name/", 1)[1]) for s in scopes.split() if "/name/" in s), "Network camera")
        name = clean_name(name)
        addresses = children_named(match, "Address")
        endpoint_id = (addresses[0].text or "")[:200] if addresses else ""
        for node in children_named(match, "XAddrs"):
            for candidate in (node.text or "").split()[:16]:
                try:
                    url = validated_device_url(candidate)
                except NetworkCameraError:
                    continue
                devices.append(NetworkCamera(name, url, endpoint_id))
    return devices


def discover_cameras(timeout_s=3.0, cancel_event=None, interface_address=None):
    """Multicast two bounded ONVIF probes on the active IPv4 interface.

    Only responding discoverable devices on the local multicast network appear.
    No port/subnet scan, credentials, video requests, or background discovery.
    """
    if type(timeout_s) not in (int, float) or not .2 <= timeout_s <= 10:
        raise ValueError("Discovery timeout must be between 0.2 and 10 seconds")
    interface_address = _interface_address(interface_address)
    if cancel_event is not None and cancel_event.is_set():return []
    deadline = monotonic() + timeout_s
    message_id, probe = make_probe()
    result = {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            sock.settimeout(.2)
            if interface_address is not None:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_address))
            sock.bind((interface_address or "", 0))
            for _ in range(2):
                if cancel_event is not None and cancel_event.is_set():
                    return []
                sock.sendto(probe, ("239.255.255.250", 3702))
            while monotonic() < deadline and len(result) < MAX_CAMERAS:
                if cancel_event is not None and cancel_event.is_set():
                    break
                sock.settimeout(max(.001, min(.2, deadline - monotonic())))
                try:
                    data, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                try:
                    matches = parse_probe_matches(data, message_id)
                except NetworkCameraError:
                    continue
                for camera in matches:
                    result.setdefault(camera.device_url, camera)
                    if len(result) >= MAX_CAMERAS:
                        break
    except OSError:
        raise NetworkCameraError("Local camera discovery is unavailable. Check the selected network, macOS Privacy & Security → Local Network permission and firewall settings, or enter the ONVIF address manually.") from None
    return sorted(result.values(), key=lambda d: (d.name.casefold(), d.device_url))
