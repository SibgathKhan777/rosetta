# Deploying to production (zero-cost, AWS)

Backend (Postgres, Redis, MinIO, API, worker) runs on a free-tier AWS EC2
instance via `docker-compose.prod.yml`, behind Caddy for automatic HTTPS.
Frontend runs on Vercel. This is the actual path used for the live
deployment — an Oracle Cloud Always Free plan was tried first but blocked at
signup (Oracle's identity verification wanted a credit card; a debit card
was rejected). AWS's signup accepts debit cards.

See README's "Known operational risks" section for what this setup does
*not* solve on its own (YouTube specifically blocking cloud IPs — worked
around below — and LLM daily quota limits).

## 1. Get AWS credentials

```bash
aws --version   # needs 2.32.0+; brew install awscli if missing/older
aws login       # opens a browser sign-in; use --remote if no local browser
aws configure set region ap-south-1   # or your preferred region
aws sts get-caller-identity   # confirms it worked
```

## 2. Provision the EC2 instance

Find a free-tier-eligible instance type and the latest Ubuntu ARM64 AMI for
your region:

```bash
aws ec2 describe-instance-types --filters "Name=free-tier-eligible,Values=true" \
  --query "InstanceTypes[].InstanceType" --output text --region ap-south-1
# t4g.small (2 vCPU / 2GB RAM, ARM Graviton) is the best fit here — more RAM
# than the classic t3.micro, which matters since the worker loads
# faster-whisper + RapidOCR + EAST models simultaneously.

aws ssm get-parameter --region ap-south-1 \
  --name /aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id \
  --query "Parameter.Value" --output text
```

Create a security group — SSH restricted to your own IP, HTTP/HTTPS open to
the world:

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" \
  --region ap-south-1 --query "Vpcs[0].VpcId" --output text)
SG_ID=$(aws ec2 create-security-group --group-name video-platform-sg \
  --description "video-extraction-platform" --vpc-id $VPC_ID --region ap-south-1 \
  --query "GroupId" --output text)

MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp \
  --port 22 --cidr "${MY_IP}/32" --region ap-south-1
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp \
  --port 80 --cidr 0.0.0.0/0 --region ap-south-1
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp \
  --port 443 --cidr 0.0.0.0/0 --region ap-south-1
```

Create a key pair and launch the instance:

```bash
aws ec2 create-key-pair --key-name video-platform-key --region ap-south-1 \
  --query "KeyMaterial" --output text > ~/.ssh/video-platform-key.pem
chmod 400 ~/.ssh/video-platform-key.pem

aws ec2 run-instances \
  --image-id <ami-id from above> \
  --instance-type t4g.small \
  --key-name video-platform-key \
  --security-group-ids $SG_ID \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":24,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=video-platform}]' \
  --region ap-south-1 --query "Instances[0].InstanceId" --output text

aws ec2 wait instance-status-ok --instance-ids <instance-id> --region ap-south-1
aws ec2 describe-instances --instance-ids <instance-id> --region ap-south-1 \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text
```

## 3. Install Docker on the instance

```bash
ssh -i ~/.ssh/video-platform-key.pem ubuntu@<instance-ip>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
```

## 4. Get the code onto the instance

No GitHub remote was set up for this project, so the code was `rsync`'d
directly rather than `git clone`'d — either works:

```bash
rsync -avz --exclude 'node_modules' --exclude '.next' --exclude '__pycache__' \
  --exclude '.git' --exclude '*.pyc' --exclude '.env' \
  -e "ssh -i ~/.ssh/video-platform-key.pem" \
  ./ ubuntu@<instance-ip>:/home/ubuntu/video-extraction-platform/
```

**Explicitly exclude `.env`** — see the `--env-file` warning in step 6 for
why a stray copy of the local dev `.env` breaks things silently.

## 5. Configure secrets

```bash
ssh -i ~/.ssh/video-platform-key.pem ubuntu@<instance-ip>
cd video-extraction-platform
cp .env.production.example .env.production
```

Edit `.env.production` and replace every `REPLACE_ME` — generate secrets
directly on the server, don't reuse anything pasted into a chat/doc:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # JWT_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # MINIO_ROOT_PASSWORD (same value for S3_SECRET_KEY)
```

`MINIO_ROOT_USER`/`S3_ACCESS_KEY` just need to match each other (any string,
not a secret). Set `VISION_LLM_API_KEY` to your Groq key. Leave
`CORS_ALLOWED_ORIGINS` as a placeholder for now — fixed in step 8.

## 6. Bring the stack up

**Always pass `--env-file .env.production` explicitly.** Docker Compose only
auto-loads a file literally named `.env` in the working directory for its
own `${VAR}` interpolation (used by the `postgres`/`minio` services and the
`DATABASE_URL` line) — that's separate from `env_file:`, which only injects
variables into a container's own runtime environment. Confirmed directly:
an rsync that didn't exclude the local dev `.env` left a stray copy on the
server, and Postgres/MinIO silently initialized with *that* file's
dev-default credentials via `${VAR}` interpolation, while `api`/`worker`
still connected using the real `.env.production` secrets via `env_file` —
breaking MinIO auth with no immediately obvious cause.

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build \
  postgres redis minio api worker
