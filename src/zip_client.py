#!/usr/bin/env python3
"""
zip_client.py — Polls a zip_server for a new zip file and downloads it.

Usage:
    python zip_client.py [--host HOST] [--port PORT] [--interval SECONDS] [--dest DIR]

Defaults:
    host     : 127.0.0.1
    port     : 8765
    interval : 30          (seconds between polls)
    dest     : ./downloads

The client checks every <interval> seconds.  When a zip becomes available
(and hasn't been downloaded before) it is saved to <dest>.
"""

import argparse
from datetime import datetime
import json
import os
import time
import urllib.error
import urllib.request


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat()}] {msg}")

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST     = "127.0.0.1"
DEFAULT_PORT     = 8765
DEFAULT_INTERVAL = 30          # seconds
DEFAULT_DEST     = "./downloads"

CONNECT_TIMEOUT  = 10          # seconds for HTTP connect / read


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_url(host: str, port: int, path: str) -> str:
    return f"http://{host}:{port}{path}"


def fetch_status(host: str, port: int) -> dict | None:
    """
    Call GET /status and parse the plain-text response.
    Returns a dict with keys: status, name, size, mtime
    or {'status': 'none'} when nothing is available.
    Returns None on connection error.
    """
    url = build_url(host, port, "/status")
    try:
        with urllib.request.urlopen(url, timeout=CONNECT_TIMEOUT) as resp:
            body = resp.read().decode().strip()
    except (urllib.error.URLError, OSError) as exc:
        log(f"[client] Could not reach server: {exc}")
        return None

    try:
        result: dict = json.loads(body)
    except json.JSONDecodeError:
        log(f"[client] Invalid status response: {body!r}")
        return {"status": "none"}
    return result


def download_zip(host: str, port: int, dest: str, expected_name: str) -> bool:
    """
    Stream GET /download to dest/<expected_name>.
    Returns True on success, False on failure.
    """
    url      = build_url(host, port, "/download")
    out_path = os.path.join(dest, expected_name)

    log(f"[client] Downloading {expected_name} …")
    try:
        with urllib.request.urlopen(url, timeout=CONNECT_TIMEOUT) as resp:
            os.makedirs(dest, exist_ok=True)
            with open(out_path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)  # 64 KB
                    if not chunk:
                        break
                    fh.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        log(f"[client] Download failed: {exc}")
        return False

    size = os.path.getsize(out_path)
    log(f"[client] Saved to {os.path.abspath(out_path)} ({size} bytes)")
    return True


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------
def run_client(host: str, port: int, interval: int, dest: str):
    log(f"[client] Polling http://{host}:{port} every {interval}s")
    log(f"[client] Downloads will be saved to: {os.path.abspath(dest)}")
    log(f"[client] Press Ctrl+C to stop.\n")

    last_downloaded: str | None = None   # filename of the last file we fetched

    while True:
        status = fetch_status(host, port)

        if status is None:
            # Server unreachable — already printed a message inside fetch_status
            pass

        elif status.get("status") == "none":
            log(f"[client] No zip available on server.")

        else:
            name  = status.get("name", "")
            size  = status.get("size", "?")
            mtime = status.get("mtime", "0")

            # Use name+mtime as a unique key so a replaced file is re-downloaded
            file_key = f"{name}@{mtime}"

            if file_key == last_downloaded:
                log(f"[client] {name} ({size} bytes) — already downloaded, skipping.")
            else:
                log(f"[client] New zip found: {name} ({size} bytes)")
                ok = download_zip(host, port, dest, name)
                if ok:
                    last_downloaded = file_key

        log(f"[client] Next check in {interval}s …\n")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Zip-file polling client")
    parser.add_argument("--host",     default=DEFAULT_HOST,     help=f"Server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port",     default=DEFAULT_PORT,     type=int, help=f"Server port (default: {DEFAULT_PORT})")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, type=int, help=f"Poll interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--dest",     default=DEFAULT_DEST,     help=f"Download destination folder (default: {DEFAULT_DEST})")
    args = parser.parse_args()

    try:
        run_client(args.host, args.port, args.interval, args.dest)
    except KeyboardInterrupt:
        pass

    log(f"[client] Stopped.")


if __name__ == "__main__":
    main()
