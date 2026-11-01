#!/usr/bin/env bash
# Run a research round-2 module in the same throwaway sandbox as scripts/research-harness.sh
# (ADR-0021): no network, read-only root and repo, no capabilities, no .env. Writable: the trial
# registry directory, the run output directory, and an in-memory /tmp.
#
#   scripts/research-round2.sh coverage            # data coverage report (WP-A)
#   scripts/research-round2.sh prereg              # write the frozen trials to the registry (WP-A)
#   scripts/research-round2.sh run [--seeds 200]   # score every pre-registered trial (WP-C)
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
image="freqtradeorg/freqtrade:2026.8"   # same pin as infra/docker-compose.yml
state="$repo/services/research/state"
out="$repo/services/research/runs/round2"
mkdir -p "$state" "$out"
cmd="${1:?usage: research-round2.sh coverage|prereg|run [args]}"; shift
case "$cmd" in coverage|prereg|run) ;; *) echo "unknown command: $cmd" >&2; exit 2 ;; esac

extra=()
if [ "$cmd" = prereg ]; then
	# Pre-registration must point at a commit that contains the frozen spec, unmodified.
	git -C "$repo" diff --quiet HEAD -- services/research/candidates-round2.json \
		|| { echo "candidates-round2.json has uncommitted changes; commit it first" >&2; exit 2; }
	extra=(--commit "$(git -C "$repo" rev-parse HEAD)")
fi

docker run --rm --name "research-round2-$$" \
	--network none \
	--cpus "${HARNESS_CPUS:-4}" --memory "${HARNESS_MEMORY:-4g}" --pids-limit 256 \
	--read-only --tmpfs /tmp:rw,size=1g \
	--cap-drop ALL --security-opt no-new-privileges \
	-v "$repo:/repo:ro" \
	-v "$state:/state" \
	-v "$out:/out" \
	-e PYTHONPATH=/repo/services/research/src \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-w /tmp \
	--entrypoint python \
	"$image" -m "research_harness.round2.$cmd" ${extra[@]+"${extra[@]}"} "$@"
