# Production deployment

This guide describes the deployment boundaries implemented by the current
FastAPI service. It does not define a container image or a reverse-proxy
configuration for a specific hosting provider.

## 1. Deployment model

The API can run as one process or behind multiple worker processes. The
`SDM_API_WORKERS` setting defaults to `4`; `SDM_API_QUEUE_SIZE` also defaults to
`4` and bounds work waiting for a CPU worker. When the worker capacity or queue
is full, the API returns HTTP 503 with `Retry-After`.

`SDM_REQUEST_TIMEOUT` defaults to `30` seconds. A request that waits longer
than this configured timeout receives HTTP 504; the underlying worker keeps its
capacity until its work finishes.

The request-body guard rejects bodies larger than 512 KiB before endpoint
processing. SQL parsing and transpilation use a default maximum input length of
100,000 characters from `SDM_TRANSPILER_MAX_SQL_LENGTH`; the parser limit falls
back to the same value unless `SDM_PARSER_MAX_SQL_LENGTH` is explicitly set.

For a single process, the in-memory rate-limit backend is suitable. For several
workers or instances, use Redis so all workers share one rate-limit counter.

### Batch conversion

`POST /api/convert/batch` accepts one source/target dialect pair and between
one and `SDM_MAX_BATCH_SIZE` statements (default `100`). The entire JSON body
remains subject to the 512 KiB limit, and each SQL statement uses the existing
SQL-length and security checks. Empty or oversized arrays and non-string
items return 422; unsupported dialects return 400. Ordinary item failures
return HTTP 200 with per-item errors, even when every item fails.

A batch occupies one worker slot and runs its statements sequentially. The
default 30-second `SDM_REQUEST_TIMEOUT` covers queue waiting plus execution
for the whole batch, not a separate budget for each statement. It does not
cover the entire HTTP lifecycle, such as body reading or response serialization.
Capacity rejection returns 503 with `Retry-After`; timeout returns 504. Neither
response contains partial results. A 504 does not cancel the batch: background
work may continue through the remaining statements, update the cache, and
retain its slot until completion.

Rate limiting counts one HTTP request per batch, rather than one request per
statement. Prefer smaller batches when latency and fairness to other requests
matter; the default 100-statement limit does not guarantee completion within
30 seconds.

## 2. Reverse proxy and TLS

Terminate TLS at the reverse proxy and forward HTTP traffic to the Uvicorn
application. The proxy must preserve the original host, scheme, and forwarding
chain. A minimal Nginx location is:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

The application does not trust `X-Forwarded-For` by default. Set
`SDM_TRUSTED_PROXIES` to the direct proxy IPs or CIDRs only when the direct
peer is a trusted proxy. The application rejects `0.0.0.0/0` and `::/0` as
trusted networks. If the proxy address is not included, all users behind the
proxy share the direct peer's rate-limit bucket and that peer is recorded in
the structured logs.

HSTS is a responsibility of the TLS termination layer. The application does
not set HSTS.

## 3. Authentication and CORS

`SDM_API_KEY` is empty by default, which keeps local business endpoints
public. Set it in production. Clients can send the value in `X-API-Key` or as
`Authorization: Bearer <key>`.

`SDM_ALLOWED_ORIGINS` is a comma-separated list of explicit origins. Keep the
list limited to the browser origins that need access. Do not combine a
wildcard origin with credentialed requests; the application enables CORS
credentials.

