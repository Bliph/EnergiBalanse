# Deploying EnergiBalanse

This deploys the **shedder** service (the EV charge controller) as a single
Docker container. It is outbound-only — it dials an external MQTT broker and the
Tesla API, and listens on no ports.

> Model: one Docker image, built on the server from this git repo. Config/secrets
> live in a gitignored `docker.env`; runtime state lives in a Docker volume. The
> server holds nothing but Docker, the cloned repo, and those two things.
> For the full rationale see [`../CONTAINERIZE-AND-DEPLOY-HANDOFF.md`](../CONTAINERIZE-AND-DEPLOY-HANDOFF.md).

---

## A. One-time server setup (Ubuntu)

Do this once per server.

**1. Install Docker** (official repo — Ubuntu's `docker.io` ships an old Compose):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # then log out/in so `docker` works without sudo
docker compose version            # verify
```

**2. Open SSH only** (nothing inbound is needed):

```bash
sudo ufw allow OpenSSH && sudo ufw enable
```

**3. Let the server pull from GitHub** — add an SSH deploy key:

```bash
ssh-keygen -t ed25519 -C "energibalanse-$(hostname)" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub      # add this to GitHub repo → Settings → Deploy keys
ssh -T git@github.com          # verify (a greeting = success)
```

**4. Clone the repo** (this guide uses `~/git/EnergiBalanse`):

```bash
mkdir -p ~/git
git clone git@github.com:Bliph/EnergiBalanse.git ~/git/EnergiBalanse
cd ~/git/EnergiBalanse
```

**5. Create the secrets file** from the template and fill in every value:

```bash
cp deploy/docker.env.template deploy/docker.env
nano deploy/docker.env         # MQTT_HOST/PORT/USERNAME/PASSWORD, TESLA_EMAIL
```

`docker.env` is gitignored, so deploys never overwrite it.

**6. Seed the runtime state volume.** The Tesla OAuth token cache *must* be
provided up front — interactive login can't happen inside a container. Copy your
working `tesla_cache.json` (and, optionally, your tuned `shedder_control.yaml`)
into `conf/` on the server, then run:

```bash
docker run --rm \
  -v energibalanse_shedder-state:/state \
  -v "$PWD/conf":/seed:ro busybox \
  sh -c "cp /seed/tesla_cache.json /state/ && \
         cp /seed/shedder_control.yaml /state/ 2>/dev/null; \
         chown -R 10001:10001 /state"
```

> The `chown` matters: the container runs as uid 10001 and needs to rewrite the
> token cache when it refreshes.

**7. Allow your laptop to deploy passwordlessly** (run on Windows):

```powershell
ssh-keygen -t ed25519     # if you don't already have a key
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh you@your-server "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

---

## B. Deploy (every time, from Windows)

One command from the repo root. It pushes your branch, then SSHes in to pull and
rebuild:

```powershell
./deploy/deploy.ps1 -Server you@your-server -Branch main
```

Options: `-Path /home/johan/git/EnergiBalanse` (default), `-Branch main` (default),
`-Port 22` (default). Example with a non-standard SSH port:

```powershell
./deploy/deploy.ps1 -Server you@your-server -Branch container -Port 22375
```

Tip: a `~/.ssh/config` entry lets you shorten `-Server you@host -Port 22375` to
just `-Server energibalanse`.

---

## C. Operate (on the server, from `~/git/EnergiBalanse`)

```bash
docker compose -f deploy/docker-compose.yml logs -f       # follow logs
docker compose -f deploy/docker-compose.yml ps            # status
docker compose -f deploy/docker-compose.yml restart shedder
docker compose -f deploy/docker-compose.yml up -d         # apply docker.env edits
docker compose -f deploy/docker-compose.yml down          # stop (keeps the volume)
```

Settings precedence: `docker.env` env vars override `conf/shedder.conf`. To change
a secret/connection value, edit `docker.env` and run `up -d`. To change tuning
(topics, location, timings), edit `conf/shedder.conf` and redeploy.

---

## D. Updating the TeslaPy fork

The image installs the fork pinned to a commit (see [`../requirements.txt`](../requirements.txt)).
To ship fork changes:

1. Push to `github.com/Bliph/TeslaPy`.
2. Get the new commit: `git -C path/to/TeslaPy rev-parse HEAD`.
3. Replace the SHA in `requirements.txt`, then deploy. The changed SHA forces pip
   to re-fetch (and busts Docker's layer cache).

---

## Notes

- **Not included:** the OCPP-MQTT bridge under `ocpp/` is not containerized by this
  stack. It listens on port 8180 (inbound), so it would need a published port and a
  firewall rule if you add it later.
- **Secrets in git history:** the old MQTT password and Tesla token cache are still
  in past commits — rotate the MQTT credentials.
- **Resilience:** `restart: unless-stopped` relaunches the container on crash or
  reboot. In-process MQTT auto-reconnect still does the rest.
