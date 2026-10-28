#!/usr/bin/env python3
"""
Smoke test: with dumpLeaderboards on, a driver laps in practice and
leaves. The server empties and resets the weekend, and the results
of the abandoned practice must be written with that lap, as the exe
does. Invoked from `make test`. Exits 0 on success, non-zero on any
failure.
"""

import json
import os
import signal
import socket
import struct
import subprocess
import tempfile
import time

from fake_client import build_car_info, build_driver_info, wstr_a
from smoke_handshake import ACCD_PROTOCOL_VERSION, TCP_PORT, fail, write_cfg

SETTINGS = {"serverName": "smoke", "dumpLeaderboards": 1}
LAP_MS = 95000


def frame(body):
    return struct.pack("<H", len(body)) + body


def join():
    body = bytes([0x09])
    body += struct.pack("<H", ACCD_PROTOCOL_VERSION)
    body += wstr_a("")
    body += build_driver_info(steam="S76561199000000001")
    body += bytes(8)
    body += build_car_info(race_number=91)
    return frame(body)


def lap(ms):
    """Two 0x20 sector splits, then the 0x21 lap completed."""
    out = frame(struct.pack("<BiBiH", 0x20, ms // 3, 0, 100000, 0))
    out += frame(struct.pack("<BiBiH", 0x20, ms // 3, 1, 100000, 0))
    out += frame(struct.pack("<BiiBHB", 0x21, ms, 100000, 0, 0, 0))
    return out


def results_with_lap(path):
    if not os.path.isdir(path):
        return None
    for name in sorted(os.listdir(path)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(path, name)) as f:
                obj = json.load(f)
        except (OSError, ValueError):
            continue
        if any(lp.get("laptime") == LAP_MS for lp in obj.get("laps", [])):
            return obj
    return None


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-empty-") as tmp:
        cfg = os.path.join(tmp, "cfg")
        os.mkdir(cfg)
        write_cfg(cfg)
        with open(os.path.join(cfg, "settings.json"), "w") as f:
            json.dump(SETTINGS, f)
        proc = subprocess.Popen(
            [accd_bin, cfg],
            cwd=tmp,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
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

            sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
            sock.sendall(join())
            time.sleep(0.5)
            sock.sendall(lap(LAP_MS))
            time.sleep(0.5)
            sock.close()

            results = os.path.join(tmp, "results")
            obj = None
            end = time.monotonic() + 5.0
            while obj is None and time.monotonic() < end:
                if proc.poll() is not None:
                    fail(f"accd exited with status {proc.returncode}")
                time.sleep(0.2)
                obj = results_with_lap(results)
            if obj is None:
                fail("no results file for the abandoned practice")
            print("PASS: emptying the server writes the abandoned session")
        finally:
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
