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
import glob
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat()}] {msg}")


def _kill_descendants(pid: int) -> None:
    for task in glob.glob("/proc/*/status"):
        try:
            with open(task) as fh:
                data = fh.read()
            ppid = None
            for line in data.splitlines():
                if line.startswith("PPid:"):
                    ppid = int(line.split()[1])
                    break
            if ppid != pid:
                continue
            child = int(task.split("/")[2])
            name = open(f"/proc/{child}/comm").read().strip()
            if name == "tee":
                continue
            os.kill(child, signal.SIGKILL)
            log(f"[client] Killed PID {child} ({name})")
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_INTERVAL = 30  # seconds
DEFAULT_DEST = "./downloads"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_FBSHOT_LOVE = os.path.join(os.path.dirname(_SCRIPT_DIR), "fbshot.love")
DEFAULT_SCREENSHOT_CMD = f"love {_FBSHOT_LOVE} {{}}"

CONNECT_TIMEOUT   = 10  # seconds for HTTP connect / read
DISCOVERY_PORT    = 8766
DISCOVERY_TIMEOUT = 30  # seconds to wait for a broadcast before giving up
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "client.json")


def load_config() -> dict:
    defaults = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "interval": DEFAULT_INTERVAL,
        "dest": DEFAULT_DEST,
        "screenshot_cmd": DEFAULT_SCREENSHOT_CMD,
    }
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as fh:
            return {**defaults, **json.load(fh)}
    with open(CONFIG_FILE, "w") as fh:
        json.dump(defaults, fh, indent=2)
        fh.write("\n")
    return defaults


