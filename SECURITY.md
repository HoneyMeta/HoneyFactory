# Security policy

## Reporting a vulnerability

Please do not report security problems in public issues, pull requests or discussions.

Use one of these private channels:

- GitHub: **Security → Report a vulnerability** on https://github.com/HoneyMeta/HoneyFactory (private vulnerability
  reporting), or
- e-mail **dev@honeymeta.com** with the subject `SECURITY: <short description>`.

Include what you can of the following:

- the affected version or commit, and how HoneyFactory was deployed (Docker, bare metal, Windows desktop client,
  self-hosted or SaaS mode);
- the component (API endpoint, web page, OPC UA / Modbus / MQTT server, soft PLC, teaching MES, assignment packages
  `.vfhw`, desktop client, Docker setup);
- steps to reproduce, a proof of concept, and the impact you expect;
- whether the problem is already public.

What happens next:

- We confirm receipt within 3 working days.
- We send a first assessment (accepted or not, severity, planned fix) within 10 working days.
- We agree a disclosure date with you. By default we publish an advisory when a fixed release is available, and no
  later than 90 days after the report. We credit you in the advisory unless you prefer not to be named.

## Supported versions

Security fixes go into the latest release and the `main` branch. Older releases are not patched; upgrade to the
latest release (see [docs/deployment.md](docs/deployment.md)). Customers with a commercial support agreement get fixes
according to their agreement.

## Deployment notes

These are known properties of the software, not vulnerabilities. Please take them into account before you report.

- **Demo mode is not for production.** With `VF_DEMO=1` HoneyFactory creates demo accounts (teacher, students,
  engineers) that share the published password `honey123`. Never expose a demo instance to an untrusted network.
  Without `VF_DEMO` there are no default accounts; the first administrator is created in the browser on first start or
  with `python -m vfactory create-admin`.
- **The simulated plant's protocol servers have no authentication.** The OPC UA server, the Modbus TCP servers and the
  embedded MQTT broker accept anonymous clients, and some tags are writable (that is the point of virtual
  commissioning). They are meant for labs and test benches. Do not publish these ports beyond a trusted network, and
  never connect them to a real plant network without segmentation. `docker/compose.production.yml` publishes them on
  `127.0.0.1` only.
- **HTTPS.** HoneyFactory serves plain HTTP. Put it behind a reverse proxy with TLS when it is reachable beyond a
  trusted network.
- **AI features.** When you configure a model endpoint, the assistant and the AI tutor send prompts that contain model
  and plant data (scene, signals, student answers) to that endpoint. Use an endpoint you trust, or a self-hosted
  model. AI features are off until base URL, model and key are all set.
- **Assignment packages.** A self-hosted server re-scores every `.vfhw` package submitted from a desktop client and
  ignores the score the client reports; report any way to make it accept a forged score. In SaaS mode the server
  does not run plants, so packages are recorded with the client's score and marked `verified=false` (documented, not
  a vulnerability).
- **Licence files.** Licences are verified offline against the public keys in `vfactory/tenancy/license_keys.py`.
  The signing private key is never part of the repository or of any build.
- **Secrets.** Keep model API keys, licence keys and account passwords out of the repository. Use environment
  variables or the git-ignored `config/llm.local.json`.
