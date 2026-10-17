#!/usr/bin/env bash
# check-worker-net.sh SUBNET -- refuse a team-net whose subnet is not SUBNET.
#
# The egress rules (team-egress) match the worker subnet by address. A team-net
# left by an earlier install, or created by hand, with any other subnet would
# leave workers unrestricted while setup reported success. Exit 0 when the
# network is absent (setup creates it) or matches; exit 1 otherwise.
set -euo pipefail
expected="${1:?usage: check-worker-net.sh SUBNET}"
docker network inspect team-net >/dev/null 2>&1 || exit 0
actual="$(docker network inspect team-net --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' | xargs)"
if [ "${actual}" != "${expected}" ]; then
  echo "docker network team-net has subnet '${actual}', expected '${expected}':" >&2
  echo "the egress rules would not cover it. Remove it (docker network rm team-net) and rerun setup." >&2
  exit 1
fi
