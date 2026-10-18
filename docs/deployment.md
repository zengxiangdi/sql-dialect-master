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

## 7. Operational checklist

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
