#!/bin/sh
# Restore the MELBCUP raw-data archive into $1 (default ./restore) and verify every file.
# Usage: sh restore.sh [target-dir]   (run in the folder holding the bundles and manifests)
set -e
A="$(pwd)"
T="${1:-restore}"
sha256sum -c BUNDLES.sha256                      # 1. every bundle intact
mkdir -p "$T"
for b in meetings-*.tar racingcom-*.tar betfair-raw.tar; do tar -xf "$b" -C "$T"; done
cd "$T" && sha256sum -c --quiet "$A/MANIFEST.sha256" && echo "restore OK: $(wc -l < "$A/MANIFEST.sha256") files verified"   # 2. every file intact
