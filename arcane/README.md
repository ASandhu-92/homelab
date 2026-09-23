# arcane

Arcane as the Docker manager for the lab: one manager on the main Docker
host, an edge agent on every other host.

## What

Arcane is a web UI for containers, images, volumes, networks and compose
projects. The manager controls its own host's Docker daemon directly and
discovers every compose project under one directory. Other hosts run a small
agent that connects out to the manager, so the whole fleet shows up as a list
of environments in one UI.

I moved to it from Dockhand. The compose files stay plain files on disk, in
one folder per project; Arcane reads and runs them, it does not own them.

## Why

- **Plain compose on disk.** Projects are ordinary `compose.yaml` folders
  under `STACKS_DIR`. If Arcane is down or removed, `docker compose` still
  works on every one of them.
- **Edge agents, no inbound ports.** Each agent dials the manager, so no host
  needs a listening port or a firewall rule for management.
- **The identity mount.** The stacks directory is mounted at the same path
  inside the container as on the host. Arcane runs compose against the host
  daemon, so a relative bind mount in a stack (`./config:/config`) is
  resolved on the host. With a different path inside the container, every
  stack that uses one breaks.

### Things that surprised me

- **The built-in local environment cannot be renamed.** Its name and URL are
  read-only in the UI; every other environment renames inline. Re-adding the
  manager host as an edge agent to get a better name is rejected. Live with
  the name.
- **"Regenerate API Key" is revocation, not rotation.** Each environment has
  one token, shown once when you create it. Pressing Regenerate invalidates
  the current token at once, and that host goes Offline until the new token
  is written to the agent's `secrets/agent_token` file and the agent is
  restarted. Store the token when you first see it.
- **Do not paste the UI's generated agent config.** It fills
  `MANAGER_API_URL` with the public URL. If that URL has an SSO middleware in
  front, the agent gets a login redirect and the environment stays Offline.
  Point agents at the manager's LAN address instead (`agent/compose.yaml`).
- **Directories are not projects.** A folder with a shell script or nothing
  in it is not a project. Arcane counts folders that contain a compose file.
- **Keep the reverse proxy out of it.** I do not let Arcane manage the Traefik
  project. If one click can stop the proxy, one click can take down every
  way into the UI that would let you start it again.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Manager `v2.8.0`: identity-mounted stacks dir, secrets from files, exec-form healthcheck (the image is distroless) |
| `.env.example` | `APP_URL`, `STACKS_DIR`, and how to create the two secret files |
| `agent/compose.yaml` | Edge agent for every other host, token from a file |
| `agent/.env.example` | The manager's LAN URL and the stacks dir for that host |

## Usage

Manager:

```bash
cp .env.example .env && $EDITOR .env
mkdir -p secrets
openssl rand -hex 32 | tr -d '\n' > secrets/encryption_key
openssl rand -hex 32 | tr -d '\n' > secrets/jwt_secret
chmod 600 secrets/*
docker compose up -d
```

Then route `APP_URL` through Traefik with SSO in front.

Each additional host: create the environment in the UI, copy the token, then

```bash
cd agent
cp .env.example .env && $EDITOR .env
mkdir -p secrets && printf %s '<token from the UI>' > secrets/agent_token
chmod 600 secrets/agent_token
docker compose up -d
```

Status "Standby" on an agent is normal: it is connected and idle.

Tested on Docker (published port removed, throwaway secrets, `STACKS_DIR`
pointed at a temp folder with one demo project): the manager went healthy
through its own `./arcane health` check, `/api/health` returned `UP`, and the
log showed the demo project discovered from the filesystem. Not tested here:
pairing an agent (it needs an environment created in the UI).

## Integration

- **Traefik + Authelia**, route the manager's hostname through both. Agents
  never use that hostname.
- **Backups**, `./data` holds the SQLite database, settings and environment
  records. It is a bind mount so the host backup job (see `kopia`) picks it
  up.
- **Secrets**, keep `secrets/` out of the stacks directory if the stacks
  directory is a git repository.
