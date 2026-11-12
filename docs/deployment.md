# Deployment

The same code runs in two modes, chosen with `VF_MODE` (or `"mode"` in `<data dir>/config/deploy.json`):

| | Self-hosted (`selfhost`, default) | SaaS (`saas`) |
|---|---|---|
| Operated by | a school, lab or company on its own server | a hosting provider |
| Organisations | one ("default") | many, each isolated from the others |
| Seats come from | a signed licence file (offline activation), unlimited without one | the operations console `/ops` |
| Plants on the server | yes: simulation, OPC UA, Modbus, MQTT | no: plants run only in the desktop clients |
| Browser pages | everything, plus organisation management `/org` and class progress `/progress` | organisation management, classes and grades, class progress, accounts; operations console `/ops` |

A more detailed Chinese version of this page is in [部署-自部署与SaaS.md](部署-自部署与SaaS.md).

## Docker

```bash
cp docker/env.example .env        # adjust VF_LANG, TZ, ports, AI endpoint
docker compose -f docker-compose.yml -f docker/compose.production.yml up -d
```

- One container (`factory`) runs the simulation, the web UI and API (8800), OPC UA (4840), MQTT (1883) and Modbus TCP
  (5020–5029, one port per plant).
- All data lives in the volume `vf-data` mounted at `/data` (`VF_HOME=/data`): `data/`, `plants/`, `config/`,
  `logs/`. The image runs as an unprivileged user (uid 10001).
- `docker/compose.production.yml` turns demo mode off (`VF_DEMO=0`) and publishes the protocol ports on `127.0.0.1`
  only. The first visit to http://<host>:8800 asks for the administrator account, or:

  ```bash
  docker compose exec factory python -m vfactory create-admin --username admin
  ```

- A data volume that was first started in demo mode keeps its demo accounts. Start production on a fresh volume
  (`docker compose down -v` deletes all data) or under another project name (`-p`).
- AI: set `VF_LLM_BASE_URL`, `VF_LLM_API_KEY` and `VF_LLM_MODEL` in `.env`, or put `config/llm.local.json` into the
  volume (`/data/config/llm.local.json`).
- Behind a slow or filtered connection, the build takes mirrors as build arguments (all optional):

  ```bash
  docker build -t honeyfactory:local \
    --build-arg NODE_IMAGE=<registry mirror>/library/node:22-bookworm-slim \
    --build-arg PYTHON_IMAGE=<registry mirror>/library/python:3.12-slim-trixie \
    --build-arg NPM_REGISTRY=https://<npm mirror>/ \
    --build-arg DEBIAN_MIRROR=http://<debian mirror host> \
    --build-arg PIP_MIRROR=https://<pypi mirror>/simple .
  ```

  `DEBIAN_MIRROR` replaces `http://deb.debian.org` in the apt sources. If the `# syntax=` line cannot be resolved,
  add `--build-arg BUILDKIT_SYNTAX=<registry mirror>/docker/dockerfile:1`. Then start with
  `HONEYFACTORY_IMAGE=honeyfactory:local docker compose up` (Compose builds only when the image is missing).
- Headless test script against the image: `docker compose --profile test run --rm factory-test` (JUnit in
  `./test-results/junit.xml`).

## Without Docker

```bash
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
VF_HOME=/srv/honeyfactory python -m vfactory serve --http 8800
```

Run it under a service manager (systemd, NSSM on Windows) with a dedicated user. `VF_HOME` keeps the data outside the
program directory, so upgrading is replacing the program directory and restarting. The demo plant
`foundry-housing` is created in `<data dir>/plants/` when the folder is empty.

## First administrator

A production server (no `VF_DEMO`) has no accounts. Until an active administrator exists, the login page shows a
**Create administrator** form (`GET /api/setup/admin` → `{needed, demo, lang}`, `POST /api/setup/admin`
`{username, password, name}`), and `python -m vfactory create-admin` does the same on the command line. The password
must have at least 8 characters and must not be one of the published demo passwords. SaaS mode and the desktop client
never offer this form.

## HTTPS reverse proxy

HoneyFactory serves plain HTTP. Put a reverse proxy with TLS in front of it whenever it is reachable beyond a trusted
network; the WebSocket path `/ws/` (live plant view) needs the upgrade headers.

Nginx:

```nginx
map $http_upgrade $connection_upgrade { default upgrade; '' close; }

server {
    listen 443 ssl http2;
    server_name factory.example.org;
    ssl_certificate     /etc/ssl/factory/fullchain.pem;
    ssl_certificate_key /etc/ssl/factory/privkey.pem;

    client_max_body_size 64m;          # same as VF_MAX_BODY_MB

    location / {
        proxy_pass http://127.0.0.1:8800;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        $connection_upgrade;
        proxy_read_timeout 360s;           # grading a submitted homework package can take a few minutes
    }
}
server { listen 80; server_name factory.example.org; return 301 https://$host$request_uri; }
```

Caddy:

```
factory.example.org {
    reverse_proxy 127.0.0.1:8800
    request_body { max_size 64MB }
}
```

- With `X-Forwarded-Proto: https` the server marks cookies Secure and sends `Strict-Transport-Security`. If the proxy
  does not send the header, set `VF_HTTPS=1`.