# ---------------------------------------------------------------------------
# Server discovery
# ---------------------------------------------------------------------------
def discover_server(discovery_port: int = DISCOVERY_PORT, timeout: int = DISCOVERY_TIMEOUT):
    """Listen for a UDP broadcast from the server. Returns (host, port) or None."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("", discovery_port))
        log(f"[client] Listening for server broadcast on UDP port {discovery_port} (timeout {timeout}s) …")
        data, addr = sock.recvfrom(256)
        info = json.loads(data.decode())
        host = addr[0]
        port = int(info["port"])
        log(f"[client] Discovered server at {host}:{port}")
        return host, port
    except TimeoutError:
        log("[client] Discovery timed out, using configured host.")
        return None
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        log(f"[client] Discovery error: {exc}")
        return None
    finally:
        sock.close()


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


def download_zip(host: str, port: int, dest: str, expected_name: str, screenshot_cmd: str = DEFAULT_SCREENSHOT_CMD) -> bool:
    """
    Stream GET /download to dest/<expected_name>.
    Returns True on success, False on failure.
    """
    url = build_url(host, port, "/download")
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

    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
        sh_files = [n for n in names if n.endswith(".sh") and "/" not in n]
        if sh_files:
            sh_name = sh_files[0]
            root_folders = []
            for name in names:
                if "/" in name:
                    root_folders.append(name.split("/")[0])
                elif name.endswith("/"):
                    root_folders.append(name.rstrip("/"))
            root_folders = list(set(root_folders))
            json_name = os.path.splitext(sh_name)[0] + ".json"
            json_path = os.path.join(dest, json_name)
            with open(json_path, "w") as fh:
                json.dump(
                    {
                        "filename": sh_name,
                        "foldername": root_folders[0] if root_folders else "",
                    },
                    fh,
                )
            log(f"[client] Wrote {json_path}")

            with open(json_path) as fh:
                info = json.load(fh)

            autoinstall = "/roms/ports/PortMaster/autoinstall"
            no_zips = not os.path.isdir(autoinstall) or not any(
                f.lower().endswith(".zip") for f in os.listdir(autoinstall)
            )
            if no_zips:
                script_path = os.path.join("/roms/ports", info["filename"])
                sdt_log = os.path.join(dest, "sdt.log")
                with open(sdt_log, "w") as fh:
                    proc = subprocess.Popen(
                        ["bash", script_path],
                        stdout=fh,
                        stderr=subprocess.STDOUT,
                        cwd="/roms/ports",
                        start_new_session=True,
                    )

                time.sleep(2)
                screenshot_path = os.path.join(os.path.abspath(dest), "screenshot.png")
                r = subprocess.run(shlex.split(screenshot_cmd.replace("{}", screenshot_path)), capture_output=True, text=True)
                if r.returncode != 0:
                    log(f"[client] Screenshot failed (exit {r.returncode}): {r.stderr.strip() or r.stdout.strip()}")
                else:
                    log(f"[client] Saved screenshot to {screenshot_path}")

                _kill_descendants(proc.pid)
                log(f"[client] Killed app launched by {script_path}")

                proc.wait()
                log(f"[client] {script_path} finished, output in {sdt_log}")

                if info.get("foldername"):
                    src_log = os.path.join("/roms/ports", info["foldername"], "log.txt")
                    if os.path.isfile(src_log):
                        shutil.copy(src_log, os.path.join(dest, "log.txt"))
                        log(f"[client] Copied {src_log} to {dest}")

                    out_dir = os.path.join(dest, f"{info['foldername']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                    os.makedirs(out_dir, exist_ok=True)
                    for f in [out_path, json_path, screenshot_path, sdt_log,
                              os.path.join(dest, "log.txt")]:
                        if os.path.isfile(f):
                            shutil.move(f, os.path.join(out_dir, os.path.basename(f)))
                    log(f"[client] Moved files to {out_dir}")

    return True


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------
def run_client(host: str, port: int, interval: int, dest: str, screenshot_cmd: str = DEFAULT_SCREENSHOT_CMD):
    log(f"[client] Polling http://{host}:{port} every {interval}s")
    log(f"[client] Downloads will be saved to: {os.path.abspath(dest)}")
    log("[client] Press Ctrl+C to stop.\n")

    last_downloaded: str | None = None  # filename of the last file we fetched

    while True:
        status = fetch_status(host, port)

        if status is None:
            # Server unreachable — already printed a message inside fetch_status
            pass

        elif status.get("status") == "none":
            log("[client] No zip available on server.")

        else:
            name = status.get("name", "")
            size = status.get("size", "?")
            mtime = status.get("mtime", "0")

            file_key = f"{name}@{mtime}"

            if file_key == last_downloaded:
                log(f"[client] {name} ({size} bytes) — already downloaded, skipping.")
            else:
                log(f"[client] New zip found: {name} ({size} bytes)")
                ok = download_zip(host, port, dest, name, screenshot_cmd)
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
    config = load_config()

    parser = argparse.ArgumentParser(description="Zip-file polling client")
    parser.add_argument(
        "--host",
        default=None,
        help=f"Server host; if omitted, auto-discover via UDP broadcast (fallback: {config['host']})",
    )
    parser.add_argument(
        "--port",
        default=config["port"],
        type=int,
        help=f"Server port (default: {config['port']})",
    )
    parser.add_argument(
        "--interval",
        default=config["interval"],
        type=int,
        help=f"Poll interval in seconds (default: {config['interval']})",
    )
    parser.add_argument(
        "--dest",
        default=config["dest"],
        help=f"Download destination folder (default: {config['dest']})",
    )
    parser.add_argument(
        "--screenshot-cmd",
        default=config["screenshot_cmd"],
        help=f"Screenshot command with {{}} for output path (default: {config['screenshot_cmd']})",
    )
    args = parser.parse_args()

    if args.host is None:
        discovered = discover_server()
        host = discovered[0] if discovered else config["host"]
        port = discovered[1] if discovered else args.port
    else:
        host = args.host
        port = args.port

    try:
        run_client(host, port, args.interval, args.dest, args.screenshot_cmd)
    except KeyboardInterrupt:
        pass

    log("[client] Stopped.")


if __name__ == "__main__":
    main()
