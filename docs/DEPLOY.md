# Putting the press on your domain

Target: **`book.carolanne.link`** (a subdomain — the simplest setup).
`carolanne.link` uses Vercel's nameservers, and `book` is currently only
covered by a wildcard that serves a 404, so the name is free to claim.
Adjust names for any other domain.

Vercel itself can't run this app (builds are long-running Python
processes needing WeasyPrint), so the app runs on **Fly.io** and the
subdomain points at it. The repo already contains everything: the
`Dockerfile`, `fly.toml`, and a GitHub Actions workflow that performs the
whole deployment.

## One-time setup (the only human steps)

1. **Create a Fly.io account** at <https://fly.io> (it asks for a card;
   this app scales to zero when idle and costs at most a few dollars a
   month, usually cents).

2. **Make a deploy token**: Fly dashboard → *Tokens* (or
   `fly tokens create deploy`). Copy it.

3. **Add repository secrets** on GitHub
   (`carolannejiang/bookformatter` → Settings → Secrets and variables →
   Actions → *New repository secret*):
   - `FLY_API_TOKEN` — the token from step 2 (required)
   - `BOOKFORMATTER_PASSCODE` — any phrase; visitors must type it to run
     builds (optional but recommended — the press has no accounts)

4. **Run the workflow**: Actions tab → *Deploy to Fly.io* → *Run
   workflow*. It creates the app (`carolanne-bookpress`), sets the
   passcode, deploys, and requests the certificate for
   `book.carolanne.link`. (If the app name is already taken on Fly,
   change it in `fly.toml` and in `.github/workflows/deploy.yml`, then
   rerun.)

5. **Add the DNS record** in Vercel (dashboard → *Domains* →
   `carolanne.link` → *DNS Records*):

   | Type  | Name   | Value                          |
   |-------|--------|--------------------------------|
   | CNAME | `book` | `carolanne-bookpress.fly.dev.` |

   The explicit record overrides the wildcard for `book`. Fly notices the
   DNS, finishes the Let's Encrypt certificate automatically (usually
   within a few minutes), and `https://book.carolanne.link` is live.

After that, every push to `main` redeploys automatically, and the
workflow can be rerun manually any time.

## Serving under a path instead (`carolanne.link/book`)

Also supported. Deploy the same app with the base-path env set
(`fly secrets set BOOKFORMATTER_BASE_PATH=/book` or the env var on any
host), then add rewrites to the Vercel project that serves the domain:

```json
{
  "rewrites": [
    { "source": "/book", "destination": "https://carolanne-bookpress.fly.dev/book" },
    { "source": "/book/:path*", "destination": "https://carolanne-bookpress.fly.dev/book/:path*" }
  ]
}
```

## Other hosts

Any Docker host works — Railway and Render can deploy this repo directly;
set `BOOKFORMATTER_PUBLIC=1` (and optionally `BOOKFORMATTER_PASSCODE`,
`BOOKFORMATTER_BASE_PATH`) in their dashboards. On your own VPS:

```bash
BOOKFORMATTER_PUBLIC=1 BOOKFORMATTER_PASSCODE=... \
    bookformatter-web --host 127.0.0.1 --port 8080 --no-browser
```

behind Caddy (`book.carolanne.link { reverse_proxy 127.0.0.1:8080 }`) or
nginx.

## What public mode does

`BOOKFORMATTER_PUBLIC=1` (default in the Docker image) turns on:

- **SSRF guard** — user-submitted URLs that resolve to private/internal
  addresses (localhost, 10.x, 192.168.x, 169.254.x, …) are refused, on
  every redirect hop, so visitors can't use the server to probe its
  network.
- **Rate limiting** — 6 builds per 15 minutes per client IP (reads
  `X-Forwarded-For` when behind a proxy).
- Existing caps apply everywhere: 100 MB request body, 100 inputs per
  build, 20 MB per fetched resource, 2 concurrent builds (others queue),
  20 retained jobs.

`BOOKFORMATTER_PASSCODE` adds a passcode field to the page; builds
without the right passcode are rejected.

Honest limitations of the hosted setup: jobs live in memory (a restart
forgets in-flight builds), TLS comes from the platform (Fly/Vercel), and
DNS-rebinding SSRF is out of scope. For a personal press behind a
passcode, that's a reasonable trade.
