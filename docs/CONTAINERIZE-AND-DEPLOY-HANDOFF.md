# Containerize & one-command deploy — handoff spec

This describes a containerization + remote-deploy pattern proven on another
Python project (a FastAPI web app + Postgres + worker behind a Caddy reverse
proxy), distilled into a **reusable recipe** and pre-adapted for **this project
(EnergiBalanse)**.

**This project, as observed:** a standalone Python service that
- has **no web server** (nothing inbound — it does not listen for HTTP),
- has **no database**,
- talks **MQTT** to an external broker and makes **outbound REST/OCPP** calls,
- is configured by `requirements.txt` + YAML files in `conf/` and the repo root,
- runs one or more long-lived loops (the repo shows `mqtt_client`,
  `charge_controller`, `shedder`, `timebuffer` log files),
- **writes runtime state to files** (`cache.json`, `power_buffer_*.yaml`, logs).

The goal: deploy to a Linux server with one command from Windows —

```powershell
./deploy/deploy.ps1 -Server you@your-server
```

> ⚠️ Read **§6 (project-specific notes)** before copying templates — this project
> has two wrinkles the generic recipe doesn't: it uses `requirements.txt` (not a
> packaged `pyproject.toml`), and it writes state into the working tree, which
> the git-based deploy would otherwise clobber.

---

## 1. The core idea

1. **One Docker image** built from a `Dockerfile` at the repo root. It installs
   the dependencies and copies the code. *Which* process runs is decided by the
   container's `command:` in compose — so one image can back several services
   (the original runs `web` and `worker` from a single image this way; here you
   might run `mqtt_client`, `charge_controller`, `shedder` similarly).
2. **`docker compose` describes the running service(s).** Start with one; add
   more with different `command:`s if you split the loops into separate containers.
3. **All configuration/secrets live in one gitignored env file** (`deploy/docker.env`),
   created on the server from a committed template (`deploy/docker.env.template`).
   Compose passes it to the container via `env_file:`.
4. **Deploy is git-based and pull-style.** `deploy.ps1` runs on your Windows
   machine: it `git push`es your branch, then SSHes into the server and runs
   `git fetch` + `git reset --hard origin/<branch>` + `docker compose up -d --build`.
   Because the env file is gitignored, `reset --hard` never clobbers your secrets.
5. **The server holds almost no state.** The only thing installed on the host is
   Docker. "Moving servers" = install Docker, clone repo, drop in `docker.env`
   (+ restore any state volume), `up -d --build`.

### What you DON'T need here (vs. the original web app)
- **Caddy reverse proxy + HTTPS + domain + DNS** — nothing inbound.
- **Postgres + data volume + healthcheck** — no DB.
- **Published ports** — outbound-only, so the container publishes **no ports**.
- **Firewall rules for 80/443** — only SSH needs to be open.

### What transfers directly
- The `Dockerfile` shape (slim Python base, non-root user).
- A compose service with `restart: unless-stopped` + `env_file:`.
- The gitignored `docker.env` + committed `docker.env.template` pattern.
- `.dockerignore` to keep the build lean and secret-free.
- `deploy/deploy.ps1` — the push-then-SSH-pull-rebuild script (nearly verbatim).
- One-time server setup (install Docker, SSH key to GitHub, clone, env file).

---

## 2. Files to create

```
EnergiBalanse/
├─ Dockerfile
├─ .dockerignore
├─ requirements.txt              # (exists)
├─ conf/ ...                     # (exists — config YAML)
├─ ocpp/ shedder/ scripts/ ...   # (exists — code)
└─ deploy/
   ├─ docker-compose.yml
   ├─ docker.env.template         # committed, no secrets
   ├─ docker.env                  # created on server + locally, GITIGNORED
   └─ deploy.ps1
```

### 2.1 `Dockerfile` (repo root) — requirements.txt variant

