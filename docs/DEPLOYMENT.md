# Deployment

**Scope:** Hosting plan, CI/CD pipeline, one-time VM provisioning, configuration, backup strategy. For application code, see [BACKEND.md](./BACKEND.md) and [FRONTEND.md](./FRONTEND.md).

## Hosting Plan

| Component | Service | Tier | Notes |
|---|---|---|---|
| Database | Supabase managed PostgreSQL | Free | 500 MB. **No managed backups/PITR on the free tier** — see [Backup Strategy](#backup-strategy) |
| App server | Oracle Cloud Free Tier — 1 Ampere ARM VM (`VM.Standard.A1.Flex`) | Always-free | 1 OCPU, 6 GB RAM, **arm64/aarch64**. Runs the Dockerized FastAPI backend + host Nginx |
| Object storage | AWS S3 | Paid (small) | ~$0.023/GB/month after 5 GB / 12-month free tier expires |
| Container registry | GitHub Container Registry (GHCR) | Free | Stores the `pillora-api` image (`linux/arm64`) built by CI |
| Edge / CDN / TLS | Cloudflare (proxied DNS) | Free | Browser TLS, DDoS protection, caching, hides the origin IP |
| Domain | `questionbank.pillora.com.sg` (zone DNS on Cloudflare) | — | Proxied A record → Oracle VM. `www.pillora.com.sg` stays DNS-only → Wix (untouched) |
| Origin TLS | Cloudflare Origin Certificate | Free | 15-year cert on Nginx; zone SSL/TLS mode Full (strict). No Certbot/ACME renewal |
| AI | Anthropic Claude API | Paid | ~$48/year at projected volume |

**DB size estimate:** metadata only, no images. Expected <50 MB even after years of use. Comfortably inside the 500 MB free tier.

**Object-storage cost:** AWS S3 free tier covers 5 GB for the first 12 months only. After that, expect ~$0.023/GB/month for storage plus modest request and egress costs. At ~2 GB/year growth, year-2 storage cost is roughly $0.05/month, scaling to ~$0.50/month by year 5 — still trivial.

**Region:** pick an AWS region close to Singapore (e.g. `ap-southeast-1`) to keep latency low for users and for the Oracle VM ↔ S3 round-trips during paper generation.

### Why DB is NOT on the VM

A VM disk crash on Oracle Cloud's free tier would lose all data. Supabase provides a managed, off-VM Postgres with high availability at zero cost. Durability of point-in-time data is handled by our own backup pipeline (below), since the free tier does not include managed backups. Putting the DB on the VM trades reliability for nothing.

## Architecture

```
Browser
   │  HTTPS
   ▼
Cloudflare edge (browser TLS, CDN, DDoS, hides origin IP)
   │  HTTPS — Full (strict), Cloudflare Origin Certificate; firewall allows only Cloudflare IPs
   ▼
Oracle Cloud VM
   ├─ Nginx (host)      — origin TLS, serves /var/www/pillora SPA, proxies /api → 127.0.0.1:8000
   └─ Docker
        └─ pillora-api  — FastAPI/uvicorn on 127.0.0.1:8000
              ├──► Supabase Postgres   — metadata
              ├──► AWS S3              — images (+ DB backups)
              └──► Anthropic Claude    — AI labeling

CI/CD:  GitHub push to main → Actions (test → build image → push GHCR → SSH deploy)
```

The frontend is built in CI and served as static files by Nginx; it calls the API at same-origin `/api/*` (Cloudflare is transparent — same hostname), so **no CORS configuration is needed**.

## Alternatives Considered

| Option | Why rejected |
|---|---|
| **AWS EC2 for the VM** | Only 12 months free, then paid. Oracle's always-free VMs are better long-term. |
| **Oracle Cloud Object Storage** | Always-free 10 GB, but S3's tooling, MinIO local-dev compatibility, and presigned-URL ergonomics won out. |
| **DB on the Oracle VM** | VM disk failure = data loss. Supabase is free and managed. |
| **Supabase Pro ($25/mo) for PITR** | Better RPO, but not needed at this scale; weekly `pg_dump` → S3 meets the durability requirement for free. |
| **Bare systemd backend** | Docker gives reproducible builds and clean image-tag rollbacks; chosen over venv-on-VM. |
| **Let's Encrypt/Certbot at the origin** | Works, but Cloudflare adds free edge TLS, DDoS protection, and origin-IP hiding, and its 15-year Origin Certificate removes ACME renewal entirely. |

## CI/CD Pipeline

Two GitHub Actions workflows:

- **`.github/workflows/ci.yml`** — runs on PRs and non-`main` branches: backend unit tests (`pytest tests/ --ignore=tests/integration`, fully offline via SQLite + moto) and the frontend lint/build.
- **`.github/workflows/deploy.yml`** — runs on **push to `main`**:
  1. **test** — same checks, as a deploy gate.
  2. **build-and-push** — cross-builds the `Dockerfile` for **`linux/arm64`** (via QEMU, to match the Ampere VM) and pushes `ghcr.io/billyhoce/pillora-api:<sha>` + `:latest`; builds the frontend and uploads `dist/` as an artifact.
  3. **deploy** — SCPs `dist/` to the VM and SSHes in to: sync the repo, `docker compose pull`, **take a pre-migration DB dump (aborts on failure)**, `alembic upgrade head`, `docker compose up -d`, and curl `/api/health` to confirm.

**Required GitHub secrets:** `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (private key whose public half is in the VM user's `~/.ssh/authorized_keys`). GHCR push/pull uses the built-in `GITHUB_TOKEN` — no extra secret needed. **Production app secrets are never placed in GitHub** — they live only in `/opt/pillora/.env` on the VM, and migrations run there.

**Rollback:** re-deploy a previous image by SSHing to the VM and running, from `/opt/pillora/repo/deploy`:
```bash
IMAGE_TAG=<previous-git-sha> docker compose -f docker-compose.prod.yml up -d
```

## One-Time VM Provisioning

1. **Provision the VM** — Oracle Cloud, 1 Ampere ARM VM (`VM.Standard.A1.Flex`, up to 4 OCPU / 24 GB RAM, always-free), **Ubuntu 24.04 LTS (aarch64)**. The CI image is built for `linux/arm64` to match this shape. Open port **443** in the security list, ideally restricted to [Cloudflare's IP ranges](https://www.cloudflare.com/ips/) so the origin is reachable only through Cloudflare. Leave port 80 closed.
2. **Install host packages:**
   ```bash
   sudo apt update
   sudo apt install -y docker.io docker-compose-v2 nginx \
                       postgresql-client git curl unzip
   sudo usermod -aG docker "$USER"   # log out/in for group to take effect
   ```
   *(No Poppler — PDF→image uses PyMuPDF, which bundles its own libraries.)*

   **AWS CLI v2** (not via `apt` — Ubuntu dropped the `awscli` package due to an upstream botocore dependency conflict; v2 is also the only AWS-supported version):
   ```bash
   curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o awscliv2.zip
   unzip awscliv2.zip
   sudo ./aws/install
   rm -rf aws awscliv2.zip
   ```
   *(Use `awscli-exe-linux-x86_64.zip` instead if provisioning on an x86_64 VM.)*
3. **Clone the repo** (used by the deploy job to sync the compose file + backup script):
   ```bash
   sudo mkdir -p /opt/pillora && sudo chown "$USER":"$USER" /opt/pillora
   git clone https://github.com/billyhoce/PilloraQuestionBank.git /opt/pillora/repo
   ```
4. **Create the production env file:**
   ```bash
   cp /opt/pillora/repo/deploy/pillora.env.example /opt/pillora/.env
   # edit /opt/pillora/.env with real prod values
   chmod 600 /opt/pillora/.env
   cp /opt/pillora/repo/deploy/scripts/backup_db.sh /opt/pillora/backup_db.sh
   chmod +x /opt/pillora/backup_db.sh
   ```
5. **Static frontend dir** (owned by the deploy user so the workflow needs no sudo):
   ```bash
   sudo mkdir -p /var/www/pillora && sudo chown -R "$USER":"$USER" /var/www/pillora
   ```
6. **AWS S3** — create two buckets in `ap-southeast-1`:
   - `pillora-prod` (images) and `pillora-prod-backups` (DB dumps).
   - **Block all public access** on both (app uses presigned URLs).
   - **Enable bucket versioning** on both. On each, add a lifecycle rule to expire **noncurrent** versions after 30 days.
   - Create one IAM user with `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on `pillora-prod`, plus `s3:PutObject` on `pillora-prod-backups`. Put its keys in `/opt/pillora/.env`.
7. **Cloudflare + Nginx (origin TLS):** the app runs on its own subdomain, `questionbank.pillora.com.sg`, so the existing `www.pillora.com.sg` Wix site is untouched.
   - **Move the `pillora.com.sg` zone to Cloudflare:** add it in Cloudflare, let it import existing records, then set the given nameservers at your registrar. **Replicate every current Wix record and keep `www`/root DNS-only (grey cloud)** so Wix behaves exactly as before.
   - Add a **proxied** (orange-cloud) A record: `questionbank` → the VM's public IP.
   - Set the zone's **SSL/TLS mode to Full (strict)** and enable **Always Use HTTPS** (this is per-hostname-safe: grey-clouded `www`/Wix bypasses Cloudflare entirely).
   - Create a **Cloudflare Origin Certificate** (SSL/TLS → Origin Server → Create Certificate) covering `questionbank.pillora.com.sg` (or `*.pillora.com.sg`) and install it on the VM:
     ```bash
     sudo mkdir -p /etc/ssl/cloudflare
     sudo tee /etc/ssl/cloudflare/pillora-origin.pem   # paste the certificate, then Ctrl-D
     sudo tee /etc/ssl/cloudflare/pillora-origin.key   # paste the private key, then Ctrl-D
     sudo chmod 600 /etc/ssl/cloudflare/pillora-origin.key
     ```
   - Install the site config (its `server_name` is already `questionbank.pillora.com.sg`):
     ```bash
     sudo cp /opt/pillora/repo/deploy/nginx/pillora.conf /etc/nginx/sites-available/pillora.conf
     sudo ln -s /etc/nginx/sites-available/pillora.conf /etc/nginx/sites-enabled/
     sudo rm -f /etc/nginx/sites-enabled/default
     sudo nginx -t && sudo systemctl reload nginx
     ```
   - (Recommended) Enable **Authenticated Origin Pulls** and keep the VM firewall restricted to Cloudflare IPs so the origin cannot be reached directly.
8. **Verify DNS** — `dig +short questionbank.pillora.com.sg` should return Cloudflare IPs (proxied), and `www.pillora.com.sg` should still resolve to and serve Wix as before.
9. **Weekly backup timer:**
   ```bash
   sudo cp /opt/pillora/repo/deploy/systemd/pillora-backup.* /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now pillora-backup.timer
   ```
10. **First deploy** — push to `main` (or re-run the deploy workflow). It pulls the image, runs migrations against the prod DB, and brings up the container. The seed-reference-data migration runs automatically as part of `alembic upgrade head`.

After this, every push to `main` deploys automatically.

## Configuration Reference

Production values live in `/opt/pillora/.env` (template: `deploy/pillora.env.example`).

| Env var | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | Backend, backups | Postgres connection (Supabase prod, session pooler :5432, `+psycopg` driver) |
| `JWT_SECRET_KEY` | Backend | Signs auth tokens. Must be a long random string (`openssl rand -hex 32`) |
| `S3_BUCKET` | Backend | Image bucket (`pillora-prod`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | Backend, backups | AWS S3 (boto3 / awscli) credentials and region |
| `S3_ENDPOINT_URL` (optional) | Backend | MinIO override for local dev only; **leave unset in production** |
| `BACKUP_S3_BUCKET` | Backups | Versioned bucket for DB dumps (`pillora-prod-backups`) |
| `ANTHROPIC_API_KEY` | Backend | Claude API auth |

## Backup Strategy

**The Supabase free tier has no managed backups and no point-in-time recovery.** Durability is provided by our own pipeline:

- **PostgreSQL → S3 (`pg_dump`):** `deploy/scripts/backup_db.sh` streams `pg_dump | gzip` to `s3://<BACKUP_S3_BUCKET>/db/`.
  - **Weekly** via the `pillora-backup.timer` systemd timer.
  - **Before every migration:** the deploy workflow runs the same script *before* `alembic upgrade head`, so an automated deploy always creates a fresh recovery point and aborts if the dump fails.
  - The backups bucket has **versioning** on, so even an overwritten/deleted dump is recoverable.
  - **Restore:** `aws s3 cp s3://<bucket>/db/<file>.sql.gz - | gunzip | psql "<plain-postgresql-url>"` (strip the `+psycopg` driver suffix from `DATABASE_URL`).
- **Images (AWS S3):** 11-nines durability by design. **Versioning** is enabled on the image bucket with a lifecycle rule expiring noncurrent versions after 30 days, protecting against accidental overwrites/deletes without inflating storage cost.

**Recovery point objective (RPO):** up to 7 days for the database between weekly dumps (plus a guaranteed dump on every deploy). Acceptable for this workload; tighten by changing the timer's `OnCalendar` to `daily` if desired.
