#!/usr/bin/env bash
# Replay the sample logs through wazuh-logtest inside the manager container
# and print, for each line, the rule that fired.
#
# Usage: wazuh/test/run-logtest.sh [manager-container-name]
# The files in wazuh/decoders and wazuh/rules must already be installed
# (see wazuh/README.md) and the manager restarted.
set -euo pipefail

CONTAINER="${1:-single-node-wazuh.manager-1}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

for sample in "$HERE"/samples/*.log; do
  echo "=== $(basename "$sample") ==="
  # One logtest session per file, so frequency rules (brute force, crash
  # loop) see the earlier lines of the same file.
  docker exec -i "$CONTAINER" /var/ossec/bin/wazuh-logtest < "$sample" 2>&1 | awk '
    function flush() {
      if (event == "") return
      if (rule != "") printf "rule %-7s lvl %-3s %s\n", rule, level, desc
      else            printf "NO RULE             %s\n", event
    }
    /full event:/ {
      flush()
      sub(/^[^:]*: \047/, ""); sub(/\047$/, ""); event = $0; rule = ""; phase3 = 0
    }
    /Phase 3/                  { phase3 = 1 }
    phase3 && /\tid: /         { rule = $2;  gsub(/\047/, "", rule) }
    phase3 && /\tlevel: /      { level = $2; gsub(/\047/, "", level) }
    phase3 && /\tdescription: / { sub(/^[^:]*: \047/, ""); sub(/\047$/, ""); desc = $0 }
    END { flush() }'
  echo
done