The API exposes operational response headers including `Retry-After`,
`X-API-Version`, `X-Process-Time`, `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `X-Request-ID`.

## 4. Rate limiting

Rate limiting is enabled by default:

- `SDM_RATE_LIMIT_ENABLED=true` controls enforcement.
- `SDM_RATE_LIMIT_REQUESTS=100` sets the fixed-window request count.
- `SDM_RATE_LIMIT_WINDOW=60` sets the window length in seconds.
- `SDM_RATE_LIMIT_BACKEND=memory` selects the per-process backend.
- `SDM_RATE_LIMIT_BACKEND=redis` selects the shared Redis backend.
- `SDM_REDIS_URL` is required when the Redis backend is selected.

The Redis backend pings Redis during startup and fails fast when the service is
unreachable. Use Redis for multi-worker or multi-instance deployments that
need one global limit. The memory backend is scoped to one process.

Behind a reverse proxy, configure `SDM_TRUSTED_PROXIES` correctly. Without it,
the proxy peer is the client identity and all users sharing that proxy may
share one bucket.

## 5. Health and readiness

- `/health` is a process liveness endpoint and does not run dependency probes.
- `/ready` runs the authorized readiness checks.
- `/health/deep` runs the authorized deep health checks.

Without a configured `SDM_HEALTH_PROBE_TOKEN`, readiness and deep health are
available only to loopback clients. Once the token is configured, callers must
send `X-Health-Probe-Token` with the matching value, including loopback
callers. A proxy deployment must configure the token and forward this header
to the application.

Readiness authorization never uses `X-Forwarded-For` to widen access. Do not
rely on forwarding headers to bypass the probe token.

## 6. Cache and security headers

The response cache policy is explicit:

- `POST /api/*` responses, including SQL conversion, parsing, diff, NL2SQL,
  and type mapping, use `Cache-Control: no-store`.
- `/health`, `/ready`, and `/health/deep` use `Cache-Control: no-store`.
- Public catalog GET endpoints use `Cache-Control: private, max-age=60`.
- `/api/stats` and `/` use `Cache-Control: private, max-age=15`.
- `/docs`, `/redoc`, `/openapi.json`, and CORS preflight responses receive no
  cache policy from the application middleware.

The application sends `X-XSS-Protection: 0`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, and a strict referrer policy. It does not set a CSP;
configure CSP at the static frontend or reverse-proxy layer after validating
the policies required by the frontend and API documentation pages. It also
does not set HSTS; configure that at the TLS termination layer.

## 7. Metrics

Metrics are disabled by default. Enable them with `SDM_METRICS_ENABLED=true`
and set the dedicated `SDM_METRICS_TOKEN`; requests must send that value in
the `X-Metrics-Token` header. Keep `/metrics` on an internal network and do
not expose it publicly. It is separate from the business API key and the
health-probe token.

The initial implementation exposes process-local metrics. In a multi-worker
deployment, each worker has its own counters and cache/worker gauges; a
Prometheus scrape may reach one worker at a time. Prometheus multiprocess
aggregation is deferred to a later batch.

The endpoint exposes build info, HTTP request totals and duration histograms,
rate-limit rejections, conversion outcomes, worker capacity/in-use/rejection/
timeout statistics, transpiler cache hits/misses/evictions/size, and the
in-memory rate-limit active-client gauge. HTTP labels use normalized methods,
FastAPI route templates, and status classes (`2xx`, `3xx`, `4xx`, `5xx`).
Conversion labels use the fixed supported dialect names and a fixed result
vocabulary. Labels never contain SQL, query strings, client IPs, request IDs,
error text, table names, or column names. The `/metrics` scrape itself is not
counted as an HTTP request.

Batch conversion adds three metrics, also scoped to one process:

| Metric | Labels | Meaning |
|--------|--------|---------|
| `sdm_transpile_batch_requests_total` | `source`, `target`, `result` | One outcome for each request entering the batch handler |
| `sdm_transpile_batch_items_total` | `source`, `target`, `result` | Item outcomes only after a complete result list reaches the handler |
| `sdm_transpile_batch_size` | None | Histogram of validated statement counts before worker admission |

Batch request results are `success` (all items succeeded), `partial_failure`
(both successful and failed items), `error` (all items failed, or a request-level
503/504/500), and `validation_error` (an unsupported dialect found in the
handler). Item results are only `success` or `error`. Dialect labels contain
normalized supported names or the fixed value `unknown` for invalid input.
The existing `sdm_transpile_requests_total` continues to count only the
single-conversion endpoint; batch items do not increment it.

The size histogram has fixed buckets of 1, 2, 5, 10, 20, 50, and 100 statements,
plus the implicit `+Inf` bucket. It is observed after dialect validation and
before worker admission, including batches that subsequently receive 503/504.
Rejections before the handler, such as authentication, body-size, rate-limit,
or Pydantic validation failures, use the existing HTTP metrics and do not
increment batch metrics.

503/504 responses do not increment the item counter. Even if a timed-out
background batch later completes, its items remain excluded because the
handler did not receive its complete results. Cache statistics can still
increase as that background work finishes. Batch labels never include item
indices or batch lengths; the existing privacy and per-process boundaries
apply to all three metrics.

Prometheus configuration can send the token in a header:

```yaml
scrape_configs:
  - job_name: sql-dialect-master
    metrics_path: /metrics
    static_configs:
      - targets: ["api.internal:8000"]
    http_headers:
      X-Metrics-Token:
        values: ["${SDM_METRICS_TOKEN}"]
```

For Prometheus versions without `http_headers`, configure the reverse proxy to
inject `X-Metrics-Token` on the internal scrape path. Do not put the token in a
URL query parameter or in logs.

## 8. Operational checklist

- Terminate TLS at the proxy and forward the required host, scheme, and XFF
  headers.
- Set `SDM_API_KEY` and `SDM_HEALTH_PROBE_TOKEN` in production.
- Configure `SDM_TRUSTED_PROXIES` with only the direct proxy IPs/CIDRs.
- Use Redis rate limiting for multiple workers or instances.
- Review worker, queue, timeout, body-size, and SQL-size settings for the
  expected workload.
- Monitor 429, 503, and 504 responses and the structured request logs.
- Verify `/health` and authorized `/ready` responses from the proxy path.
- Do not expose API keys, Redis URLs, or probe tokens in logs or committed
  configuration.
- Before a release, wait for CI, Quality, CodeQL, and Benchmark checks to
  pass.
