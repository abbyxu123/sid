#!/usr/bin/env python3
"""Bridge Seeed MR60BHA2/XIAO serial logs into the Cat.TV device gateway.

This script is intentionally standard-library only. It does not flash the
sensor or the main Cat.TV board; it only reads USB serial text and POSTs the
latest parsed sample to `/v1/sensor/mmwave`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import termios
import time
import urllib.request


DEFAULT_PORT = "/dev/cu.usbmodem101"
DEFAULT_GATEWAY = "http://127.0.0.1:8090/v1/sensor/mmwave"
STATE_RE = re.compile(r"'(?P<name>[^']+)':.*?state\s+(?P<value>-?\d+(?:\.\d+)?)", re.I)


def parse_line(line: str) -> dict:
    match = STATE_RE.search(line)
    if not match:
        return {}
    name = match.group("name").lower()
    value = float(match.group("value"))
    if "target number" in name:
        return {"target_count": int(round(value)), "present": value > 0}
    if "distance to detection object" in name:
        return {"distance_cm": round(value, 1)}
    if "respiratory rate" in name:
        return {"respiration_bpm": int(round(value))}
    if "heart rate" in name:
        return {"heart_bpm": int(round(value))}
    if "illuminance" in name:
        return {"illuminance_lux": round(value, 1)}
    return {}


def open_serial(path: str, baud: int):
    baud_const = {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
    }.get(baud)
    if baud_const is None:
        raise ValueError(f"Unsupported baud rate: {baud}")
    fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = baud_const
    attrs[5] = baud_const
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def post_sample(url: str, sample: dict) -> None:
    data = json.dumps(sample).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        resp.read()


def run(port: str, gateway: str, baud: int, dry_run: bool, once: bool) -> None:
    fd = open_serial(port, baud)
    buffer = b""
    sample: dict = {"source": "mr60bha2-usb"}
    last_post = 0.0
    print(f"mmWave bridge reading {port} -> {gateway}", flush=True)
    try:
        while True:
            try:
                chunk = os.read(fd, 2048)
            except BlockingIOError:
                chunk = b""
            if chunk:
                buffer += chunk
                *lines, buffer = buffer.split(b"\n")
                for raw in lines:
                    try:
                        line = raw.decode("utf-8", "ignore").strip()
                    except Exception:
                        continue
                    update = parse_line(line)
                    if update:
                        sample.update(update)
            now = time.time()
            enough = {"heart_bpm", "respiration_bpm", "distance_cm"} & set(sample)
            if enough and now - last_post >= 1.0:
                last_post = now
                payload = dict(sample)
                payload["ts"] = now
                if dry_run:
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                else:
                    try:
                        post_sample(gateway, payload)
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                    except Exception as exc:
                        print(f"post failed: {exc}", file=sys.stderr, flush=True)
                if once:
                    return
            time.sleep(0.05)
    finally:
        os.close(fd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=os.environ.get("MMWAVE_PORT", DEFAULT_PORT))
    parser.add_argument("--gateway", default=os.environ.get("MMWAVE_GATEWAY", DEFAULT_GATEWAY))
    parser.add_argument("--baud", type=int, default=int(os.environ.get("MMWAVE_BAUD", "115200")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="print/post one parsed sample then exit")
    args = parser.parse_args()
    run(args.port, args.gateway, args.baud, args.dry_run, args.once)


if __name__ == "__main__":
    main()
