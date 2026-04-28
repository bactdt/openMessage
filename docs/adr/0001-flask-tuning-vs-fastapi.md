# ADR 0001: Flask Tuning Before FastAPI Migration

## Status

Accepted

## Context

OpenMessage currently uses Flask with local JSON files for storage. The critical path is small: create an encrypted message, store one JSON file, then atomically read and delete that file exactly once. Recent stability work added transient lock semantics for short file handoff windows, and `scripts/storage_baseline.py` now provides a local baseline for storage throughput and p95 latency.

The next architecture question is whether to keep Flask and tune the current deployment model, or migrate the service to FastAPI/ASGI for async I/O.

## Decision

Keep Flask as the default runtime for now. Tune and measure the existing Flask deployment before starting a FastAPI migration.

FastAPI remains a valid future option if baseline data shows file I/O, request concurrency, or tail latency cannot meet production goals with Flask plus deployment tuning.

For C20, the selected route is Option A: keep Flask and tune deployment. The current local storage baseline does not show enough storage latency to justify a framework migration before the v2 E2E protocol work.

## Options Considered

### Option A: Keep Flask and Tune Deployment

- Preserve the current application model and API behavior.
- Tune production serving through Gunicorn worker/thread counts, timeouts, rate-limit storage, and filesystem placement.
- Use `scripts/storage_baseline.py` and API-level measurements to decide whether storage is actually the bottleneck.
- Avoid a framework migration while Zero-Knowledge/E2E protocol work is still pending.

Recommended Gunicorn starting point:

```bash
gunicorn \
  --bind 127.0.0.1:5000 \
  --workers 2 \
  --threads 4 \
  --worker-class gthread \
  --timeout 30 \
  --graceful-timeout 30 \
  --keep-alive 2 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  app:app
```

Production tuning guidance:

- Start with `workers = CPU cores` or `CPU cores * 2` on small hosts, then increase only when CPU has headroom and request queueing is visible.
- Use `gthread` with `threads` between `2` and `8` for moderate concurrency around short file I/O sections.
- Keep `timeout` and `graceful-timeout` at `30s` initially; OpenMessage requests should be short, so long timeouts mask worker stalls.
- Keep `keep-alive` low, around `2s`, when Gunicorn sits behind a reverse proxy.
- Use `max-requests` plus jitter to recycle workers defensively without synchronized restarts.
- Use a shared `RATE_LIMIT_STORAGE_URI` such as Redis in production. The default in-memory limiter is per process and becomes inconsistent with multiple workers.
- Keep `data/` on local persistent storage where possible; re-run the storage baseline if moving to network-backed volumes.

### Option B: Migrate to FastAPI/ASGI

- Move request handling to ASGI and introduce async route handlers.
- Potentially improve concurrency for network-bound work.
- Requires replacing Flask integrations, request lifecycle hooks, templates/static handling assumptions, rate-limit integration, test clients, and deployment docs.
- Local file operations are still blocking unless moved to threads or replaced with async-compatible storage, so migration alone may not improve the current bottleneck.

## Tradeoffs

Flask tuning has lower implementation risk and keeps behavior stable while measurement is still early. It also lets the project spend complexity budget on the E2E v2 protocol instead of framework churn.

FastAPI may become worthwhile if API latency is dominated by concurrent request scheduling or if future work introduces network-bound dependencies. It is less compelling while the service remains mostly CPU-light and file-I/O-bound.

## Migration Triggers

Revisit FastAPI if one or more of these become true:

- Storage/API baseline p95 remains above the production target after Gunicorn and filesystem tuning.
- Expected concurrent reads/writes cannot be handled by reasonable Flask worker/thread settings.
- New dependencies add meaningful async network I/O to the request path.
- The v2 E2E API introduces streaming, long polling, or other ASGI-friendly behavior.

## Baseline Result

Measured locally with:

```bash
./venv/bin/python scripts/storage_baseline.py --count 1000 --payload-bytes 1024
```

Result on the current development machine:

| Operation | Throughput/s | Avg ms | p95 ms |
| --- | ---: | ---: | ---: |
| `save_message` | 9489.80 | 0.105 | 0.135 |
| `pop_message` | 6134.24 | 0.163 | 0.199 |

This is a local filesystem baseline, not a production SLO. It is sufficient for the current decision because the measured file operations are sub-millisecond and the application does not yet have async network I/O in the request path. Production deployment should repeat the same baseline on the target host and storage volume.

## Route Decision

Choose Option A now: keep Flask and tune Gunicorn plus storage placement.

Do not start FastAPI migration until at least one migration trigger is observed after production-like measurement. The next architecture work should focus on v2 E2E protocol changes and API compatibility tests rather than framework churn.

## Consequences

- C19 documents concrete Gunicorn production settings before any framework migration.
- C20 uses baseline data to choose Flask tuning over a staged FastAPI migration for now.
- Any future FastAPI migration should preserve existing API responses, retry semantics, and one-time read guarantees through regression tests.
