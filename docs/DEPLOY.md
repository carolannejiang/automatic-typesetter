# Putting the website on your own domain

This guide gets bookformatter running at **`carolanne.link/book`** (adjust
the names for any other domain/path).

`carolanne.link` is served by **Vercel**. Vercel hosts static and
serverless sites, so it can't run this app directly (builds are
long-running Python processes that need WeasyPrint/Chromium). The standard
pattern instead:

1. run the app in a small container host (Fly.io shown below), and
2. add a **rewrite** to the Vercel project so `/book` proxies to it.

Visitors only ever see `carolanne.link/book` — the app host is invisible.

## 1 · Run the app on Fly.io (~5 minutes)

The repo already contains the `Dockerfile`. From the repo root:

```bash
# install flyctl once: https://fly.io/docs/flyctl/install/
fly launch --no-deploy --name carolanne-bookformatter   # accept defaults; creates fly.toml
fly secrets set BOOKFORMATTER_BASE_PATH=/book
# optional but recommended — only people with the passcode can run builds:
fly secrets set BOOKFORMATTER_PASSCODE=some-secret-words
fly deploy
```

Check it works at `https://carolanne-bookformatter.fly.dev/book/`.

Fly's smallest machine (shared-cpu-1x, 256 MB) is fine; add
`--vm-memory 512` if large feed builds get killed. Any Docker host works
the same way (Railway and Render can deploy this repo directly — set the
env vars in their dashboard).

## 2 · Add the rewrite on Vercel

In the Vercel project that serves `carolanne.link`, add to `vercel.json`
(create the file at the project root if it doesn't exist):

```json
{
  "rewrites": [
    { "source": "/book", "destination": "https://carolanne-bookformatter.fly.dev/book" },
    { "source": "/book/:path*", "destination": "https://carolanne-bookformatter.fly.dev/book/:path*" }
  ]
}
```

Deploy the Vercel project. Done: `https://carolanne.link/book` now serves
the press. (If the site redirects apex → `www`, the path follows
automatically: `www.carolanne.link/book`.)

## Alternatives to the Vercel rewrite

**Your own server (VPS) with Caddy** — if you ever move the domain to a
box you control:

```caddyfile
carolanne.link {
    handle /book* {
        reverse_proxy 127.0.0.1:8080
    }
    # ... the rest of the site
}
```

**nginx:**

```nginx
location = /book { return 301 /book/; }
location /book/ { proxy_pass http://127.0.0.1:8080; proxy_set_header X-Forwarded-For $remote_addr; }
```

Run the app on the box with:

```bash
BOOKFORMATTER_BASE_PATH=/book BOOKFORMATTER_PUBLIC=1 BOOKFORMATTER_PASSCODE=... \
    bookformatter-web --host 127.0.0.1 --port 8080 --no-browser
```

**Subdomain instead of a path** — `book.carolanne.link` is even simpler:
add a CNAME to the app host and skip the base path entirely. Path vs
subdomain is purely cosmetic; everything else stays the same.

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
without the right passcode are rejected. **Recommended** — a book build
is real CPU work, and this app has no accounts or billing. Don't run a
passcode-less instance anywhere heavily trafficked.

Honest limitations of the hosted setup: jobs live in memory (a restart
forgets in-flight builds), there's no HTTPS termination in the app itself
(Fly/Vercel provide it), and DNS-rebinding SSRF is out of scope. For a
personal press behind a passcode, that's a reasonable trade.
