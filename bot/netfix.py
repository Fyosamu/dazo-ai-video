# -*- coding: utf-8 -*-
"""DNS self-heal for this machine.

The local resolver is flaky: it sometimes answers a public hostname with a
dead private address (api.pexels.com -> 10.10.34.36) and sometimes fails
outright (Errno 11001 getaddrinfo failed), while curl/other apps still work.

    import netfix   # very first import of the entry script

patches socket.getaddrinfo so that
  * a failed lookup is retried over DNS-over-HTTPS,
  * a bad (private) answer is replaced by the DoH answer,

and the DoH query itself goes straight to 8.8.8.8 / 1.1.1.1 by IP, so it
never depends on the broken resolver.  Healthy answers are untouched.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import struct
import threading
import time

_orig = socket.getaddrinfo
_tls = threading.local()
_cache = {}
_BAD = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16")]

# (SNI/hostname, IP) pairs - queried by IP so no local DNS is involved
_DOH = [("dns.google", "8.8.8.8"), ("dns.google", "8.8.4.4"),
        ("cloudflare-dns.com", "1.1.1.1"), ("cloudflare-dns.com", "1.0.0.1")]


def _debug(msg):
    import os
    if os.environ.get("NETFIX_DEBUG"):
        print("[netfix] %s" % msg, flush=True)


def _private(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return isinstance(a, ipaddress.IPv4Address) and any(a in n for n in _BAD)


class _ByIP(http.client.HTTPSConnection):
    """HTTPSConnection that connects to a fixed IP but keeps the real SNI,
    so DoH works even when the local resolver cannot answer at all."""

    def __init__(self, sni, ip, timeout=6, context=None):
        super().__init__(sni, 443, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _udp(host, qtype="A"):
    """Plain DNS-over-UDP to a public resolver.

    The DoH-by-IP path is blocked on some networks (RST on :443), but UDP/53
    to 8.8.8.8 still answers — so try this before giving up.
    """
    key = "%s/%s/udp" % (host, qtype)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < 3600:
        return hit[1]
    qtype_n = 28 if qtype == "AAAA" else 1
    tid = int(now * 1000) & 0xFFFF
    name = b"".join(bytes([len(p)]) + p.encode()
                    for p in host.split(".")) + b"\x00"
    pkt = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0) + name + struct.pack(">HH", qtype_n, 1)
    out = []
    for server in (("8.8.8.8", 53), ("1.1.1.1", 53), ("9.9.9.9", 53)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(4)
        try:
            sock.sendto(pkt, server)
            data, _ = sock.recvfrom(2048)
        except Exception:                      # noqa: BLE001 - next resolver
            continue
        finally:
            sock.close()
        try:
            qd, an = struct.unpack(">HH", data[4:8])
            i = 12
            for _ in range(qd):                # skip question section
                while data[i]:
                    i += 1 + data[i]
                i += 5
            for _ in range(an):
                if data[i] & 0xC0 == 0xC0:
                    i += 2
                else:
                    while data[i]:
                        i += 1 + data[i]
                    i += 1
                _t, _c, _ttl, ln = struct.unpack(">HHIH", data[i:i + 10])
                i += 10
                if _t == qtype_n and ln == 4:
                    ip = socket.inet_ntoa(data[i:i + 4])
                    if not _private(ip) and ip not in out:
                        out.append(ip)
                i += ln
        except Exception:                      # noqa: BLE001 - malformed
            continue
        if out:
            _cache[key] = (now, out)
            _debug("udp %s %s -> %s" % (host, qtype, out))
            return out
    return out


def _doh(host, qtype="A"):
    key = "%s/%s" % (host, qtype)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < 3600:
        return hit[1]
    if getattr(_tls, "busy", False):          # never recurse into our own lookup
        return []
    _tls.busy = True
    try:
        path = "/resolve?name=%s&type=%s" % (host, qtype)
        q = "/dns-query?name=%s&type=%s" % (host, qtype)
        answers = _udp(host, qtype)           # cheap, usually enough
        if answers:
            _cache[key] = (now, answers)
            return answers
        for verify in (True, False):          # 2nd pass ignores cert problems
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            for sni, ip in _DOH:
                try:
                    conn = _ByIP(sni, ip, context=ctx)
                    conn.request("GET", q if "cloudflare" in sni else path,
                                 headers={"User-Agent": "netfix/1.0",
                                          "Accept": "application/dns-json"})
                    r = conn.getresponse()
                    data = json.loads(r.read())
                    conn.close()
                    answers = [a["data"] for a in data.get("Answer", [])
                               if a.get("type") in ((1, 28) if qtype == "AAAA" else (1,))
                               and not _private(a["data"])]
                    if answers:
                        _cache[key] = (now, answers)
                        _debug("doh %s %s -> %s" % (host, qtype, answers))
                        return answers
                except Exception:             # noqa: BLE001 - try next server
                    continue
        return answers
    finally:
        _tls.busy = False


def _entry(ip, port, type_, proto_, flags_):
    t = type_ or socket.SOCK_STREAM
    p = proto_ or (socket.IPPROTO_UDP if t == socket.SOCK_DGRAM else socket.IPPROTO_TCP)
    if ":" in ip:
        return (socket.AF_INET6, t, p, "", (ip, port, 0, 0))
    return (socket.AF_INET, t, p, "", (ip, port))


def _gai(host, port, family=0, type=0, proto=0, flags=0, **kw):
    # socket.getaddrinfo(host, port, family, type, proto, flags) - flags, NOT canonname
    err = None
    try:
        res = _orig(host, port, family, type, proto, flags, **kw)
    except OSError as e:                      # Errno 11001 / 10065 / timeouts
        res, err = [], e
    if not isinstance(host, str):
        if res:
            return res
        raise err if err is not None else OSError("getaddrinfo failed")
    try:
        ipaddress.ip_address(host)
        if res:
            return res                        # host already is an address
        raise err if err is not None else OSError("getaddrinfo failed")
    except ValueError:
        pass

    if res and not any(_private(r[4][0]) for r in res):
        return res                            # healthy answer, leave it alone

    family = family or 0
    qtype = "AAAA" if family == socket.AF_INET6 else "A"
    fixed = [_entry(ip, port, type, proto, flags)
             for ip in (_doh(host, qtype) or _doh(host))]
    out = fixed + [r for r in res if not _private(r[4][0])]
    if family:
        filt = [r for r in out if r[0] == family]
        if filt:
            return filt
    if out:
        return out
    if err is not None:
        _debug("still failing %s: %s" % (host, err))
        raise err
    return res


if socket.getaddrinfo is _orig:               # install once (also on re-import
    socket.getaddrinfo = _gai                 # of a second copy)
    __patched__ = True
