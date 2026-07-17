# Runbook — Publish the rendering showcase to Cloudflare Pages

> **Two stacks, two Pages projects.** This runbook covers the **asciiball**
> showcase → `asciiball.pages.dev` (from `asciiball/docs/showcase.html`). The
> **glassball** web UI is a separate project, `glassball.pages.dev`, built from
> `glassball/docs/glassball.html` — deploy it with the identical Wrangler flow
> below, just swap `--project-name=glassball` and the staged directory. The old
> single `ascii-planets` project was deleted on the 2026-07-16 rename.

Publish the self-contained `asciiball/docs/showcase.html` to a free, rendered
public URL **without making this repo public**. End result:

> **https://asciiball.pages.dev/**

- **Time:** ~5–10 min (first time), ~30 s per redeploy.
- **Cost:** $0 — Cloudflare Pages free tier (unlimited bandwidth/requests, no card).
- **Privacy:** only the single uploaded HTML file becomes public. The GitHub
  repo, its code, and history stay private.
- **Source of truth:** the page is generated from this repo by
  `scripts/build_showcase.py`; Cloudflare only ever gets the built HTML. Never
  hand-edit what you upload.

---

## ✅ Deployed (2026-07-09)

**Live: https://asciiball.pages.dev/** — returns `200 text/html`, showcase
renders (Earth dark/light panels). Deployed via Wrangler CLI (Path B).

- [x] Redeployed 2026-07-09 after doubling the rotation frame count (24→48,
      90ms interval) for smoother playback at the same rotation speed — see
      commit `07aab79`.
- [x] Redeployed 2026-07-09 after regenerating the Moon's maria/crater masks at
      LROC-native 2048×1024 (fixed the showcase's tiling artifact + added a
      1×/0.5×/0.25× speed toggle) — see commit `ae727a3` — then again after
      fixing panel circularity (`line-height:1.3`; webfont monospace rendered
      flatter than the assumed `--aspect 2.3`, so discs were oblate ovals with
      poles reading as cut off) — see commit `bb610d0`. Root propagation lagged
      the first of these two by a few minutes; confirmed live by diffing the
      production response against the committed HTML (byte-identical).
- [x] Redeployed 2026-07-09 for **v0.2.0** — the engine now auto-detects 24-bit
      truecolor (`--color-depth`, `detect_truecolor`) for a smoother depth
      gradient, and each showcase panel is twinned: the 256-color and truecolor
      renders spin side by side off the same geometry.
- [x] Redeployed 2026-07-17 after the **cover refactor** — the page now opens on a
      live, ambient auto-spinning Earth hero (`hero_globe()`, `HERO_R=18`, its own
      coarser `HERO_ANGLES`, no controls) beside a short lede + four trimmed cue
      chips, so a rendered globe leads before any explanation. Verified live at
      `https://asciiball.pages.dev/` (HTTP 200, `heroGlobe` present). Redeployed
      again same day after doubling the hero's baked frames (`HERO_FRAMES` 32→64)
      at the fixed 90ms tick — twice as smooth and half the angular speed (a
      5760ms revolution) in one knob.

- [x] Cloudflare account (personal). The account email + account id are
      deliberately kept out of this repo — store them in `~/env-secrets/` (or your
      local notes). `npx wrangler login` picks up the authenticated account; the
      account id also surfaces in the Cloudflare dashboard URL and `wrangler whoami`.
- [x] **Node 22 via nvm, default** (`node --version` = v22.23.1; nvm `default`
      alias = 22, confirmed for fresh login shells).
- [x] Page built + staged at `tmp/pages-site/index.html`.
- [x] `npx wrangler login` (OAuth, browser) — authenticated.
- [x] **Gotcha (wrangler v4):** `pages deploy` no longer auto-creates the project.
      Had to run `npx wrangler pages project create asciiball
      --production-branch=main` first, *then* deploy.
