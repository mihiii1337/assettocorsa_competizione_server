#!/usr/bin/env python3
"""
Smoke test: a handshake with the Steam ID of a connected driver only
closes that driver's connection once it is accepted.

A duplicate rejected for a wrong password, a car outside the carGroup
or a car other than its entry list model must leave the driver
connected. A reconnect in the same car gets the same car back, one in
another model gets a new car, and a reconnect still gets in when
maxCarSlots is reached. Each accepted reconnect closes the old
connection. Invoked from `make test`. Exits 0 on success, non-zero on
any failure.
"""

import json
import os
import select
import signal
import socket
import struct
import subprocess
import tempfile
import time

from fake_client import build_car_info, build_driver_info, wstr_a
from smoke_handshake import ACCD_PROTOCOL_VERSION, TCP_PORT, fail, write_cfg

VICTIM = "S76561199000000101"
OTHER = "S76561199000000102"
EXTRA = "S76561199000000103"
PASSWORD = "secret"
GT3 = 35
GT3_OTHER = 30
GT4 = 50
REJECT_BAD_GROUP = 1
REJECT_PASSWORD = 6
REJECT_FULL = 9
REJECT_BAD_CAR = 11


class Client:
    def __init__(self, steam, model, password=PASSWORD, race_number=7):
        self.buf = b""
        self.closed = False
        self.sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
        body = bytes([0x09])
        body += struct.pack("<H", ACCD_PROTOCOL_VERSION)
        body += wstr_a(password)
        body += build_driver_info(steam=steam)
        body += bytes(8)
        body += build_car_info(car_model=model, race_number=race_number)
        self.sock.sendall(struct.pack("<H", len(body)) + body)
        self.reply = self.first_frame()

    def first_frame(self):
        end = time.monotonic() + 3.0
        while True:
            if len(self.buf) >= 2:
                n = struct.unpack_from("<H", self.buf)[0]
                if n == 0xFFFF:
                    fail("unexpected long frame in the handshake reply")
                if len(self.buf) >= 2 + n:
                    body = self.buf[2 : 2 + n]
                    self.buf = self.buf[2 + n :]
                    return body
            if self.closed or time.monotonic() >= end:
                fail("no handshake reply")
            self.pump(0.05)

    def pump(self, duration):
        """Read for duration seconds, return False once closed."""
        end = time.monotonic() + duration
        while not self.closed:
            left = end - time.monotonic()
            if left <= 0:
                break
            ready, _, _ = select.select([self.sock], [], [], left)
            if not ready:
                continue
            try:
                chunk = self.sock.recv(65536)
            except ConnectionResetError:
                chunk = b""
            if chunk:
                self.buf += chunk
            else:
                self.closed = True
        return not self.closed

    def car_id(self):
        if len(self.reply) < 10 or self.reply[0] != 0x0B:
            fail(f"expected a welcome, got {self.reply[:2].hex()}")
        return struct.unpack_from("<I", self.reply, 6)[0]

    def reject_code(self):
        if len(self.reply) < 2 or self.reply[0] != 0x0C:
            fail(f"expected a reject, got {self.reply[:2].hex()}")
        return self.reply[1]

    def close(self):
        self.sock.close()


def rejected(steam, model, code, password=PASSWORD):
    cl = Client(steam, model, password)
    got = cl.reject_code()
    cl.close()
    if got != code:
        fail(f"duplicate got reject code {got}, expected {code}")


def still_connected(cl, what):
    if not cl.pump(0.5):
        fail(f"{what} disconnected the connected driver")


def replaced(old, steam, model, what):
    new = Client(steam, model)
    new.car_id()
    end = time.monotonic() + 2.0
    while old.pump(0.1):
        if time.monotonic() >= end:
            fail(f"{what} left the old connection open")
    old.close()
    return new


def run(settings, entrylist, scenario):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-dup-") as tmp:
        write_cfg(tmp)
        with open(os.path.join(tmp, "settings.json"), "w") as f:
            json.dump(settings, f)
        if entrylist is not None:
            with open(os.path.join(tmp, "entrylist.json"), "w") as f:
                json.dump(entrylist, f)
        proc = subprocess.Popen(
            [accd_bin, tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        clients = []
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", TCP_PORT), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                fail(f"accd did not listen on {TCP_PORT} within 3s")
            scenario(clients)
            if proc.poll() is not None:
                fail(f"accd exited with status {proc.returncode}")
        finally:
            for cl in clients:
                cl.close()
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()


def open_server(clients):
    victim = Client(VICTIM, GT3)
    clients.append(victim)
    car = victim.car_id()

    rejected(VICTIM, GT3, REJECT_PASSWORD, password="wrong")
    still_connected(victim, "wrong password duplicate")
    rejected(VICTIM, GT4, REJECT_BAD_GROUP)
    still_connected(victim, "carGroup duplicate")

    victim = replaced(victim, VICTIM, GT3, "reconnect")
    clients.append(victim)
    if victim.car_id() != car:
        fail(f"reconnect got car {victim.car_id()}, not its car {car}")

    victim = replaced(victim, VICTIM, GT3_OTHER, "reconnect in another model")
    clients.append(victim)
    car = victim.car_id()

    other = Client(OTHER, GT3, race_number=8)
    clients.append(other)
    other.car_id()
    extra = Client(EXTRA, GT3, race_number=9)
    clients.append(extra)
    if extra.reject_code() != REJECT_FULL:
        fail("server with maxCarSlots cars took one more")

    rejected(VICTIM, GT3_OTHER, REJECT_PASSWORD, password="wrong")
    still_connected(victim, "wrong password duplicate on a full server")
    victim = replaced(victim, VICTIM, GT3_OTHER, "reconnect on a full server")
    clients.append(victim)
    if victim.car_id() != car:
        fail(f"full server reconnect got car {victim.car_id()}, not {car}")
    still_connected(other, "reconnect of another driver")


def entry_list_server(clients):
    victim = Client(VICTIM, GT3)
    clients.append(victim)
    car = victim.car_id()

    rejected(VICTIM, GT3_OTHER, REJECT_BAD_CAR)
    still_connected(victim, "forced car model duplicate")

    victim = replaced(victim, VICTIM, GT3, "entry list reconnect")
    clients.append(victim)
    if victim.car_id() != car:
        fail(f"entry list reconnect got car {victim.car_id()}, not {car}")


def main():
    base = {"serverName": "smoke", "password": PASSWORD}
    run({**base, "carGroup": "GT3", "maxCarSlots": 2}, None, open_server)
    entries = [
        {"drivers": [{"playerID": VICTIM}], "raceNumber": 7, "forcedCarModel": GT3}
    ]
    run(base, {"entries": entries, "forceEntryList": 1}, entry_list_server)
    print("PASS: only an accepted handshake closes the same Steam ID")


if __name__ == "__main__":
    main()
