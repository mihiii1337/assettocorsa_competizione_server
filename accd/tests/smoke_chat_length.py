#!/usr/bin/env python3
"""
Smoke test: two drivers join, one sends player chat, and both must get
the 0x2b relay with the message unchanged.

Covers a short message, one past the 35 code points accd used to cut
at, non-ASCII text, and the 254 code point ceiling of the str_a
writer. The sender must be the driver's full name in uppercase, and
the first and last name only once the full name is over 35 code
points. Invoked from `make test`. Exits 0 on success, non-zero on
any failure.
"""

import os
import select
import signal
import socket
import struct
import subprocess
import tempfile
import time

from fake_client import Reader, build_car_info, build_driver_info, wstr_a
from smoke_handshake import ACCD_PROTOCOL_VERSION, TCP_PORT, fail, write_cfg

SAMPLES = [
    "Hello",
    "A message longer than thirty-five characters must remain intact.",
    "Unicode stays intact: äöü ÄÖÜ ß",
    "x" * 254,
]

# (first, second, last) per client and the sender name each must get.
DRIVERS = [
    (("Jean", "Pierre", "Dupré"), "JEAN PIERRE DUPRé"),
    (("Bartholomew", "Alexander", "Montgomery-Smith"), "BARTHOLOMEW MONTGOMERY-SMITH"),
]


def frame(body):
    return struct.pack("<H", len(body)) + body


def join(steam, race_number, names):
    first, second, last = names
    body = bytes([0x09])
    body += struct.pack("<H", ACCD_PROTOCOL_VERSION)
    body += wstr_a("")
    body += build_driver_info(first=first, second=second, last=last, steam=steam)
    body += bytes(8)
    body += build_car_info(race_number=race_number)
    return frame(body)


def collect(proc, socks, bufs, duration):
    """Read frames for `duration` seconds, return (sock, sender, text) per 0x2b."""
    got = []
    end = time.monotonic() + duration
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return got
        if proc.poll() is not None:
            fail(f"accd exited with status {proc.returncode}")
        ready, _, _ = select.select(socks, [], [], left)
        for sock in ready:
            chunk = sock.recv(65536)
            if not chunk:
                fail("server closed a client connection")
            bufs[sock] += chunk
            while len(bufs[sock]) >= 2:
                n = struct.unpack_from("<H", bufs[sock])[0]
                if len(bufs[sock]) < 2 + n:
                    break
                pkt = bufs[sock][2 : 2 + n]
                bufs[sock] = bufs[sock][2 + n :]
                if pkt and pkt[0] == 0x2B:
                    r = Reader(pkt)
                    r.u8()
                    sender = r.fmt_a()
                    got.append((sock, sender, r.fmt_a()))


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-chat-") as tmp:
        write_cfg(tmp)
        proc = subprocess.Popen(
            [accd_bin, tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        socks = []
        bufs = {}
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

            for i, (names, _) in enumerate(DRIVERS):
                sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
                socks.append(sock)
                bufs[sock] = b""
                sock.sendall(join(f"S7656119900000000{i}", 90 + i, names))
                collect(proc, socks, bufs, 0.2)

            sends = [(0, text) for text in SAMPLES] + [(1, "Hello")]
            for i, text in sends:
                msg = bytes([0x2A]) + wstr_a(text) + struct.pack("<i", 0)
                socks[i].sendall(frame(msg))
                got = collect(proc, socks, bufs, 0.3)
                ok = {sock for sock, _, body in got if body == text}
                if ok != set(socks):
                    fail(f"{len(text)} code point message not relayed intact")
                want = DRIVERS[i][1]
                for _, sender, _ in got:
                    if sender != want:
                        fail(f"sender {sender!r}, want {want!r}")
            print("PASS: chat relayed intact to both clients with full sender names")
        finally:
            for sock in socks:
                sock.close()
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    main()
