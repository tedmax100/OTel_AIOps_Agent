#!/usr/bin/env bash
# Delete the Day1 bench cluster. The telemetry lives only in the pod, so this
# throws the data away — rerun up.sh to regenerate a fresh 24h window.
set -euo pipefail
k3d cluster delete aiops-day01
