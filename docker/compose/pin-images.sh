#!/usr/bin/env bash
# Resolve every third-party image to its @sha256 digest and print pinned lines (D6: never a floating tag).
# Usage: ./pin-images.sh   — then paste the digests into docker-compose.yml / mcp-servers.json.
set -euo pipefail

images=(
  "redis/redis-stack:latest"
  "mcp/filesystem:latest"
  "mcp/git:latest"
  "mcp/memory:latest"
  "mcp/sequentialthinking:latest"
  "mcp/time:latest"
  "mcp/fetch:latest"
)

for image in "${images[@]}"; do
  docker pull "$image" >/dev/null
  digest=$(docker inspect --format='{{index .RepoDigests 0}}' "$image")
  echo "${image}  ->  ${digest}"
done
