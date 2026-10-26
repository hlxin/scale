# Running the web service on a server

A step-by-step guide to running the SCALE web service ([README.md](README.md)) on a Linux server of your own, behind
HTTPS, so that the graph explorer on GitHub Pages can sign readers in, curate papers, answer questions and open
contributions. A person does these steps: they create accounts and hold secrets.

Plan on a couple of hours, most of it waiting for a DNS name and open ports.

## What you need

- **A server.** Linux (Ubuntu 22.04 or 24.04 is easiest), 2 CPUs or more, 4 GB of memory, 20 GB of disk. No GPU.
- **A public HTTPS name** that reaches the server, such as `scale-api.example.org`, with ports 80 and 443 open to the
  internet. If your network administrators will not open ports, see [Without open ports](#without-open-ports).
- **A Claude API key** from a Claude Console workspace with a monthly spend limit. Usage paid by the service is the
  key's; a Claude Max or Team plan's monthly API credits apply when the plan is linked to that Console organization.
- **A GitHub account** to create the sign-in app, and later a bot account for contributions.

In the examples, `scale-api.example.org` is the service's name and `server` is how you reach the server over SSH.

## 1. Prepare the server

```bash
# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER        # log out and back in

# folders that outlive the container: kept papers, use counts, settings
sudo mkdir -p /srv/scale-web/archive /srv/scale-web/state
sudo chown -R 1000:1000 /srv/scale-web/archive /srv/scale-web/state   # the container runs as uid 1000
sudo touch /srv/scale-web/scale-web.env
sudo chown $USER /srv/scale-web/scale-web.env && chmod 600 /srv/scale-web/scale-web.env

# the code
sudo git clone https://github.com/hlxin/scale.git /srv/scale-web/src
sudo chown -R $USER /srv/scale-web/src
```

## 2. Create the GitHub sign-in app

GitHub → Settings → Developer settings → OAuth Apps → **New OAuth App**:

| field | value |
|---|---|
| Application name | `SCALE` |
| Homepage URL | `https://hlxin.github.io/scale/` |
| Authorization callback URL | `https://scale-api.example.org/auth/callback` |

Then **Generate a new client secret**, and keep the client ID and the secret for the next step.

## 3. Write the settings

All settings and secrets live in one file, `/srv/scale-web/scale-web.env`, readable by you alone. Never commit it.

Put the API key in without pasting it into a terminal that is logged or shared. From a Mac that keeps the key in its
Keychain (under the account `scale-web` and the service `ANTHROPIC_API_KEY`):

```bash
printf 'ANTHROPIC_API_KEY=%s\n' "$(security find-generic-password -a scale-web -s ANTHROPIC_API_KEY -w)" \
  | ssh server 'cat >> /srv/scale-web/scale-web.env'
```

Otherwise open the file in an editor on the server and type the line `ANTHROPIC_API_KEY=...`.

Then add the rest (`nano /srv/scale-web/scale-web.env`):

```bash
SCALE_WEB_SECRET=            # the output of: openssl rand -hex 32
SCALE_WEB_PUBLIC_URL=https://scale-api.example.org
SCALE_WEB_SITE_ORIGINS=https://hlxin.github.io
GITHUB_CLIENT_ID=            # from step 2
GITHUB_CLIENT_SECRET=        # from step 2

# who may curate and ask: start with yourself, add logins, and use * for any GitHub account later
SCALE_WEB_ALLOWLIST=your-github-login

# cost: a smaller model makes a monthly budget go further than the default
SCALE_WEB_MODEL=claude-sonnet-5-5
SCALE_WEB_TOKENS_PER_DAY=3000000
SCALE_WEB_JOBS_PER_USER=5

# the page's contact for a rights holder, and the address Unpaywall asks for
SCALE_CONTACT_EMAIL=         # a role address, not a person's

# use counts for the leaderboard, on a mounted folder
SCALE_WEB_USAGE=/data/state/usage.json

# kept papers: leave unset until the legal check (README, "Before keeping papers in copyright")
# SCALE_WEB_ARCHIVE=/data/archive
```

The other settings and their defaults are in the [README's table](README.md#settings-environment).

## 4. Build and start the service

```bash
cd /srv/scale-web/src
docker build -f service/Dockerfile -t scale-web .
docker run -d --name scale-web --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  --env-file /srv/scale-web/scale-web.env \
  -v /srv/scale-web/archive:/data/archive \
  -v /srv/scale-web/state:/data/state \
  scale-web
curl -s http://127.0.0.1:8080/health      # the schema version, and the contact
```

The service listens on the server only (`127.0.0.1`); the proxy of the next step is its one way in.

## 5. Put HTTPS in front

[Caddy](https://caddyserver.com/docs/install) obtains and renews the certificate itself:

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
scale-api.example.org {
    request_body {
        max_size 45MB
    }
    reverse_proxy 127.0.0.1:8080
}
EOF
sudo systemctl reload caddy
```

From another computer, `curl -s https://scale-api.example.org/health` answers as in step 4.

With nginx instead, set `client_max_body_size 45m;` (the largest PDF is `SCALE_WEB_MAX_UPLOAD_MB`, 40 by default) and
use a certificate from your network administrators or Let's Encrypt.

## 6. Point the page at it

Open a pull request (or ask an agent to) that sets the address in [`site/config.js`](../site/config.js):

```js
window.SCALE_SERVICE_URL = "https://scale-api.example.org";
```

Once it is merged, the site is published again. Reload the page (Shift-reload, past the browser's cache):

- **Sign in with GitHub** appears.
- **Curate** takes a PDF or a DOI.
- Questions are answered in words.

Curate one paper yourself before you widen the allowlist.

## 7. Contributions (can wait)

Contributing a curated paper opens a pull request from a bot, never from the reader's account or yours.

1. Create a GitHub account for the bot and add it to `hlxin/scale` with write access. Pushes to main stay blocked by
   the repository's ruleset.
2. Signed in as the bot, create a fine-grained token for `hlxin/scale` only, with **Contents** and **Pull requests**
   set to read and write.
3. Add both lines below to the settings and restart the service (`docker restart scale-web`):

   ```bash
   SCALE_WEB_GITHUB_TOKEN=     # the bot's token
   SCALE_WEB_REVIEWERS=        # logins asked to review each contribution, comma-separated
   ```

Without them, everything else works, and Contribute answers that contributions are not set up on this service.

## Running it

| task | how |
|---|---|
| update to the latest main | `cd /srv/scale-web/src && git pull && docker build -f service/Dockerfile -t scale-web .`, then `docker rm -f scale-web` and the `docker run` of step 4 |
| read the logs | `docker logs -f scale-web` |
| change a setting | edit `scale-web.env`, then `docker restart scale-web` |
| back up | `/srv/scale-web/archive` and `/srv/scale-web/state`; nothing else holds data |
| curate kept papers again after a schema change | `docker exec scale-web python -m scaleweb --recurate --dry-run`, then without `--dry-run` |

Keep these in mind:

- **A restart forgets work in progress.** It drops running jobs and resets the day's budgets, which are counted in
  memory. Update at a quiet time.
- **Run one instance.** Two copies of the service would each count their own budgets.
- **Keep the server patched.** Open only SSH, 80 and 443, and keep `scale-web.env` at `chmod 600`: it holds every
  secret.
- **Bound spending twice.** Set the workspace spend limit in the Claude Console as well as `SCALE_WEB_TOKENS_PER_DAY`.

## Without open ports

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) reaches the
service from the server outward, so no port is opened. It needs a domain managed by Cloudflare.

1. Install `cloudflared` on the server.
2. Create the tunnel and its DNS name:

   ```bash
   cloudflared tunnel login
   cloudflared tunnel create scale-web
   cloudflared tunnel route dns scale-web scale-api.example.org
   ```

3. In `~/.cloudflared/config.yml`, send the name to `http://127.0.0.1:8080`.
4. Run the tunnel as a service: `sudo cloudflared service install`.

Skip step 5: the tunnel serves HTTPS.

## When something fails

| symptom | likely cause |
|---|---|
| the container exits at once | `SCALE_WEB_SECRET` is missing or shorter than 32 characters (`docker logs scale-web`) |
| the page says the service is not configured | `site/config.js` is not set yet, or the browser shows the old page (Shift-reload) |
| the browser console shows a CORS error | `SCALE_WEB_SITE_ORIGINS` is not the page's origin, `https://hlxin.github.io` (scheme and host, no path) |
| sign-in fails at GitHub with a redirect error | the OAuth app's callback is not `<SCALE_WEB_PUBLIC_URL>/auth/callback` |
| "sign in with a GitHub account on the allowlist" | add the login to `SCALE_WEB_ALLOWLIST` and restart |
| a large PDF fails to upload | the proxy's body limit (step 5) is below the upload limit |
| jobs fail with "credit balance is too low" | the Console organization's credits are spent; add credits or wait for the next month's |