```dockerfile
# syntax=docker/dockerfile:1
#
# Single image for the EnergiBalanse service(s). The process is set by the
# container's command in deploy/docker-compose.yml.

FROM python:3.12-slim

# Stream logs straight to Docker, skip .pyc clutter, keep pip quiet and cache-free.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# If any dependency needs a C toolchain to build (no prebuilt wheel), add an
# apt-get layer here first, e.g.:
#   RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
#       && rm -rf /var/lib/apt/lists/*

# Install deps first (cached unless requirements change), then copy the code.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user inside the container.
RUN useradd --system --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# No EXPOSE / no ports — outbound MQTT + REST/OCPP only.
# Replace with this project's real entrypoint (see §6 — confirm the module/script).
CMD ["python", "-m", "shedder"]
```

> `COPY . .` relies on a good `.dockerignore` (next) so the huge `*.log` files
> and `.venv` don't bloat the image. Keep deps in their own layer so day-to-day
> code changes don't reinstall everything.

### 2.2 `.dockerignore` (repo root)

```gitignore
# Keep the build context small and free of secrets / local cruft.
.git/
.venv/
venv/
**/__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Local logs and runtime state — never bake into the image.
*.log
cache.json

# Secrets and local env.
.env
.env.*
deploy/docker.env

# Editor / CI / things the image doesn't need.
.vscode/
.claude/
```

### 2.3 `deploy/docker-compose.yml`

```yaml
# EnergiBalanse — production stack for a single host.
#
# Run from the repository root:
#   docker compose -f deploy/docker-compose.yml up -d --build
#
# All configuration lives in deploy/docker.env — copy docker.env.template to
# docker.env and fill it in.

name: energibalanse

services:
  app:
    build:
      context: ..
      dockerfile: Dockerfile
    image: energibalanse:latest
    restart: unless-stopped        # auto-restart on crash, reboot, or MQTT drop
    env_file: docker.env
    # No ports: outbound-only (MQTT + REST/OCPP to external services).
    volumes:
      # Persist runtime state OUTSIDE the git working tree so deploy's
      # `git reset --hard` can't wipe it (see §6). The app must be told to read
      # and write state here (e.g. STATE_DIR=/state in docker.env).
      - app-state:/state

  # If you split the loops into separate containers, reuse the SAME image and
  # just change the command — compose builds it once:
  #
  # mqtt:
  #   image: energibalanse:latest
  #   restart: unless-stopped
  #   env_file: docker.env
  #   command: ["python", "-m", "mqtt_client"]
  #   volumes: [ "app-state:/state" ]

volumes:
  app-state:
```

### 2.4 `deploy/docker.env.template` (committed — NO real secrets)

Fill with what this project actually needs (MQTT, the REST/OCPP backends, paths).

```dotenv
# EnergiBalanse — Docker deployment environment
# =============================================
# Copy this file to "docker.env" (same directory) and fill in every value:
#   cp deploy/docker.env.template deploy/docker.env
#
# docker.env holds secrets and is gitignored — never commit it.
#
# Format rules (docker compose env_file): KEY=value, one per line. Do NOT wrap
# values in quotes and do NOT put inline comments after a value.

# --- MQTT broker (external) --------------------------------------------------
MQTT_HOST=broker.example.com
MQTT_PORT=8883
MQTT_USERNAME=CHANGE_ME
MQTT_PASSWORD=CHANGE_ME
MQTT_TLS=true
MQTT_TOPIC_PREFIX=energibalanse

# --- Upstream REST / OCPP services -------------------------------------------
REST_BASE_URL=https://api.example.com
REST_API_KEY=CHANGE_ME
# OCPP_BACKEND_URL=...

# --- Paths / runtime ---------------------------------------------------------
# Where the app reads/writes persistent state (mapped to the app-state volume).
STATE_DIR=/state
# LOG_LEVEL=INFO
```

Add `deploy/docker.env` to this repo's existing `.gitignore`.

### 2.5 `deploy/deploy.ps1` — the one-command deploy

