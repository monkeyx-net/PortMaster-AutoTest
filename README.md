# PortMaster AutoTest

Automated testing tool for PortMaster game ports. A client-server pair that watches for new zip releases, downloads them, runs the game, takes a screenshot, and collects logs.

## Components

### Server (`src/zip_server.py`)

Watches a folder for `.zip` files and serves the latest one via HTTP.

| Endpoint | Description |
|---|---|
| `GET /` | Info page with current zip name and size |
| `GET /status` | JSON with `status`, `name`, `size`, `mtime`, `md5` |
| `GET /download` | Streams the zip file as `application/zip` |

The server computes an MD5 hash of the zip on each `/status` request so clients can detect content changes even when modification times are preserved.

**Config:** CLI args or `server.json` (auto-created):
```
--host HOST    Bind address (default: 0.0.0.0)
--port PORT    Port (default: 8765)
--folder DIR   Folder to watch (default: ./serve_folder)
```

### Client (`src/zip_client.py`)

Polls the server at a configurable interval and processes new zips.

1. **Download** — fetches the zip if `name@md5` differs from the last download
2. **Inspect** — finds the root `.sh` script and root folder name inside the zip, writes metadata to `<script>.json`
3. **Auto-run** — if `/roms/ports/PortMaster/autoinstall` has no zips, runs the `.sh` script from `/roms/ports/` and captures output to `sdt.log`
4. **Screenshot** — waits 2s, then captures a screenshot via `spectacle`
5. **Kill** — kills all child processes (except `tee`) via SIGKILL, then waits for the script to finish
6. **Collect** — copies `/roms/ports/<foldername>/log.txt` to `dest/log.txt`
7. **Archive** — moves all files into `dest/<foldername>_<timestamp>/`

Dedup uses `name@md5` — any content change triggers a re-download regardless of file timestamp.

**Config:** CLI args or `client.json` (auto-created):
```
--host HOST       Server address (default: 127.0.0.1)
--port PORT       Server port (default: 8765)
--interval SECS   Poll interval (default: 30)
--dest DIR        Download destination (default: ./downloads)
```

## Requirements

- Python 3.10+
- `spectacle` (KDE screenshot tool) — for the screenshot feature
- Linux with `/proc` — for process tree walking
