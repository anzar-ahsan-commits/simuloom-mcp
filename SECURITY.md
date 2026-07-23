# Security policy

## Reporting a vulnerability

Please use GitHub private vulnerability reporting for security issues. Do not include API
keys, production payloads, customer schemas, or protected health information in a public
issue, pull request, simulation bundle, or reproduction case.

## Deployment expectations

- Enable authentication outside isolated local development.
- Generate long, random API keys and store them in a secret manager.
- Set a stable, high-entropy `SIMULOOM_AUDIT_SIGNING_KEY` and protect its history.
- Terminate TLS at a trusted reverse proxy or ingress.
- Give users the lowest sufficient role and rotate credentials regularly.
- Place WireMock's Admin API on a private network reachable only by SimuLoom.
- Treat `/runtime` as service traffic: restrict it at the ingress if simulations must not be
  publicly invokable. API-key middleware protects control-plane `/api/v1` and `/mcp` routes,
  not the virtualized service façade.
- Back up audit events to append-only or write-once storage for independent retention.
- Restrict filesystem access to the native SQLite database because it contains virtualized
  request metadata, mappings, and current business-scenario state. Back it up consistently
  with the simulation workspace when restart recovery is required.
- The operator console stores an entered API key only in browser `sessionStorage`; closing the
  tab clears it. Serve the console only over TLS outside local development, do not use it on
  shared browser profiles, and retain the bundled strict Content Security Policy.
- The visual designer creates SVG elements through the DOM and inserts scenario labels only as
  text. Keep this text-only rendering boundary and server-side scenario validation when
  extending graph or import behavior.

## Current security boundary

SimuLoom v0.15 uses statically configured API keys. It does not yet provide OIDC, automatic
key rotation, distributed rate limiting, or an external policy engine. The local SHA-256
audit chain detects accidental modification; HMAC signing is strongly recommended when an
operator could otherwise rewrite both events and hashes.

Scenario definitions are limited in size and complexity, restricted to approved OpenAPI
operations and response codes, and cannot target WireMock admin paths. SimuLoom rejects
unsafe response framing headers and validates declared JSON responses when a response schema
is available.

Individual scenario resets require operator access. Resetting every scenario in the shared
WireMock runtime requires admin access and should be treated as a cross-simulation operation.
