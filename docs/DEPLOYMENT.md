# Deployment

**Scope:** Hosting plan, deployment checklist, configuration, backup strategy. For application code, see [BACKEND.md](./BACKEND.md) and [FRONTEND.md](./FRONTEND.md).

## Hosting Plan

| Component | Service | Tier | Notes |
|---|---|---|---|
| Database | Supabase managed PostgreSQL | Free | 500 MB; automatic backups + PITR |
| App server | Oracle Cloud Free Tier — 1 AMD VM | Always-free | 1 OCPU, 1 GB RAM. Runs FastAPI + Nginx |
| Object storage | AWS S3 | Paid (small) | ~$0.023/GB/month after 5 GB / 12-month free tier expires |
| Domain | Your registrar | — | A record → Oracle VM public IP |
| TLS | Let's Encrypt via Certbot | Free | Auto-renewal via cron |
| AI | Anthropic Claude API | Paid | ~$48/year at projected volume |

**DB size estimate:** metadata only, no images. Expected <50 MB even after years of use. Comfortably inside the 500 MB free tier.

**Object-storage cost:** AWS S3 free tier covers 5 GB for the first 12 months only. After that, expect ~$0.023/GB/month for storage plus modest request and egress costs. At ~2 GB/year growth, year-2 storage cost is roughly $0.05/month, scaling to ~$0.50/month by year 5 — still trivial. Egress is $0.09/GB beyond the free allowance, but at this user volume that stays in single-digit dollars per year.

**Region:** pick an AWS region close to Singapore (e.g. `ap-southeast-1`) to keep latency low for users and for the Oracle VM ↔ S3 round-trips during paper generation.

### Why DB is NOT on the VM

A VM disk crash on Oracle Cloud's free tier would lose all data. Supabase provides:
- managed automatic backups,
- point-in-time recovery,
- high availability,

…all at zero cost in the free tier. Images in Oracle Object Storage are already durable by design. Putting the DB on the VM trades reliability for nothing.

## Alternatives Considered

| Option | Why rejected |
|---|---|
| **AWS EC2 for the VM** | Only 12 months free, then paid. Oracle's always-free VMs are better long-term. (S3 is still used for object storage despite the same free-tier limit, because the post-free-tier cost is negligible at this scale and the SDK/tooling ecosystem is the most mature option.) |
| **Oracle Cloud Object Storage** | Always-free 10 GB, but S3's tooling, MinIO local-dev compatibility, and presigned-URL ergonomics won out over the free-tier savings. |
| **DB on the Oracle VM** | VM disk failure = data loss. Supabase is free and managed. |
| **Oracle Autonomous Database** | Free and managed, but Oracle SQL/drivers add complexity vs. plain Postgres. |

## Deployment Checklist

1. **Supabase** — create a new project (free tier). Note the PostgreSQL connection string.
2. **Oracle Cloud** — provision:
   - 1 AMD VM (1 OCPU, 1 GB RAM, always-free shape).
3. **AWS** — provision:
   - 1 S3 bucket in a Singapore-friendly region (e.g. `ap-southeast-1`).
   - Block all public access at the bucket level (the app uses presigned URLs).
   - Create an IAM user scoped to `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on this bucket only. Note the access key + secret.
4. **VM setup** — install:
   - Python 3.11+
   - Poppler (for PDF→image conversion)
   - Nginx
   - Certbot (Let's Encrypt)
5. **Backend** — deploy FastAPI app via systemd service (or Docker). Listen on `127.0.0.1:8000`.
6. **Frontend** — `npm run build`; copy `dist/` to a static directory served by Nginx.
7. **Nginx** — configure reverse proxy:
   - `/api/*` → `http://127.0.0.1:8000`
   - `/*` → static frontend
8. **TLS** — run Certbot to issue Let's Encrypt cert and configure Nginx HTTPS. Confirm auto-renewal cron is in place.
9. **DNS** — point your domain's A record to the VM's public IP.
10. **Environment variables** — set on the VM (in the systemd unit or `.env` loaded by it):
    - `DATABASE_URL` — Supabase Postgres connection string
    - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET` — AWS S3 credentials and target bucket
    - `ANTHROPIC_API_KEY` — Anthropic Claude API key
    - `JWT_SECRET` — long random string for signing tokens
    - `CORS_ORIGIN` — your production domain
11. **Database** — run migrations to create tables. Seed initial reference data (subjects, streams, levels, exam types, and an initial set of topics/subtopics).

## Configuration Reference

| Env var | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | Backend | Postgres connection (Supabase) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET` | Backend | AWS S3 (boto3) config |
| `S3_ENDPOINT_URL` (optional) | Backend | Override for local dev against MinIO; leave unset in production |
| `ANTHROPIC_API_KEY` | Backend | Claude API auth |
| `JWT_SECRET` | Backend | Signs auth tokens |
| `CORS_ORIGIN` | Backend | CORS allow-list (production domain only) |

## Backup Strategy

- **PostgreSQL (Supabase):** managed automatic backups + point-in-time recovery are included in the free tier. **No manual backup needed.**
- **Images (AWS S3):** 11-nines durability by design. **Enable bucket versioning** for protection against accidental overwrites/deletes. Consider a lifecycle rule to expire non-current versions after 30 days so versioning doesn't quietly inflate storage costs.
- **Optional extra safety:** weekly `pg_dump` cron on the VM, uploading the dump to the same S3 bucket (or a separate `*-backups` bucket). Cheap insurance against catastrophic Supabase loss.
