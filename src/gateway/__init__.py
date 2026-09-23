"""gateway: the PC-side local network interface layer (REST + WebSocket).

Corresponds to docs/decisions/07-gateway.md
 ("PC 内置网关" -- the gateway-mode specialization where the PC
upper-computer process itself plays the gateway role) and to
docs/android.md.

Architectural position: this package is a *peer of* ``ui/`` -- both are
consumers of ``api.ApiInterface``, differing only in how they re-express
its capabilities (``ui/`` as Qt signals for PyQt6 widgets, ``gateway/`` as
HTTP responses and WebSocket messages for an Android client). It is not a
new architectural layer, and it does not change any existing layer's
responsibilities.

Dependency direction (mirrors the rule ``ui/`` already follows): this
package imports ``api`` plus the shared model types from ``core``/
``service``/``application`` that ``api`` itself already exposes in its
signatures. It never imports ``device``, ``communication``, or
``protocol`` -- an Android client is not supposed to know a COM port, a
baud rate, a CRC, or a frame format exists, and neither is this layer.
"""
