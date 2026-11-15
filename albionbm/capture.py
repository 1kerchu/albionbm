"""Captura pasiva de los paquetes del juego (puerto 5056) con Scapy + Npcap.

Solo escucha: no envía nada, no inyecta nada y no lee la memoria del juego.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

PORT = 5056
BPF_FILTER = f"udp port {PORT} or tcp port {PORT}"


class CaptureError(Exception):
    pass


class Capture:
    def __init__(self, on_packet: Callable[[bytes, Optional[str]], None],
                 on_error: Callable[[str], None]):
        self.on_packet = on_packet
        self.on_error = on_error
        self._sniffer = None
        self.running = False

    def start(self) -> None:
        try:
            from scapy.all import AsyncSniffer, conf  # noqa: F401
            from scapy.layers.inet import IP, TCP, UDP
        except ImportError:
            raise CaptureError("Falta la librería Scapy. Instálala con:  pip install scapy")

        def handle(pkt):
            try:
                if UDP in pkt:
                    layer = pkt[UDP]
                elif TCP in pkt:
                    layer = pkt[TCP]
                else:
                    return
                payload = bytes(layer.payload)
                if not payload:
                    return
                src_ip = pkt[IP].src if IP in pkt and layer.sport == PORT else None
                self.on_packet(payload, src_ip)
            except Exception as e:  # nunca dejar que un paquete raro tumbe la captura
                self.on_error(f"Paquete ignorado: {e}")

        ifaces = self._interfaces()
        try:
            self._sniffer = AsyncSniffer(filter=BPF_FILTER, prn=handle, store=False, iface=ifaces)
            self._sniffer.start()
        except Exception as e:
            raise CaptureError(self._explain(e))
        self.running = True

        # AsyncSniffer arranca en otro hilo: comprobamos que no haya fallado al iniciar.
        def watchdog():
            t = getattr(self._sniffer, "thread", None)
            if t:
                t.join(2.0)
                if not t.is_alive() and self.running:
                    exc = getattr(self._sniffer, "exception", None)
                    self.running = False
                    self.on_error(self._explain(exc) if exc else "La captura se detuvo inesperadamente.")
        threading.Thread(target=watchdog, daemon=True).start()

    @staticmethod
    def _interfaces():
        """Todas las interfaces de red activas (por si usas VPN o ExitLag)."""
        try:
            from scapy.interfaces import get_working_ifaces
            ifs = [i for i in get_working_ifaces() if getattr(i, "ips", None) and (i.ips.get(4) or i.ips.get(6))]
            return ifs or None
        except Exception:
            return None

    @staticmethod
    def _explain(e) -> str:
        msg = str(e)
        low = msg.lower()
        if "winpcap" in low or "npcap" in low or "libpcap" in low or "pcap" in low:
            return ("No se encontró Npcap. Descárgalo gratis de https://npcap.com e instálalo "
                    "(marca «WinPcap API-compatible mode»). Después reinicia la app.")
        if "permission" in low or "access" in low or "denied" in low:
            return "Sin permisos para capturar. Ejecuta la app como administrador."
        return f"No se pudo iniciar la captura: {msg}"

    def stop(self) -> None:
        self.running = False
        if self._sniffer:
            try:
                self._sniffer.stop()
            except Exception:
                pass
            self._sniffer = None
