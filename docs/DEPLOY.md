# Putting the press on your domain

Target: **`book.carolanne.link`**. The domain already lives on Vercel
(Vercel nameservers), and `book` is currently only covered by a wildcard
that serves a 404 — free to claim. Adjust names for any other domain.

## Option A — All on Vercel (no new accounts)

The repo contains a serverless adapter (`api/index.py`, `vercel.json`,
`bookformatter/serverless.py`): the same press, built synchronously per
request. EPUBs are identical to the local tool. PDFs are delivered as
**print HTML** — open the download and File → Print → Save as PDF
(Chrome/Edge give correct trim, margins, and page numbers; server-side
PDF needs system libraries Vercel's Python functions don't have — see
Option B if you want that).

Setup, all in the Vercel dashboard (~5 minutes):

1. **Import the repo**: <https://vercel.com/new> → Import
   `carolannejiang/bookformatter`. Framework preset "Other", no build
   command, defaults as detected → **Deploy**. (The production branch is
   the repo's default branch; every push to it redeploys automatically.)

2. **Set the passcode** (recommended — builds are real compute on your
   account): Project → Settings → Environment Variables →
   `BOOKFORMATTER_PASSCODE` = a phrase you like → save, then Deployments
   → ⋯ on the latest → Redeploy so it takes effect.

3. **Attach the subdomain**: Project → Settings → Domains → add
   `book.carolanne.link`. Because the domain is on Vercel DNS in the same
   account, Vercel configures the record and certificate itself —
   no manual DNS.

That's it: `https://book.carolanne.link` is live.

Hosted limits to know about: each build must finish inside the function's
window (60 s as configured in `vercel.json`; on plans with Fluid compute
you can raise `maxDuration` to 300) — a huge blog with "fetch full posts"
may need a smaller "max posts" or the CLI instead. Request bodies
(uploads) cap at ~4.5 MB on Vercel. Nothing is stored server-side; the
book streams straight back. The SSRF guard is always on, and Vercel's
Hobby plan is for non-commercial use.

## Option B — Fly.io (adds server-rendered WeasyPrint PDFs; currently serving book.carolanne.link)

For one-click, full-fidelity print PDFs (running heads, TOC page numbers,
recto chapter openers), run the container on Fly and point the subdomain
there instead. The repo ships `Dockerfile`, `fly.toml`, and a GitHub
Actions workflow (`.github/workflows/deploy.yml`) that does the whole
deployment.

1. Create a Fly.io account, make a deploy token (dashboard → Tokens).
2. Add GitHub repo secrets: `FLY_API_TOKEN` (required),
   `BOOKFORMATTER_PASSCODE` (recommended).
3. Run the *Deploy to Fly.io* workflow from the Actions tab. It creates
   app `carolanne-bookpress`, deploys, and requests the certificate for
   `book.carolanne.link`.
4. DNS: in Vercel → Domains → `carolanne.link` → DNS Records, add
   `CNAME book → carolanne-bookpress.fly.dev.` (an explicit record
   overrides the wildcard).

Cost: the machine stops when idle; typically cents per month.

Both options can coexist (e.g. Vercel at `book.` and Fly at `press.`),
and switching later is just moving the DNS/domain attachment.

## Serving under a path instead (`carolanne.link/book`)

Supported by the local/Fly server via `BOOKFORMATTER_BASE_PATH=/book`,
proxied with rewrites from the Vercel project that serves the domain:

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

`BOOKFORMATTER_PUBLIC=1` (always on in the serverless function; default
in the Docker image) turns on:

- **SSRF guard** — user-submitted URLs that resolve to private/internal
  addresses (localhost, 10.x, 192.168.x, 169.254.x, …) are refused, on
  every redirect hop, so visitors can't use the server to probe its
  network.
- **Rate limiting** (long-running server only) — 6 builds per 15 minutes
  per client IP (reads `X-Forwarded-For` behind a proxy). The serverless
  function relies on the passcode instead.
- Caps everywhere: 100 inputs per build, 20 MB per fetched resource,
  request-body limits, 2 concurrent builds on the long-running server.

`BOOKFORMATTER_PASSCODE` adds a passcode field to the page; builds
without the right passcode are rejected.

Honest limitations of hosting: long-running-server jobs live in memory (a
restart forgets in-flight builds), TLS comes from the platform, and
DNS-rebinding SSRF is out of scope. For a personal press behind a
passcode, that's a reasonable trade.