```powershell
#!/usr/bin/env pwsh
# Deploy EnergiBalanse from this machine to the server.
#
# Pushes the chosen branch to origin, then SSHes into the server to pull the
# latest code and (re)build the Docker stack. Compose only recreates a service
# if its image or config actually changed.
#
# Usage:
#   ./deploy/deploy.ps1 -Server you@your-server
#   ./deploy/deploy.ps1 -Server you@your-server -Path /opt/energibalanse -Branch main
#   ./deploy/deploy.ps1 -Server you@your-server -Port 22375   # non-standard SSH port
#
# One-time prerequisites (see §3):
#   - key-based SSH access to the server
#   - the repo cloned to <Path> on the server
#   - deploy/docker.env created and filled in ON THE SERVER (it is gitignored,
#     so `git reset --hard` below never touches it)

param(
    [Parameter(Mandatory = $true)] [string]$Server,
    [string]$Path = "/opt/energibalanse",
    [string]$Branch = "main",
    [int]$Port = 22
)

$ErrorActionPreference = "Stop"

Write-Host "==> Pushing '$Branch' to origin..." -ForegroundColor Cyan
git push origin $Branch

# Remote script: sync the checkout to origin/<branch>, then rebuild + restart.
$remote = @"
set -e
cd '$Path'
git fetch --all --prune
git checkout '$Branch'
git reset --hard 'origin/$Branch'
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
"@

# This file is CRLF on Windows; remote bash treats a trailing '\r' as part of
# each command ('set -e\r' -> "invalid option", blank lines -> $'\r'). Send LF.
$remote = $remote -replace "`r`n", "`n"

Write-Host "==> Deploying on $Server (port $Port, $Path)..." -ForegroundColor Cyan
ssh -p $Port $Server $remote
if ($LASTEXITCODE -ne 0) {
    throw "Remote deploy failed (ssh exit code $LASTEXITCODE)."
}

Write-Host "==> Done. Tail logs with:" -ForegroundColor Green
Write-Host "    ssh -p $Port $Server 'cd $Path && docker compose -f deploy/docker-compose.yml logs -f'"
```

**Load-bearing gotcha:** keep the `$remote -replace "`r`n","`n"` line. PowerShell
here-strings are CRLF; without converting to LF the remote bash sees `set -e\r`
and errors. Don't remove it.

---

## 3. One-time server setup (Ubuntu 24.04 LTS)

### 3a. Install Docker (official repo — NOT Ubuntu's `docker.io`, it ships an old Compose)

```bash
sudo apt-get remove -y docker docker-engine docker.io containerd runc || true
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER     # run docker without sudo; log out/in afterwards
```

Verify: `docker version` and `docker compose version`.

### 3b. Firewall — SSH only

```bash
sudo ufw allow OpenSSH
sudo ufw enable
```

No 80/443: nothing inbound. The MQTT client and REST calls dial out, so no
inbound rule is needed.

### 3c. Let the server pull from GitHub (SSH deploy key)

```bash
ssh-keygen -t ed25519 -C "energibalanse-$(hostname)" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Add the printed public key to GitHub as a **Deploy key** (repo → Settings →
Deploy keys; leave write access off) or an account SSH key. Verify:

```bash
ssh -T git@github.com   # success greeting even though it "fails" to open a shell
```

### 3d. Clone and configure

```bash
sudo mkdir -p /opt/energibalanse
sudo chown "$USER:$USER" /opt/energibalanse
git clone git@github.com:YOU/EnergiBalanse.git /opt/energibalanse
cd /opt/energibalanse
cp deploy/docker.env.template deploy/docker.env
nano deploy/docker.env          # fill in every CHANGE_ME
```

### 3e. SSH key from Windows → server (so deploy.ps1 is passwordless)

