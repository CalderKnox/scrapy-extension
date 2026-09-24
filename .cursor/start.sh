#!/usr/bin/env bash
# Per-boot startup for the scrapy-extension Cloud Agent environment.
# Brings up a loopback-only Redis so the live integration tier and the runnable
# examples work out of the box. Idempotent and tolerant of restarts.
set -euo pipefail

if ! command -v redis-server >/dev/null 2>&1; then
  echo "redis-server not installed; skipping (unit suite is unaffected)."
  exit 0
fi

if redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
  echo "Redis already running on 127.0.0.1:6379."
  exit 0
fi

# Loopback bind only; development-only, never exposed beyond the local machine.
redis-server \
  --daemonize yes \
  --bind 127.0.0.1 \
  --port 6379 \
  --save '' \
  --appendonly no \
  --dir /tmp \
  --pidfile /tmp/redis-scrapy-ext.pid \
  --logfile /tmp/redis-scrapy-ext.log

for _ in $(seq 1 30); do
  if redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    echo "Redis is ready on 127.0.0.1:6379."
    exit 0
  fi
  sleep 1
done

echo "WARNING: Redis did not become ready in time." >&2
exit 0
