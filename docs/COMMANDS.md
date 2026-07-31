# Command Reference — every command actually used to set up and deploy this

A raw, copy-paste-ready log of the real commands run to get this project from local
docker-compose to live on AWS + Vercel. Narrative context and *why* each step exists is in
[DEPLOYMENT.md](../DEPLOYMENT.md) — this file is just the commands, grouped by what they do.
Placeholders (`<like-this>`) stand in for values that are specific to one run (instance IDs,
IPs, tokens) — never paste real secrets into this file when you fill them in.

---

## 1. AWS CLI — install and authenticate

```bash
# Check / install the CLI (needs 2.32.0+ for `aws login`)
aws --version
brew install awscli          # macOS, if missing or too old

# Short-lived, auto-rotating credentials (not a static access key)
aws login                    # opens a browser sign-in
aws login --remote           # fallback: prints a URL + code for a headless machine

aws configure set region ap-south-1
aws sts get-caller-identity  # confirms it worked — prints Account/Arn
```

## 2. AWS AI Agent Toolkit — install the plugin

```bash
claude plugin install aws-core@claude-plugins-official
claude plugin list           # confirm it shows "enabled"
```

## 3. Find a free-tier instance type and the latest Ubuntu ARM64 AMI

```bash
aws ec2 describe-instance-types \
  --filters "Name=free-tier-eligible,Values=true" \
  --query "InstanceTypes[].InstanceType" --output text --region ap-south-1

aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id \
  --region ap-south-1 --query "Parameter.Value" --output text
```

## 4. Networking — security group with least-privilege rules

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=is-default,Values=true" \
  --region ap-south-1 --query "Vpcs[0].VpcId" --output text)

SG_ID=$(aws ec2 create-security-group --group-name video-platform-sg \
  --description "video-extraction-platform" --vpc-id "$VPC_ID" --region ap-south-1 \
  --query "GroupId" --output text)