```powershell
ssh-keygen -t ed25519                                  # press Enter through prompts
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh you@your-server "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### 3f. First launch (on the server)

```bash
cd /opt/energibalanse
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f      # Ctrl-C to stop following
```

---

## 4. Day-to-day

```powershell
# Deploy an update (from Windows, one line):
./deploy/deploy.ps1 -Server you@your-server
./deploy/deploy.ps1 -Server you@your-server -Path /opt/energibalanse -Branch main -Port 22375
```

```bash
# Operate (on the server, from /opt/energibalanse):
docker compose -f deploy/docker-compose.yml logs -f
docker compose -f deploy/docker-compose.yml restart app
docker compose -f deploy/docker-compose.yml up -d        # apply docker.env edits
docker compose -f deploy/docker-compose.yml down         # stop + remove containers (keeps volumes)
```

A `~/.ssh/config` entry (`Host energibalanse` / `HostName` / `User` / `Port`)
lets you write `./deploy/deploy.ps1 -Server energibalanse` and skip `-Port`.

---

## 5. Resilience

`restart: unless-stopped` covers process crashes and server reboots — Docker
relaunches the container. The MQTT/REST loops must still handle in-process
reconnects (auto-reconnect on broker disconnect, ret/backoff on REST errors);
Docker only helps when the process fully exits.

---

## 6. ⚠️ Project-specific notes for EnergiBalanse (read before coding)

These are the points where this project departs from the generic recipe — the
receiving developer/Claude must resolve them:

1. **`requirements.txt`, not a package.** The Dockerfile above installs with
   `pip install -r requirements.txt` and `COPY . .` (rather than building a
   wheel). Confirm `requirements.txt` is complete and pinned.

2. **Confirm the real entrypoint(s).** The repo shows several long-running loops
   (`mqtt_client`, `charge_controller`, `shedder`, `timebuffer` — each has its
   own log). Decide whether they run:
   - as **one process** (set the single `CMD` accordingly), or
   - as **several containers from the one image**, each with its own `command:`
     in compose (see the commented `mqtt:` example). This mirrors how the
     original runs `web` + `worker` from a single image.
   Replace the placeholder `CMD ["python", "-m", "shedder"]` with the correct
   module/script (check how the project is started today — VS Code launch
   config, a script in `scripts/`, or a shell command).

3. **Runtime state must NOT live in the git working tree.** This project writes
   state files (`cache.json`, `power_buffer_export.yaml`, `power_buffer_import.yaml`,
   logs, possibly files under `conf/`). The deploy runs `git reset --hard`, which
   **overwrites any tracked file** every deploy. In the container model the code
   is copied into the image, so the container does **not** write to the host repo
   — but you still must give it a **persistent, writable location** that survives
   image rebuilds. Approach:
   - Point the app's state/output paths at `STATE_DIR=/state` (env) and mount the
     `app-state` named volume there (already in the compose example).
   - Make sure no state file is read from / written to a path baked into the
     image; if config in `conf/*.yaml` is *edited at runtime*, move that to the
     volume too. Config that is **read-only at runtime** can stay in the image.
   - Whatever stays git-tracked AND gets written at runtime is a bug waiting for
     the next deploy — audit the file paths the code opens for writing.

4. **Logs.** The repo currently accumulates large `*.log` files in the working
   tree. In containers, log to **stdout/stderr** instead and let
   `docker compose logs` capture them (the Dockerfile already sets
   `PYTHONUNBUFFERED=1`). If you must keep file logs, write them under `/state`.
   `.dockerignore` excludes `*.log` so they never enter the image.

5. **Secrets currently in YAML?** If broker credentials / API keys live in
   `conf/*.yaml` today, move them into `docker.env` (gitignored) and have the app
   read them from environment variables, so `reset --hard` and the image never
   carry secrets.

---

## 7. Checklist

- [ ] Add `Dockerfile` (requirements.txt variant); set the real `CMD`.
- [ ] Add native build deps to the Dockerfile only if a wheel isn't available.
- [ ] Add `.dockerignore`.
- [ ] Add `deploy/docker-compose.yml`; decide single- vs multi-service.
- [ ] Add `deploy/docker.env.template`; add `deploy/docker.env` to `.gitignore`.
- [ ] Move runtime state + writable config to the `app-state` volume / `STATE_DIR`.
- [ ] Move secrets out of `conf/*.yaml` into `docker.env`.
- [ ] Switch file logging to stdout (or to `/state`).
- [ ] Add `deploy/deploy.ps1` (keep the CRLF→LF line); set the default `-Path`.
- [ ] One-time: install Docker, open SSH only, GitHub deploy key, clone to
      `/opt/energibalanse`, create `docker.env`, add your Windows SSH key.
- [ ] First launch: `docker compose -f deploy/docker-compose.yml up -d --build`.
- [ ] Verify MQTT reconnect + REST retry behavior in-process.
```
