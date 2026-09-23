# authelia

Single sign-on and TOTP two-factor authentication for every proxied service.

## What

Authelia is the authentication gate that sits behind Traefik. When a request
hits a protected route, Traefik forward-auths it to Authelia; Authelia either
allows it (valid session) or redirects the browser to a login portal. One login
grants access to every subdomain (SSO), and admin surfaces can additionally
require a second factor.

## Why

- **One identity, many services.** The session cookie is scoped to the parent
  domain, so authenticating once at `auth.example.com` authorizes every
  `*.example.com` service without a second login.
- **Policy per route, not per app.** Access control is expressed centrally as
  ordered rules (`bypass` / `one_factor` / `two_factor`) rather than relying on
  each backend's own auth. Public services bypass; admin panels demand 2FA.
- **File backend, no external database required.** The default uses a file user
  store and local SQLite storage, production-capable for a single instance,
  with Redis session storage and SQL storage commented in for scaling out.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Authelia service on the shared `proxy` network |
| `config/configuration.yml` | Main config: TOTP, access rules, session, storage |
| `config/users_database.yml.example` | User + argon2 hash template |
| `.env.example` | Domain + the three required secret values |

## Usage

```bash
cp .env.example .env
# generate each secret:  openssl rand -hex 64
$EDITOR .env

# create the user database from the template
cp config/users_database.yml.example config/users_database.yml

# generate an argon2id password hash and paste it into users_database.yml
docker run --rm authelia/authelia:4.39.28 \
  authelia crypto hash generate argon2 --password 'your-password'

docker compose up -d
```

Then browse to any protected service, you will be redirected to
`auth.example.com`. On first login, enroll TOTP (scan the QR with an
authenticator app) to satisfy `two_factor` rules.

Tested on Docker with a generated password hash and throwaway secrets: the
container went healthy and `/api/health` returned `OK`. Fixed during that
test: the healthcheck called an `authelia healthcheck` subcommand that does
not exist, and the JWT secret now uses its 4.38+ variable name. Not tested
here: a login through Traefik.

## Integration

- **Traefik**, the `traefik` folder defines an `authelia@file` middleware
  (and a `secured@file` chain) that forward-auths to this container's
  `/api/verify` endpoint on port 9091. Both must share the external `proxy`
  network. Attach the middleware to any router you want protected.
- **Access-control example**, in `configuration.yml`, `public.example.com` is
  `bypass` (open), `traefik.example.com` / `admin.example.com` are `two_factor`
  and restricted to `group:admins`, and all other `*.example.com` routes fall
  through to `one_factor`. Rules are first-match, top to bottom.
- **Do not** put the Authelia portal itself behind the auth middleware, that
  creates a redirect loop. Its own router is intentionally unprotected.