MY_IP=$(curl -s https://checkip.amazonaws.com)

# SSH — only from this machine's current IP
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr "${MY_IP}/32" --region ap-south-1

# HTTP/HTTPS — open to the world (needed for Let's Encrypt + real traffic)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0 --region ap-south-1
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 443 --cidr 0.0.0.0/0 --region ap-south-1
```

**Temporary rule used only for testing before Caddy/TLS existed** (revoked again once HTTPS
was confirmed working — see step 8):

```bash
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 8000 --cidr "${MY_IP}/32" --region ap-south-1

# ...later, once Caddy on 443 was confirmed working:
aws ec2 revoke-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 8000 --cidr "${MY_IP}/32" --region ap-south-1
```

## 5. Key pair and instance launch

```bash
aws ec2 create-key-pair --key-name video-platform-key --region ap-south-1 \
  --query "KeyMaterial" --output text > ~/.ssh/video-platform-key.pem
chmod 400 ~/.ssh/video-platform-key.pem

aws ec2 run-instances \
  --image-id <ami-id-from-step-3> \
  --instance-type t4g.small \
  --key-name video-platform-key \
  --security-group-ids "$SG_ID" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":24,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=video-platform}]' \
  --region ap-south-1 --query "Instances[0].InstanceId" --output text

aws ec2 wait instance-running --instance-ids <instance-id> --region ap-south-1
aws ec2 wait instance-status-ok --instance-ids <instance-id> --region ap-south-1

aws ec2 describe-instances --instance-ids <instance-id> --region ap-south-1 \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text
```

## 6. Server setup — Docker

```bash
ssh -i ~/.ssh/video-platform-key.pem ubuntu@<instance-ip>

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
```

## 7. Get the code onto the server

```bash
# No git remote was set up for this project, so rsync rather than git clone.
# --exclude '.env' is not optional — see DEPLOYMENT.md's --env-file warning.
rsync -avz \
  --exclude 'node_modules' --exclude '.next' --exclude '__pycache__' \
  --exclude '.git' --exclude '*.pyc' --exclude '.env' \
  -e "ssh -i ~/.ssh/video-platform-key.pem" \
  ./ ubuntu@<instance-ip>:/home/ubuntu/video-extraction-platform/

# Re-run any time backend/frontend source changes — same command, idempotent.
```

## 8. Secrets and bringing the stack up

```bash
# On the server:
cp .env.production.example .env.production

# Generate directly on the server — never reuse anything pasted elsewhere.
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # JWT_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # MINIO_ROOT_PASSWORD (also S3_SECRET_KEY)
# edit .env.production, fill in the REPLACE_ME values

# Always pass --env-file explicitly (see DEPLOYMENT.md for why).
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build \
  postgres redis minio api worker

docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker
```

**HTTPS via a free nip.io "magic domain" + Caddy:**

```bash
cat > Caddyfile <<EOF
<instance-ip>.nip.io {
	reverse_proxy api:8000
}
EOF

docker compose --env-file .env.production -f docker-compose.prod.yml up -d caddy
curl https://<instance-ip>.nip.io/health
# {"status": "ok"}
```

**Lock down CORS once the frontend URL is known:**

```bash
sed -i 's#CORS_ALLOWED_ORIGINS=.*#CORS_ALLOWED_ORIGINS=["https://<project>.vercel.app"]#' \
  .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up -d api
```

## 9. Frontend — Vercel CLI

```bash
vercel login                 # device-authorization flow — approve the URL in your browser

cd frontend
vercel link --yes --scope <your-vercel-team-slug>

printf 'https://<instance-ip>.nip.io' | \
  vercel env add NEXT_PUBLIC_API_URL production --scope <your-team-slug>

vercel deploy --prod --scope <your-team-slug>

# To change an env var later:
vercel env rm NEXT_PUBLIC_API_URL production --yes --scope <your-team-slug>
printf '<new-value>' | vercel env add NEXT_PUBLIC_API_URL production --scope <your-team-slug>
vercel deploy --prod --scope <your-team-slug>   # redeploy to pick it up
```

## 10. Day-to-day operational commands

```bash
# Redeploy after a backend code change:
rsync -avz --exclude '.env' -e "ssh -i ~/.ssh/video-platform-key.pem" \
  ./backend/ ubuntu@<instance-ip>:/home/ubuntu/video-extraction-platform/backend/
ssh -i ~/.ssh/video-platform-key.pem ubuntu@<instance-ip> \
  "cd video-extraction-platform && \
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build api worker"

# Tail logs:
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker

# Query the database directly:
docker compose --env-file .env.production -f docker-compose.prod.yml exec postgres \
  psql -U video_platform -d video_platform -c "SELECT id, status FROM jobs ORDER BY created_at DESC LIMIT 10;"

# Run a one-off Python snippet inside the worker (debugging, minting a test token, etc.):
docker compose --env-file .env.production -f docker-compose.prod.yml exec worker \
  python -c "print('hello from the worker container')"

# Diff the fully-resolved compose config (what actually caught the stray-.env bug):
docker compose --env-file .env.production -f docker-compose.prod.yml config

# Scale the worker horizontally if concurrent job volume grows:
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --scale worker=3
```

## 11. Recovering from the stray-`.env` incident (for reference)

```bash
# On the server, once a stray dev .env was found sitting next to .env.production:
rm .env
docker compose --env-file .env.production -f docker-compose.prod.yml down
docker volume rm video-extraction-platform_postgres_data video-extraction-platform_minio_data
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build \
  postgres redis minio api worker
```

## 12. Working around YouTube's IP block — `/jobs/ingest`

```bash
# On a machine that isn't IP-blocked (e.g. your own laptop):
pip install yt-dlp requests
python3 scripts/ingest_video.py "<youtube-url>" "https://<instance-ip>.nip.io" "<your-jwt-token>"

# Get a JWT: log into the deployed frontend, then in devtools:
#   localStorage.getItem('token')
# or:
curl -X POST https://<instance-ip>.nip.io/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "..."}'
```

## 13. Password reset via email (Resend) — set up and test

```bash
# Sign up free at resend.com, create an API key under API Keys, then:

# Local dev — add to .env:
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=Rosetta <onboarding@resend.dev>
FRONTEND_URL=http://localhost:3000
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30
docker compose up -d api worker      # picks up the new env vars

# Production — add the same keys to .env.production on the server
# (FRONTEND_URL must be the real Vercel URL, not localhost), then:
docker compose --env-file .env.production -f docker-compose.prod.yml \
  up -d --build api worker

# Trigger a reset email:
curl -X POST https://<instance-ip>.nip.io/auth/forgot-password \
  -H "Content-Type: application/json" -d '{"email": "you@example.com"}'
# Always returns the same generic message whether or not the email exists —
# that's intentional, prevents enumerating registered accounts.

# Complete the reset (token comes from the emailed link's ?token= query param):
curl -X POST https://<instance-ip>.nip.io/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{"token": "<token-from-email-link>", "new_password": "..."}'
```

**Known limitation**: without a verified domain on Resend, the sandbox
sender (`onboarding@resend.dev`) can only deliver to the email address that
owns the Resend account — fine for a personal/small-scale launch, not for
other users at scale until a domain is verified.

## 14. Long-video (>1hr) part-based processing — test locally without a real 1hr+ video

```bash
# Temporarily lower thresholds in .env (must keep video_part_seconds a
# multiple of audio_chunk_seconds — enforced at startup, fails fast otherwise):
echo '
AUDIO_CHUNK_SECONDS=60
LONG_VIDEO_THRESHOLD_SECONDS=100
VIDEO_PART_SECONDS=120' >> .env
docker compose up -d api worker

# Submit any real video over 100s to exercise the part-based path locally,
# then watch parts complete one at a time (not all at once):
docker compose logs worker -f | grep -E "_start_part|stitch_part_job"

# Revert before touching production — remove the 3 temp lines from .env,
# then:
docker compose up -d api worker
```

Generate the migration for `job_parts`/its columns the same way as any
other model change — autogenerate, don't hand-write:
```bash
docker compose run --rm --no-deps api alembic revision --autogenerate -m "message"
```

**Debugging "parts stuck in processing" on a real long video**: check
whether a part's `stitch_part_job` actually ran, vs. is stuck queued behind
other work —
```bash
docker compose exec worker python -c "
from app.queue.redis_conn import redis_conn
from rq.registry import DeferredJobRegistry
from rq.queue import Queue
q = Queue('default', connection=redis_conn)
dr = DeferredJobRegistry(queue=q)
print('deferred:', dr.count, dr.get_job_ids()[:10])
print('queued:', q.count)
"
```
If a dependent job sits in `DeferredJobRegistry` with dependencies already
satisfied, something is wrong with the dependency wiring — this project's
own first version had exactly this bug (parts fanned out all at once, so
an early part's stitch got stuck behind later parts' raw work on a
single-worker deployment; fixed by chaining parts one at a time via
`_start_part`, see `DEPLOYMENT.md`'s long-video section).

## 15. Local development (unchanged throughout)

```bash
cp .env.example .env
docker compose up -d
docker compose build api worker              # rebuild after a dependency change
docker compose run --rm --no-deps api alembic revision --autogenerate -m "message"

cd frontend
npm install
npm run dev                                  # http://localhost:3000
npm run build                                # verify a production build compiles
```

## 16. Git — how the work was committed

```bash
git status
# stage specific files, never `git add -A` / `git add .`
git add backend/app/api/jobs.py backend/app/workers/tasks.py ...
git commit -m "Rework OCR pipeline, add explanation feature, rate limiting, and ingest endpoint"
git log --oneline
```
