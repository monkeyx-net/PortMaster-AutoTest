#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/tools/fbshot"
zip -0 "$SCRIPT_DIR/fbshot.love" conf.lua main.lua
echo "Built $SCRIPT_DIR/fbshot.love"
