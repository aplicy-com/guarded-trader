#!/usr/bin/env bash
# Run the research harness in a throwaway sandbox (ADR-0007 shape, ADR-0021).
#
#   scripts/research-harness.sh run C01Tsmom1d [--seeds 200] [--no-register]
#
# The container has: no network (--network none), a read-only root filesystem, no Linux
# capabilities, no privilege escalation, and none of the .env secrets (no --env-file). The repo,
# including the candle data, is mounted read-only. The only writable mounts are the trial
# registry directory (services/research/state) and the run output directory
# (services/research/runs), plus an in-memory /tmp. It is removed when the run ends.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
image="freqtradeorg/freqtrade:2026.8"   # same pin as infra/docker-compose.yml
state="$repo/services/research/state"
out="$repo/services/research/runs"
mkdir -p "$state" "$out"

test -f "$repo/services/freqtrade/user_data/data/kraken/kraken-archive-report.json" || {
	echo "No converted Kraken archive data. Run: make kraken-data" >&2
	exit 2
}

exec docker run --rm \
	--network none \
	--read-only --tmpfs /tmp:rw,size=2g \
	--cap-drop ALL --security-opt no-new-privileges \
	-v "$repo:/repo:ro" \
	-v "$state:/state" \
	-v "$out:/out" \
	-e PYTHONPATH=/repo/services/research/src \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-w /tmp \
	--entrypoint python \
	"$image" -m research_harness.cli "$@"
