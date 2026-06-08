# PortMaster AutoTest

Automated testing tool for PortMaster game ports. A client-server pair that watches for new zip releases, downloads them, runs the game, takes a screenshot, and collects logs.

## Components

### Server (`src/zip_server.py`)

Watches a folder for `.zip` files and serves the latest one via HTTP.

| Endpoint | Description |
|---|---|
| `GET /` | Info page with current zip name and size |
| `GET /status` | JSON with `status`, `name`, `size`, `mtime` |
| `GET /download` | Streams the zip file as `application/zip` |

Dedup uses `name@mtime` — if a zip is replaced in-place with the same modification time, the client won't detect the change.

**Config:** CLI args or `server.json` (auto-created):
```
--host HOST    Bind address (default: 0.0.0.0)
--port PORT    Port (default: 8765)
--folder DIR   Folder to watch (default: ./serve_folder)
```

### Client (`src/zip_client.py`)

Polls the server at a configurable interval and processes new zips.

1. **Download** — fetches the zip if `name@mtime` differs from the last download
2. **Inspect** — finds the root `.sh` script and root folder name inside the zip, writes metadata to `<script>.json`
3. **Auto-run** — if `/roms/ports/PortMaster/autoinstall` has no zips, runs the `.sh` script from `/roms/ports/` and captures output to `sdt.log`
4. **Screenshot** — waits 2s, then captures a screenshot via the configured command
5. **Kill** — kills all child processes (except `tee`) via SIGKILL, then waits for the script to finish
6. **Collect** — copies `/roms/ports/<foldername>/log.txt` to `dest/log.txt`
7. **Archive** — moves all files into `dest/<foldername>_<timestamp>/`

Dedup uses `name@mtime` — replaced-on a zip with the same timestamp will not trigger a re-download.

**Config:** CLI args or `client.json` (auto-created):
```
--host HOST       Server address (default: 127.0.0.1)
--port PORT       Server port (default: 8765)
--interval SECS   Poll interval (default: 30)
--dest DIR        Download destination (default: ./downloads)
--screenshot-cmd  Screenshot command with {} for output path (default: spectacle -b -n -o {})
```

## Requirements

- Python 3.10+
- Linux with `/proc` — for process tree walking
- Screenshot tool (default: `spectacle`, configurable via `--screenshot-cmd`)

## tools/fbshot — portable screenshot for ARM devices

`spectacle` is KDE-only and unavailable on most PortMaster handhelds. `tools/fbshot` is a headless [Love2D](https://love2d.org/) app that reads `/dev/fb0` directly (via LuaJIT FFI + `FBIOGET_VSCREENINFO` ioctl) and saves a PNG without creating any window or disturbing the running game.

**Supported pixel formats:** RGB565 (16 bpp) and any 32 bpp format (BGRA, XRGB, RGBA — channel order is read from the ioctl response).

**Build** the `.love` file (a plain zip):
```
cd tools/fbshot && zip -0 ../../fbshot.love conf.lua main.lua
```

**Use** it as the screenshot command:
```
--screenshot-cmd "love /path/to/fbshot.love {}"
```

Requires the `love` (Love2D 11.x) binary on the target device. On many PortMaster devices this is already present since Love2D ports are common.
