#!/usr/bin/env bash
# Pick the first GPU node type with actual stock, cheapest first.
#
# Prints one line: "<zone> <node-type>" (for `scw k8s pool create`), or exits 3
# when nothing on the ladder is in stock anywhere in the region.
#
# The ladder crosses zones on purpose: GPU stock has bad nights per zone, and
# one zone can run dry of a card while the next still has it. A pricier card
# is fine for transcription: a job runs minutes, so even the top of the
# ladder is cents per meeting.
#
#   infra/gpu/pick-gpu.sh            # region from SCW_REGION, default fr-par
set -euo pipefail

REGION="${SCW_REGION:-fr-par}"

# zone:type, cheapest first. Types differ per zone by design.
LADDER=(
    "${REGION}-1:L4-1-24G"
    "${REGION}-2:L4-1-24G"
    "${REGION}-1:L4-2-24G"
    "${REGION}-2:L4-2-24G"
    "${REGION}-2:L40S-2-48G"
    "${REGION}-2:H100-1-80G"
)

for entry in "${LADDER[@]}"; do
    zone="${entry%%:*}"; ntype="${entry##*:}"
    avail=$(scw instance server-type list zone="$zone" -o json 2>/dev/null \
        | python3 -c "
import json, sys
rows = json.load(sys.stdin)
for row in rows:
    if row.get('name') == '$ntype':
        print(row.get('availability', 'unknown'))
        break
" || true)
    if [ "$avail" = "available" ]; then
        echo "$zone $ntype"
        exit 0
    fi
    printf '[pick-gpu] %s in %s: %s\n' "$ntype" "$zone" "${avail:-not listed}" >&2
done

echo "[pick-gpu] no GPU stock anywhere on the ladder; stay on CPU and retry another day" >&2
exit 3
