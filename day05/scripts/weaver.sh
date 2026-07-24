#!/usr/bin/env bash
# Thin wrapper around the official `otel/weaver` container so contributors
# don't need a local weaver install.
#
#   ./weaver.sh check                 # validate the registry (built-in policies)
#   ./weaver.sh check --policy        # also run our custom policies/*.rego
#   ./weaver.sh docs                  # generate Markdown docs -> weaver/docs/
#   ./weaver.sh live-check            # validate live OTLP against the registry
#   ./weaver.sh -- <raw weaver args>  # escape hatch
#
# Override the image/version with WEAVER_IMAGE, e.g.
#   WEAVER_IMAGE=otel/weaver:v0.18.2 ./weaver.sh check
set -euo pipefail

WEAVER_IMAGE="${WEAVER_IMAGE:-otel/weaver:v0.24.0}"
WEAVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../weaver" && pwd)"
REGISTRY="/home/weaver/registry"
POLICIES="/home/weaver/policies"

run() {
  # Allocate a TTY only when we have one (so this works in CI too).
  local tty=()
  [[ -t 0 ]] && tty=(-it)
  # Mount the weaver/ dir read-write so `docs` can write generated output back.
  docker run --rm ${tty[@]+"${tty[@]}"} \
    -v "${WEAVER_DIR}:/home/weaver" \
    "${WEAVER_IMAGE}" "$@"
}

cmd="${1:-check}"
shift || true

case "${cmd}" in
  check)
    args=(registry check -r "${REGISTRY}")
    if [[ "${1:-}" == "--policy" ]]; then
      args+=(-p "${POLICIES}")
    fi
    run "${args[@]}"
    ;;
  docs)
    # Requires templates under weaver/templates/. See README "Generating docs".
    run registry generate -r "${REGISTRY}" markdown /home/weaver/docs
    ;;
  live-check)
    # Reads OTLP samples on stdin (or set an OTLP receiver — see weaver docs).
    run registry live-check -r "${REGISTRY}" "$@"
    ;;
  --)
    run "$@"
    ;;
  *)
    echo "unknown command: ${cmd}" >&2
    echo "usage: weaver.sh [check [--policy] | docs | live-check | -- <args>]" >&2
    exit 2
    ;;
esac
