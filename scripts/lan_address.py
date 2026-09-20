"""Find the LAN IPv4 address a phone on the same Wi-Fi should connect to.

Why this is not a one-liner
---------------------------
The usual trick -- open a UDP socket "to" 8.8.8.8 and read back
``getsockname()`` -- returns whichever address the OS would route
*outbound* traffic through. On a machine running a VPN/proxy that is the
tunnel's address, not the Wi-Fi address. Verified on the development
machine for this project: that trick returns ``198.18.0.1`` (a Mihomo/
Clash "Meta Tunnel" adapter), while the address a phone actually needs is
``192.168.2.153`` (the Intel Wi-Fi adapter). Handing the tunnel address to
someone to type into their phone would simply never connect, with no
useful error to explain why.

So this module enumerates every adapter, drops the ones that cannot be a
phone-reachable LAN address, and ranks the rest -- preferring real
Wi-Fi/Ethernet adapters holding a private address. It reports *all*
candidates rather than only its best guess, so a wrong guess is visible
and correctable instead of silently misleading.

Windows is the primary target (this project's launchers are .bat files and
its serial ports are COM ports), where PowerShell provides adapter names.
Other platforms fall back to a name-less enumeration that still applies
the address-range filtering.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import sys
from dataclasses import dataclass

# Adapter name/description fragments that mean "not a physical LAN adapter
# a phone could reach this PC through".
_VIRTUAL_ADAPTER_HINTS = (
    "LOOPBACK",
    "HYPER-V",
    "VETHERNET",
    "VIRTUALBOX",
    "VMWARE",
    "TAP-WINDOWS",
    "TUNNEL",
    "TUN",
    "WSL",
    "BLUETOOTH",
    "DOCKER",
    "VPN",
    "META",  # Mihomo/Clash "Meta Tunnel"
    "WINTUN",
)

# Adapter names that positively indicate a normal LAN interface.
_PHYSICAL_ADAPTER_HINTS = ("WI-FI", "WIFI", "WLAN", "以太网", "ETHERNET", "LAN")


@dataclass(frozen=True)
class LanCandidate:
    """One IPv4 address a client might be able to reach this PC on."""

    ip: str
    adapter: str
    description: str
    score: int

    @property
    def looks_usable(self) -> bool:
        return self.score > 0


def _is_plausible_lan_ip(ip: str) -> bool:
    """Reject addresses that can never be a useful LAN address."""
    try:
        address = ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        return False
    if address.is_loopback or address.is_link_local or address.is_multicast:
        # 169.254.x.x (link-local/APIPA) means "DHCP failed" -- never useful.
        return False
    # 198.18.0.0/15 is the benchmark-testing range, which Clash/Mihomo-style
    # proxies commonly use for their tunnel adapter. Not a LAN address.
    if address in ipaddress.IPv4Network("198.18.0.0/15"):
        return False
    return address.is_private


def _score(ip: str, adapter: str, description: str) -> int:
    """Higher is more likely to be the address a phone should use."""
    haystack = f"{adapter} {description}".upper()
    if any(hint in haystack for hint in _VIRTUAL_ADAPTER_HINTS):
        return 0
    if not _is_plausible_lan_ip(ip):
        return 0

    score = 10
    if any(hint in haystack for hint in _PHYSICAL_ADAPTER_HINTS):
        score += 10
    # Home routers overwhelmingly hand out 192.168.x.x; 172.16-31.x.x is
    # more often a virtual/container network even when the adapter name
    # does not say so.
    if ip.startswith("192.168."):
        score += 5
    elif ip.startswith("10."):
        score += 3
    return score


def _candidates_via_powershell() -> list[LanCandidate]:
    """Enumerate adapters with their names (Windows only).

    Encoding matters here and is easy to get wrong. ``text=True`` decodes
    with the *locale* encoding, which on a Chinese Windows install is GBK.
    Adapter descriptions are vendor strings and routinely contain bytes
    that are not valid GBK, and the failure mode is nasty: the decode
    error is raised inside ``subprocess``'s reader *thread*, so
    ``subprocess.run`` still returns normally -- but with ``stdout=None``,
    which then blows up somewhere else entirely with a confusing
    ``AttributeError``. Observed on this project's development machine
    (2026-08-16): ``'gbk' codec can't decode byte 0x91``.

    So: tell PowerShell to emit UTF-8, decode as UTF-8 explicitly, and
    never let one odd character in a vendor string take down the launcher
    (``errors="replace"`` -- a garbled adapter *name* is cosmetic, the IP
    address itself is plain ASCII and still correct).
    """
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { "
        "$a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex "
        "-ErrorAction SilentlyContinue; "
        "[PSCustomObject]@{ ip = $_.IPAddress; adapter = $a.Name; "
        "description = $a.InterfaceDescription } } | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    # stdout can still be None if the pipe could not be read at all; treat
    # that exactly like "no output" instead of crashing the launcher.
    stdout = (completed.stdout or "").lstrip("﻿").strip()
    if completed.returncode != 0 or not stdout:
        return []

    parsed = json.loads(stdout)
    if isinstance(parsed, dict):  # a single adapter is not wrapped in a list
        parsed = [parsed]

    candidates = []
    for entry in parsed:
        ip = (entry.get("ip") or "").strip()
        adapter = (entry.get("adapter") or "").strip()
        description = (entry.get("description") or "").strip()
        if not ip:
            continue
        candidates.append(
            LanCandidate(ip, adapter, description, _score(ip, adapter, description))
        )
    return candidates


def _candidates_via_socket() -> list[LanCandidate]:
    """Fallback enumeration without adapter names."""
    addresses: set[str] = set()
    try:
        _, _, resolved = socket.gethostbyname_ex(socket.gethostname())
        addresses.update(resolved)
    except OSError:
        pass
    return [LanCandidate(ip, "", "", _score(ip, "", "")) for ip in sorted(addresses)]


def find_candidates() -> list[LanCandidate]:
    """All plausible LAN addresses, best first."""
    candidates: list[LanCandidate] = []
    if sys.platform == "win32":
        try:
            candidates = _candidates_via_powershell()
        except (OSError, ValueError, subprocess.SubprocessError):
            candidates = []
    if not candidates:
        candidates = _candidates_via_socket()

    usable = [candidate for candidate in candidates if candidate.looks_usable]
    return sorted(usable, key=lambda c: (-c.score, c.ip))


def best_address() -> str | None:
    """The single most likely address, or None if nothing plausible found."""
    candidates = find_candidates()
    return candidates[0].ip if candidates else None