- Uvicorn trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`); add the proxy's address
  when it runs on another host.
- The main UI authenticates with a bearer token (not a cookie), the operations console with a cookie plus a CSRF token.
- Security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: same-origin`.

The OPC UA, Modbus and MQTT servers of the simulated plant have no authentication. Keep them inside a lab network.

## Licence files (self-hosted)

Seats for teachers and students can be limited by a licence file `.vflic`: a JSON payload (licence id,
organisation, seats, start and end date, feature packs, AI quota) with an Ed25519 signature. The server verifies it
offline against the public keys in `vfactory/tenancy/license_keys.py`.

- Import it under **Organisation → Licence** or place it at `<data dir>/config/license.vflic`.
- Without a licence file seats are unlimited (the page shows "not activated"). With `VF_LICENSE_REQUIRED=1` the trial
  limits apply (5 teachers, 50 students).
- After expiry, existing accounts keep working, but no new teacher or student accounts can be created.
- A modified file, or one signed with an unknown key, is treated as no licence and the page shows why.

The open-source repository contains public keys only. `tools/license_sign.py keygen | sign | verify` is the issuing
tool; it refuses to write a private key inside the repository. If you run your own distribution, generate your own
key pair and put your public key into `TRUSTED`.

## Organisation administrators (`/org`)

The `orgadmin` role (and `admin` on self-hosted servers) can create teachers within the seat limit, import students
(paste "id, name[, password]" or two Excel columns; a batch that exceeds the seats is rejected as a whole), archive
students at the end of a term (frees seats, keeps grades), disable teachers, reset passwords, see usage, export all of
the organisation's data as a zip and delete all of it.

## SaaS mode

```bash
export VF_MODE=saas
export VF_HOME=/srv/honeyfactory
export VF_HTTPS=1
export FORWARDED_ALLOW_IPS=127.0.0.1
python -m vfactory serve --http 8800
```

In SaaS mode the server creates no demo plant and no demo accounts and opens no OPC UA, Modbus or MQTT ports. Plants,
sandboxes and the modeling assistant are not available on the server (HTTP 403 with an explanation); pages that need a
plant offer an "Open in the client" link (`vfactory://open?path=...`). Students and teachers use the desktop client,
which reports progress to the server and submits homework packages. In SaaS mode a submitted package is recorded with
the score computed on the client (`verified=false`); `vfactory/tenancy/hooks.py` has a `register_rescorer(fn)` hook for
server-side re-scoring.

Teachers build courses in their client (drafts, checks and previews run locally). Publishing signs the course
package on the teacher's machine; the server verifies structure, hashes and signature without running a plant and
re-signs the package with its own key when students download it.

### Operations console (`/ops`)

```bash
VF_HOME=/srv/honeyfactory python tools/ops_admin.py create --username ops.admin --name "Operations"
```

prints a one-time password. Log in at `https://<host>/ops`, bind an authenticator app (TOTP), save the 10 recovery
codes and change the password. Other commands: `reset` (password and TOTP), `list`, `verify-audit` (hash chain).

The console creates organisations (code, name, contract dates, teacher and student seats, feature packs, monthly AI
quota, first organisation administrator), 30-day trials (5 teachers, 50 students), shows usage, manages operations
accounts and keeps an append-only audit log with a hash chain. Sensitive actions ask for a fresh TOTP code. Sessions
end after 15 idle minutes or 8 hours (`VF_OPS_IDLE_MIN`, `VF_OPS_MAX_HOURS`); an IP allow-list can be set in the
console or with `VF_OPS_IPS`. There is no "log in as organisation".

### AI proxy

Desktop clients without their own model configuration call the server's `/api/ai/proxy/chat/completions`. The key
stays on the server; usage is metered per organisation and month, and AI is switched off for an organisation whose
quota is used up.

## Security checklist

| Topic | What HoneyFactory does |
|---|---|
| Tenant isolation | every endpoint checks the user's organisation (`vfactory/tenancy/policy.py`); `tests/tenant_check.py` enumerates all endpoints |
| Login | 5 failed attempts lock an account for 15 minutes; 30 failures from one IP within 10 minutes pause it |
| Passwords | strict policy in SaaS mode or with `VF_PW_POLICY=strict`; initial passwords must be changed on first login |
| Sessions | revocable (logout, password change, archive, disabled account or organisation); `/api/me/sessions` |
| Uploads | request size limit (`VF_MAX_BODY_MB`), per-type limits, path traversal checks |
| Operations | TOTP, re-verification, IP allow-list, short sessions, cookie + CSRF, hash-chained audit |
| AI | key only on the server, metered per organisation |

## Backups and upgrades

- Back up `<data dir>/data`, `<data dir>/plants` and `<data dir>/config`. For a consistent copy stop the server, or
  copy `data/vf.db` with `sqlite3 vf.db ".backup vf-backup.db"`. Organisation administrators can also export their
  organisation's data from `/org`.
- Upgrades: replace the program (or pull a new image) and restart. New tables and columns are created at start-up;
  existing accounts, classes, assignments and submissions are kept.
