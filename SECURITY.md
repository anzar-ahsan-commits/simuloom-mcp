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
- Back up audit events to append-only or write-once storage for independent retention.

## Current security boundary

SimuLoom v0.7 uses statically configured API keys. It does not yet provide OIDC, automatic
key rotation, distributed rate limiting, or an external policy engine. The local SHA-256
audit chain detects accidental modification; HMAC signing is strongly recommended when an
operator could otherwise rewrite both events and hashes.