- [x] `npx wrangler pages deploy tmp/pages-site --project-name=asciiball --branch=main --commit-dirty=true`
- [x] Verified URL returns `200 text/html`; README links already target this URL
      (deployed under the exact `asciiball` name), so no README edit needed.

For redeploys after a shading/page change, see §5.

---

## 0. Prerequisites

- A Cloudflare account (free): <https://dash.cloudflare.com/sign-up>.
- This repo checked out, able to run `python scripts/build_showcase.py`.
- For the CLI path (recommended): **Node.js ≥ 22**. The current `wrangler` (v4)
  hard-requires Node 22+; on Node 18–21 it refuses to run. No Node at all? Use the
  Dashboard path instead — no CLI needed.

### Node 22 via nvm (one-time)

If `node --version` is below 22, install it with [nvm](https://github.com/nvm-sh/nvm):

```bash
nvm install 22
nvm alias default 22      # make 22 the default for future shells
node --version            # expect v22.x
```

> **New-shell gotcha:** an already-running/inherited shell may keep an older Node
> on its `PATH` even after `nvm alias default 22`. If `node --version` isn't 22 in
> a session, activate it explicitly before any `wrangler` command:
> ```bash
> nvm use 22 && hash -r    # hash -r clears bash's cached path to the old node
> ```
>
> **Can't/don't want to upgrade Node?** Pin the last Node-18/20-compatible
> Wrangler instead — replace `wrangler` with `wrangler@3` in every command below
> (e.g. `npx --yes wrangler@3 pages deploy …`).

> **Authentication note:** creating the project and deploying happen under *your*
> Cloudflare login (`wrangler login` opens a browser). These steps run under your
> account and can't be done on your behalf without a scoped API token.

---

## 1. Build the page and stage it (both paths)

Run from the repo root. `tmp/` is gitignored, so we stage the upload there. The
page is copied to `index.html` so it serves at the site root.

```bash
cd /path/to/asciiball
python scripts/build_showcase.py            # (re)writes docs/showcase.html
rm -rf tmp/pages-site && mkdir -p tmp/pages-site
cp docs/showcase.html tmp/pages-site/index.html
```

`tmp/pages-site/` now contains exactly one file: `index.html`.

---

## 2a. Path A — Cloudflare Dashboard (no CLI, quickest one-off)

1. Log in to <https://dash.cloudflare.com> → **Workers & Pages** → **Create** →
   **Pages** → **Upload assets**.
2. **Project name:** `asciiball` → **Create project**.
   - If that name is taken (it's global across all Cloudflare accounts), pick
     another, e.g. `asciiball-binlecode`. Your URL becomes
     `https://<name>.pages.dev/` — note it for step 4.
3. Drag the **`tmp/pages-site` folder** (or just `index.html`) into the upload
   area → **Deploy site**.
4. Wait ~10–30 s. Your site is live at **https://asciiball.pages.dev/**.

To update later: open the project → **Create new deployment** → upload the
rebuilt folder.

---

## 2b. Path B — Wrangler CLI (recommended, repeatable)

1. **Log in** (one-time; OAuth via browser):
   ```bash
   npx wrangler login
   ```
   - The browser often does **not** auto-open (observed on macOS/zsh). Wrangler
     prints `Opening a link in your default browser: https://dash.cloudflare.com/oauth2/auth?...`
     — copy that whole URL and open it manually. Make sure that browser is
     already signed in to the right Cloudflare account first.
   - After you click **Allow**, the page redirects to `localhost:8976` and the CLI
     prints `Successfully logged in.` Confirm with `npx wrangler whoami` — it
     should show your account email + id.
2. **Create the project** (first time only — wrangler v4 does **not**
   auto-create it on deploy; a bare `pages deploy` fails with *"The Pages project
   … does not exist"*):
   ```bash
   npx wrangler pages project create asciiball --production-branch=main
   ```
   - If the name is taken (global across all Cloudflare accounts), pick another
     and update the README links in §4 to match.
3. **Deploy:**
   ```bash
   npx wrangler pages deploy tmp/pages-site \
     --project-name=asciiball \
     --branch=main \
     --commit-dirty=true
   ```
   - `--branch=main` marks this a **production** deploy (must match the project's
     production branch from step 2), so it lands on the root
     `asciiball.pages.dev`. Any other branch gets a preview URL like
     `<hash>.asciiball.pages.dev`.
4. Wrangler prints the production URL plus a unique per-deploy URL.

> Prefer a global install? `npm i -g wrangler` then drop the `npx` prefix.

---

## 3. Verify

```bash
curl -sS -o /dev/null -w "%{http_code} %{content_type}\n" https://asciiball.pages.dev/
```

Expect `200 text/html`. Then open it in a browser — you should see the Earth
panels (dark and light) rendered, not raw HTML source.

---

## 4. Point the README at the live URL

The README's two showcase links already target
`https://asciiball.pages.dev/`. Once step 3 passes, they resolve.

- If you deployed under a **different project name**, update both links in
  `README.md` (search for `asciiball.pages.dev`) to your actual
  `<name>.pages.dev` URL, then commit.

---

## 5. Redeploy after changing the shading or the page

Whenever `docs/showcase.html` is regenerated (e.g. after a shade-ramp
change — see the `showcase` skill), republish:

```bash
python scripts/build_showcase.py
rm -rf tmp/pages-site && mkdir -p tmp/pages-site
cp docs/showcase.html tmp/pages-site/index.html
npx wrangler pages deploy tmp/pages-site --project-name=asciiball --branch=main --commit-dirty=true
```

Optional: save these four lines as `scripts/deploy_showcase.sh` so a redeploy is
one command. (It still requires you to be logged in via `wrangler login`.)

---

## 6. Rollback

Dashboard → your project → **Deployments** → choose a previous deployment →
**Rollback to this deployment**. Cloudflare retains deployment history, so you
can revert instantly without rebuilding.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Create fails: name unavailable | The `<name>.pages.dev` subdomain is global. Choose a unique project name; update README links to match. |
| Root URL shows old/blank content | Your deploy went to a *preview* branch. Redeploy with `--branch=main` (must equal the project's production branch). |
| `404` / `HTTP 000` right after first deploy | New-project DNS can take up to a minute — retry. Confirm `index.html` is at the uploaded folder's root. |
| `wrangler: command not found` | Use `npx wrangler …`, or install Node ≥ 22 (wrangler v4 requires it). |
| Deploy fails: *"The Pages project … does not exist"* | Wrangler v4 no longer auto-creates the project on deploy. Run `npx wrangler pages project create asciiball --production-branch=main` first (§2b step 2), then redeploy. |
| Login prints a URL but no browser opens | Expected on many terminals — copy the printed `https://dash.cloudflare.com/oauth2/auth?...` URL and open it manually. The CLI keeps a local server on `localhost:8976` waiting for the redirect. |
| Login won't open a browser (headless/SSH) | Run `npx wrangler login` on a machine with a browser, **or** create a Cloudflare API token (Pages: Edit) and export `CLOUDFLARE_API_TOKEN` before deploying. |
| Page renders but styling looks off | Make sure you uploaded the file straight from `scripts/build_showcase.py` output — it's self-contained (inline CSS, no assets); don't strip or reformat it. |

---

## Recap — limits & privacy

- **Free plan:** unlimited bandwidth & static requests; 500 builds/month (Direct
  Upload uses **0** builds); 25 MiB max file size; 20,000 files/deploy. This page
  is **1 file, ~9.2 MB raw** (two full rotations baked in per panel — 256 + 24-bit
  — as scrubbable frames; ~0.7 MB gzip/brotli over the wire) — still well under the
  25 MiB/file limit.
- **Private repo stays private.** Only the single HTML at the `pages.dev` URL is
  public. If you later want it under your own domain, attach a custom domain to
  the project (free to attach; you only pay to own the domain).