```

First boot downloads the whisper/EAST models (a few hundred MB) — watch
`docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker`
until it settles, then confirm the API directly (before Caddy/TLS exist yet):

```bash
# Temporarily map a port to test directly — add to a docker-compose.override.yml:
#   services: {api: {ports: ["8000:8000"]}}
# then open port 8000 to your IP only, same pattern as the SSH rule above.
curl http://<instance-ip>:8000/health
```

## 7. HTTPS via a free "magic domain" (no domain purchase needed)

**[nip.io](https://nip.io)** resolves `<ip>.nip.io` to `<ip>` automatically —
a real, publicly resolvable DNS name with no signup, which means Caddy can
get it a real Let's Encrypt certificate immediately. This is what the live
deployment actually uses; swap in a real domain later if you get one by
editing `Caddyfile` the same way.

```bash
# Caddyfile:
cat > Caddyfile <<EOF
<instance-ip>.nip.io {
	reverse_proxy api:8000
}
EOF

docker compose --env-file .env.production -f docker-compose.prod.yml up -d caddy
curl https://<instance-ip>.nip.io/health
# {"status": "ok"}
```

Once this is confirmed working, remove the temporary direct port-8000
mapping/security-group rule from step 6 — all traffic should go through
Caddy on 443 from here on.

## 8. Deploy the frontend to Vercel

```bash
vercel login              # device-flow: opens a URL, approve it in your browser
cd frontend
vercel link --yes --scope <your-vercel-team-slug>
printf 'https://<instance-ip>.nip.io' | vercel env add NEXT_PUBLIC_API_URL production --scope <your-team-slug>
vercel deploy --prod --scope <your-team-slug>
```

Note the resulting `https://<project>.vercel.app` URL.

**Important — mixed content**: the frontend is HTTPS; browsers silently
block it from calling a plain-HTTP API (this bit the first attempt here,
before Caddy/TLS was set up — curl doesn't enforce this, so a curl test can
pass while the real browser fails). Confirm the backend is HTTPS (step 7)
*before* testing the real signup/login flow through the actual UI, not just
via curl.

## 9. Lock down CORS

Back on the instance:

```bash
sed -i 's#CORS_ALLOWED_ORIGINS=.*#CORS_ALLOWED_ORIGINS=["https://<project>.vercel.app"]#' .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up -d api
```

## 10. Verify for real, through the actual browser UI

Don't stop at `curl /health` — sign up through the real deployed frontend
and submit a real video. This is how the mixed-content issue above was
actually caught; a curl-only check would have missed it entirely.

## 11. Password reset email (Resend)

Forgot/reset password (`POST /auth/forgot-password` + `POST /auth/reset-password`)
sends the reset link by email via [Resend](https://resend.com) — free, no card,
signup only needs an email address.

1. Sign up at resend.com, then create an API key under **API Keys** in the dashboard.
2. Set these in `.env.production` (the example file already has placeholders):

```bash
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=Rosetta <onboarding@resend.dev>
FRONTEND_URL=https://<project>.vercel.app   # must be the real Vercel URL, not localhost
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30
```

3. Restart the API so it picks up the new env vars:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build api worker
```

**Known limitation**: without verifying your own domain with Resend, the
shared sandbox sender (`onboarding@resend.dev`) can only deliver to the email
address that owns the Resend account — fine for testing with your own
account, but other users' reset emails won't actually arrive until a domain
is verified. `RESEND_API_KEY` left blank doesn't break signup/login; it just
means reset emails silently fail to send (logged server-side, never surfaced
to the caller — see the next paragraph for why).

If `RESEND_API_KEY` is missing or Resend has an outage, `/auth/forgot-password`
still returns its generic "if that email is registered..." success message
rather than a 500 — the alternative (a different response when the email
send fails) would leak whether an email address has an account, defeating
the whole point of the generic message. The failure is logged
server-side (`docker compose ... logs api`) so it's still debuggable.

## Known limitation: YouTube blocks AWS's IP range specifically

Unlike Instagram (confirmed working directly from this deployment), YouTube
returns `Sign in to confirm you're not a bot` for **every** request from
this server's IP — tried multiple videos and multiple internal yt-dlp
"player clients," all identical failure. This is a hard block on
AWS/GCP/Azure datacenter IP ranges generally, not specific to any one video
or account.

**Workaround built for this**: `POST /jobs/ingest` accepts a video already
downloaded elsewhere (e.g. your own machine, which isn't IP-blocked) plus
its metadata, uploads it to S3, and enqueues the pipeline from `split_job`
onward — skipping yt-dlp/`download_job` on the server entirely.

```bash
pip install yt-dlp requests
python3 scripts/ingest_video.py "<youtube-url>" "https://<instance-ip>.nip.io" "<your-jwt-token>"
```

Get a JWT by logging into the deployed frontend and reading
`localStorage.getItem('token')` from devtools, or via
`POST /auth/login`. Verified working end-to-end in production against a
real ~12-minute YouTube video that was otherwise fully blocked.

## What this setup does NOT solve

- **Backups**: Postgres/MinIO data lives on the instance's disk only. For a
  hobby launch this is an accepted risk; add a cron `pg_dump` to off-instance
  storage if that changes.
- **Groq's free daily token quota** (200K tokens/day) — shared across every
  user's vision-LLM escalation + explanation calls, and was hit repeatedly
  just from this project's own testing. Fine for light real usage; needs a
  paid tier or the OpenRouter-fallback pattern used during dev (see
  `app/services/explanation.py`'s design) if usage grows.
- **Platform blocking at scale generally** — the YouTube-on-AWS-IP case above
  has a workaround; Instagram/TikTok/etc. blocking at higher volume than
  tested here is still an open risk (see README).
- **Horizontal scaling** — one worker process. Fine for tens of users doing
  occasional jobs; scale via
  `docker compose --env-file .env.production -f docker-compose.prod.yml up -d --scale worker=N`
  if concurrent job volume grows.
