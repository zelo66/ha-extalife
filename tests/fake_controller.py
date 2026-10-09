"""Fake EFC-01 controller speaking Exta Life TCP JSON protocol - used by tests."""
from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

ETX = b"\x03"

MAC = "AABBCC112233"
USERNAME = "root"
PASSWORD = "secret-password"

RECEIVERS: list[dict[str, Any]] = [
    {   # ROP-21 switch
        "id": 11, "type": 10, "serial": 0x0B0001, "is_powered": True,
        "state": [{"alias": "Socket", "channel": 1, "icon": 1, "power": 0, "is_timeout": False}],
    },
    {   # ROP-21 switch mapped as light (icon 13)
        "id": 14, "type": 10, "serial": 0x0B0004, "is_powered": True,
        "state": [{"alias": "Lamp", "channel": 1, "icon": 13, "power": 1, "is_timeout": False}],
    },
    {   # ROP-21 not responding
        "id": 15, "type": 10, "serial": 0x0B0005, "is_powered": True,
        "state": [{"alias": "Dead", "channel": 1, "icon": 1, "power": 0, "is_timeout": True}],
    },
    {   # SRP-22 roller blind, value 0 = open, 100 = closed
        "id": 12, "type": 12, "serial": 0x0C0002, "is_powered": True,
        "state": [{"alias": "Blind", "channel": 1, "icon": 20, "value": 100, "is_timeout": False}],
    },
    {   # MEM-21 energy meter with identical (unused) phases
        "id": 13, "type": 35, "serial": 0x230003, "is_powered": True,
        "state": [{
            "alias": "Meter", "channel": 1, "is_timeout": False, "total_energy": 1234500000,
            "phase": [
                {"voltage": 23000, "current": 1000, "active_power": 230},
                {"voltage": 0, "current": 0, "active_power": 0},
                {"voltage": 0, "current": 0, "active_power": 0},
            ],
        }],
    },
]

SENSORS: list[dict[str, Any]] = [
    {   # RCT-21 temperature sensor
        "id": 20, "type": 20, "serial": 0x140020,
        "state": [{"alias": "Temperature", "channel": 1, "value_1": 21.5, "is_timeout": False}],
    },
]

TRANSMITTERS: list[dict[str, Any]] = [
    {   # P-457/4 remote
        "id": 30, "type": 6, "serial": 0x060030,
        "state": [{"alias": "Remote"}],
    },
]


class FakeController:
    """Minimal EFC-01 emulator"""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None
        self.port: int = 0
        self.writers: list[asyncio.StreamWriter] = []
        self.received: list[dict[str, Any]] = []
        self.ignored_commands: set[int] = set()
        self.receivers = copy.deepcopy(RECEIVERS)
        self.sensors = copy.deepcopy(SENSORS)
        self.transmitters = copy.deepcopy(TRANSMITTERS)
        self.connections: int = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0, limit=16 * 1024 * 1024)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in self.writers:
            writer.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    def send(self, message: dict[str, Any]) -> None:
        """Send message to all connected clients"""
        for writer in self.writers:
            if not writer.is_closing():
                writer.write(json.dumps(message).encode() + ETX)

    def send_raw(self, data: bytes) -> None:
        for writer in self.writers:
            if not writer.is_closing():
                writer.write(data + ETX)

    def notify(self, command: int, data: dict[str, Any]) -> None:
        self.send({"command": command, "status": "notification", "data": data})

    def drop_connections(self) -> None:
        for writer in self.writers:
            writer.close()
        self.writers = []

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.append(writer)
        self.connections += 1
        try:
            while True:
                try:
                    raw = await reader.readuntil(ETX)
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                text = raw[:-1].decode().strip()
                if not text:
                    continue  # keep-alive (NOOP)
                request = json.loads(text)
                self.received.append(request)
                command = request["command"]
                if command in self.ignored_commands:
                    continue
                writer.write(json.dumps(self._response(command, request.get("data") or {})).encode() + ETX)
                await writer.drain()
        finally:
            if writer in self.writers:
                self.writers.remove(writer)
            writer.close()

    def _response(self, command: int, data: dict[str, Any]) -> dict[str, Any]:
        def ok(payload: Any) -> dict[str, Any]:
            return {"command": command, "status": "success", "data": payload}

        if command == 1:  # LOGIN
            if data.get("login") == USERNAME and data.get("password") == PASSWORD:
                return ok({"login": USERNAME})
            return {"command": command, "status": "failure", "data": {"code": -2}}
        if command == 154:  # GET_EFC_CONFIG_DETAILS
            return ok({
                "network": {"name": "EFC-01 Test", "mac": MAC},
                "network_actual": {"ip": "127.0.0.1", "mask": "255.0.0.0", "gate": "", "dns_prime": ""},
            })
        if command == 151:  # CHECK_VERSION
            return ok({"installed_version": "1.6.30", "web_version": "1.6.30", "update_state": 0})
        if command == 37:  # FETCH_RECEIVERS
            return ok({"devices": copy.deepcopy(self.receivers)})
        if command == 38:  # FETCH_SENSORS
            return ok({"devices": copy.deepcopy(self.sensors)})
        if command == 39:  # FETCH_TRANSMITTERS
            return ok({"devices": copy.deepcopy(self.transmitters)})
        if command == 203:  # FETCH_EXTA_FREE
            return ok({"devices": []})
        if command == 27:  # FETCH_RECEIVER_CONFIG_DETAILS
            return ok({"new_version": "1.0", "available_version": "1.0"})
        if command == 500:  # DOWNLOAD_BACKUP
            return {"command": command, "status": "success", "data_element": {"login": USERNAME,
                                                                               "password": PASSWORD}}
        if command == 20:  # CONTROL_DEVICE
            return ok(None)
        return ok(None)
