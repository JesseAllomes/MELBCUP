#!/bin/sh
# Picker review, token-free. Usage: sh tools/nba/review/run_all.sh forward-v2.jsonl [out dir]
# Writes legs.txt, multis.txt, structure.txt, extras.txt, replay.txt (replay takes a few minutes).
set -e
D=$(cd "$(dirname "$0")" && pwd); F=$1; O=${2:-.}
for s in legs_types multis structure extras replay; do
  python3 -I "$D/$s.py" "$F" > "$O/${s%_types}.txt"; echo "$s done"
done
