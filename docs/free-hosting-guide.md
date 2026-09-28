# Hosting SimuLoom for free

This walks through putting SimuLoom on the public internet at **$0/month**, with real HTTPS and
authentication turned on. It uses three free services together:

- **Google Cloud Free Tier** — an "Always Free" `e2-micro` VM (not a time-limited trial). This
  is where SimuLoom actually runs.
- **DuckDNS** — a free subdomain (`yourname.duckdns.org`) pointing at the VM, since Let's
  Encrypt (and therefore automatic HTTPS) needs a real domain name, not a bare IP address.
- **Caddy** — a reverse proxy that automatically requests and renews the HTTPS certificate for
  that domain. Already wired up in [`deploy/docker-compose.prod.yml`](../deploy/docker-compose.prod.yml).

Everything below is one-time setup. Steps 1–2 need to happen in Google's and DuckDNS's own
consoles — there's no way to script account creation or identity verification for you.

## 1. Create the VM

1. Sign up at [cloud.google.com/free](https://cloud.google.com/free) (a card is required for
   identity verification, but Always Free resources are never billed unless you explicitly
   upgrade to a paid account).
2. Create a project, then enable the **Compute Engine API** for it (the console prompts you the
   first time you open Compute Engine).
3. Create a VM instance with machine type **`e2-micro`**, in one of the three regions the
   Always Free tier covers — **`us-west1`, `us-central1`, or `us-east1`** (any other region
   bills immediately). Pick an Ubuntu boot image with a standard persistent disk of 30GB or
   less (also free).
4. On the same creation screen, tick **"Allow HTTP traffic"** and **"Allow HTTPS traffic"** —
   this creates the needed firewall rules for you. Unlike some clouds, stock Ubuntu images on
   GCP don't ship with an additional OS-level firewall blocking those ports, so there's no
   second place to open them.
5. Under **VPC network → IP addresses**, promote the instance's ephemeral external IP to a
   **static** one (still free as long as it stays attached to a running instance) — this way
   DuckDNS never needs updating later.

## 2. Point a free domain at it

1. Sign up at [duckdns.org](https://www.duckdns.org) (sign-in via GitHub/Google works).
2. Create a subdomain, e.g. `yourname` → `yourname.duckdns.org`, and set it to the VM's
   persistent public IP from step 1.
3. Confirm it resolves before continuing: `dig +short yourname.duckdns.org` should print that
   IP. Caddy will fail to get a certificate if this isn't correct yet.

## 3. Install Docker and clone the repo

SSH into the VM — the **"SSH" button next to the instance in the GCP console** opens a
browser-based terminal with keys handled for you, no local SSH key setup needed — then:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out/in once for this to take effect
git clone https://github.com/anzar-ahsan-commits/simuloom-mcp.git
cd simuloom-mcp/deploy
```

## 4. Configure secrets

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # run twice
```

Edit `deploy/.env`:

- `SIMULOOM_DOMAIN` → the DuckDNS name from step 2.
- `SIMULOOM_API_KEYS` → replace the placeholder key with one of the generated values (keep the
  `{"subject": "...", "role": "admin"}` shape — see [docs/api.md](api.md) for the role model).
- `SIMULOOM_AUDIT_SIGNING_KEY` → the other generated value.

`deploy/.env` is gitignored — it never gets committed.

## 5. Start it

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

This runs SimuLoom on the native runtime (no WireMock sidecar needed) with a persistent
`simuloom-workspace` volume, behind Caddy on 80/443. First boot takes a few extra seconds while
Caddy requests the certificate.

## 6. Verify

```bash
curl --fail https://yourname.duckdns.org/api/v1/health
curl --fail https://yourname.duckdns.org/api/v1/readiness -H "X-API-Key: <your generated key>"
```

The console is at `https://yourname.duckdns.org/ui`, REST/Swagger at `/docs`, and MCP Streamable
HTTP at `/mcp` — all now behind your API key.

## Keeping it updated

```bash
cd simuloom-mcp && git pull
cd deploy && docker compose -f docker-compose.prod.yml up -d --build
```

## Notes

- This setup deliberately skips the WireMock adapter (`SIMULOOM_RUNTIME=native`) to keep the VM
  to a single lightweight application container plus Caddy — no separate JVM process to run.
- The local AI Copilot (`SIMULOOM_AI_ENABLED`) is left off here since it expects an Ollama
  instance reachable from the container; enabling it on a small free VM would need Ollama
  installed alongside, which is heavier than the Always Free shape comfortably runs.
- Treat the generated `SIMULOOM_API_KEYS` value like a password — anyone with it has whatever
  role you assigned it (`admin` can do everything, including changing AI settings and reading
  secrets metadata).
- The Always Free tier includes 1 GB/month of network egress from North America to most
  destinations. A personal instance of SimuLoom is nowhere near that for normal use, but it's
  worth knowing the cap exists if you start driving heavy traffic through it.
