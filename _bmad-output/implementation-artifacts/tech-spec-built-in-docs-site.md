---
title: 'Built-in Docs/Help Site'
slug: 'built-in-docs-site'
created: '2026-06-07'
status: 'Completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack:
  - 'Python 3.14 / Flask (app factory, blueprints)'
  - 'Jinja2 (templates + runtime placeholder rendering)'
  - 'Markdown (python-markdown) — NEW runtime dependency'
  - 'mkdocs + mkdocs-material + mkdocs-macros-plugin (CI docs build)'
  - 'tomllib (stdlib) for runtime version read from pyproject.toml'
files_to_modify:
  - 'esb/views/docs.py (NEW)'
  - 'esb/views/__init__.py'
  - 'esb/services/docs_service.py (NEW)'
  - 'esb/templates/docs/page.html (NEW)'
  - 'esb/templates/docs/about.html (NEW)'
  - 'esb/templates/docs/_subnav.html (NEW)'
  - 'esb/templates/base.html'
  - 'esb/templates/base_public.html'
  - 'esb/templates/components/_footer.html'
  - 'esb/static/css/app.css'
  - 'docs/staff.md'
  - 'docs/administrators.md'
  - 'mkdocs.yml'
  - '.github/workflows/docs.yml'
  - '.github/workflows/ci.yml'
  - 'requirements.txt'
  - 'requirements-dev.txt'
  - 'requirements-docs.txt (NEW)'
  - 'pyproject.toml'
  - 'tests/test_views/test_docs_views.py (NEW)'
  - 'docs/images/*.png (regenerated)'
code_patterns:
  - 'Blueprint with declarative url_prefix, registered in esb/views/__init__.py register_blueprints()'
  - 'Service layer: business logic in esb/services/, views delegate'
  - 'Templates extend base.html (authed) or base_public.html (public); blocks: title, content'
  - 'Lazy service imports inside route handlers'
test_patterns:
  - 'pytest, in-memory SQLite via TestingConfig, CSRF disabled'
  - 'Unauthenticated routes tested with client fixture; assert status_code + response.data content'
  - 'Per-test config override via app.config[...] or monkeypatch'
---

# Tech-Spec: Built-in Docs/Help Site

**Created:** 2026-06-07

**GitHub Issue:** [#58 — Built-in docs/help site](https://github.com/jantman/equipment-status-board/issues/58)

## Overview

### Problem Statement

ESB documentation lives only on the project's GitHub Pages site, which is generic — it can't reference a given installation's actual URLs, Slack channel names, or other deployment-specific values, and there's no way to discover it from inside the running app.

### Solution

Serve the existing `docs/*.md` markdown files at a public `/docs/` route inside the app, rendered server-side with installation-specific config values interpolated, plus an About page (version, GitHub/license/issues/online-docs links). Add a docs link to the header of every non-kiosk page.

### Scope

**In Scope:**

- New public `/docs/` blueprint section: Home, Members, Technicians, Staff, Administrators guides + About page
- Runtime markdown rendering with placeholder interpolation (initial set: the Slack oops channel; mechanism extensible)
- Docs link: navbar item in `base.html`, footer link on `base_public.html` pages via the shared footer partial (kiosk excluded)
- About page: running version, GitHub repo link, license info, GH Pages docs link, report-an-issue link
- Ensuring `docs/*.md` (with any placeholder syntax added) still renders sensibly on the GitHub Pages site
- Shipping the `docs/` content in the Docker image

**Out of Scope:**

- Changing the GH Pages site theme/structure or the mkdocs workflow beyond what placeholder compatibility requires
- Docs search functionality
- Kiosk views
- Editing/CMS capability for docs content

## Context for Development

### Codebase Patterns

- **Blueprints:** Defined in `esb/views/<name>.py` with declarative `url_prefix` (e.g., `public_bp = Blueprint('public', __name__, url_prefix='/public')` at `esb/views/public.py:15`), registered centrally in `esb/views/__init__.py:10-16` via `register_blueprints(app)`, which is called from `create_app()` (`esb/__init__.py:73-75`).
- **Service layer:** Views never contain business logic; they lazily import from `esb/services/` inside route handlers (pattern throughout `esb/views/public.py`).
- **Templates:** Three bases. `base.html` — full Bootstrap navbar (lines 13-63) with role-conditional items (`current_user.is_authenticated` / `role == 'staff'` checks at lines 24-46). `base_public.html` — minimal template, no nav/header, flash messages + `{% block content %}`. **ALL THREE bases include the same footer partial** `components/_footer.html` (copyright + GitHub repo link + MIT license link): `base_public.html:17`, `base_kiosk.html:17`, and `base.html:70`. **CAUTION:** any docs link added unconditionally to that partial would leak onto kiosk views — it must be flag-guarded, with only `base_public.html` setting the flag (authed pages get the docs link via the navbar instead; their footer intentionally omits it). Public templates live in `esb/templates/public/` and use blocks `title`, `content`, optional `extra_css`/`extra_js`.
- **Context processors:** `create_app()` registers `inject_current_year` and `inject_repair_constants` (`esb/__init__.py:83-89`) — precedent for injecting template globals.
- **Jinja filters:** registered in `esb/utils/filters.py:99-105` (`format_date`, `filesize`, etc.).
- **Markdown:** No markdown rendering exists anywhere in the app today. TRAP: `import markdown` already works in every dev/CI environment — `mkdocs` (in `requirements-dev.txt`) pulls in python-markdown *transitively* — but the production Docker image installs only `requirements.txt`, which has no markdown library. Code and tests importing `markdown` therefore pass everywhere EXCEPT production unless `Markdown` is added to `requirements.txt` (Task 1) — do not skip that line because imports "already work". Note: dev tooling is installed from `requirements-dev.txt` (`make setup` → Makefile line 8; `ci.yml` lines 30/44) — the pyproject `[project.optional-dependencies] dev` extras are never pip-installed by anything; `requirements-dev.txt` is the operative file.
- **Tests:** `tests/test_views/test_public_views.py` is the model — class-per-view (`TestStatusDashboardView`), unauthenticated `client` fixture, factory fixtures (`make_area`, `make_equipment`), assertions on `response.status_code` and `response.data` content (bytes or decoded + regex).

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/views/public.py` | Model for a public, no-auth blueprint (routes, lazy service imports) |
| `esb/views/__init__.py` | `register_blueprints()` — add new `docs_bp` here |
| `esb/__init__.py` | App factory: blueprint registration, context processors, filter registration |
| `esb/templates/base.html` | Authed navbar (lines 13-63) — add Docs nav link |
| `esb/templates/base_public.html` | Public base — has existing footer include (line 17); docs link goes there via flag |
| `esb/templates/components/_footer.html` | Shared footer partial used by ALL THREE bases (`base.html:70`, `base_public.html:17`, `base_kiosk.html:17`) — gains conditional docs link |
| `esb/templates/base_kiosk.html` | Kiosk base — NOT touched; includes `_footer.html` WITHOUT the docs-link flag |
| `Makefile` (line 8) + `requirements-dev.txt` | Dev deps install path — `mkdocs-macros-plugin` must go in `requirements-dev.txt` |
| `esb/config.py` | Config values for interpolation (`SLACK_OOPS_CHANNEL` line 48, `ESB_BASE_URL` line 34) |
| `docs/*.md` | Source content: index, members, technicians, staff, administrators (+ `docs/images/`) |
| `mkdocs.yml` | GH Pages nav + markdown_extensions; add macros plugin + extra vars |
| `.github/workflows/docs.yml` | Pages deploy workflow (push to main path-filtered to `docs/**`+`mkdocs.yml`, + workflow_dispatch; `pages` concurrency group) — changes: install from `requirements-docs.txt`, align Python to 3.14, extend paths filter |
| `.github/workflows/ci.yml` | Runs on every PR — gains the `docs-build` job (`mkdocs build --strict` from `requirements-docs.txt`) |
| `requirements-docs.txt` (NEW) | Single source of truth for the docs toolchain, shared by both workflows + `requirements-dev.txt` |
| `Dockerfile` | `COPY . .` (line 23) already ships `docs/`; app NOT pip-installed (version gotcha) |
| `pyproject.toml` | `version = "0.9.0"` (line 3) — runtime source of truth for About page via `tomllib` |
| `LICENSE` | MIT — referenced on About page |
| `tests/conftest.py` | Fixtures: `app`, `client`, factory fixtures |
| `tests/test_views/test_public_views.py` | Test pattern model for public views |

### Technical Decisions

- **Content source:** Single source of truth — render the same `docs/*.md` files used by the mkdocs GitHub Pages site at runtime; ship them in the Docker image (already covered by `COPY . .`). No duplicated content.
- **Access:** Fully public, no login required (matches public status dashboard and QR pages).
- **Guides included:** All five mkdocs-nav pages (Home/index, Members, Technicians, Staff, Administrators) plus About. `manual_testing.md` and `original_requirements_doc.md` are not in the mkdocs nav and are excluded.
- **Placeholder mechanism:** Jinja-style placeholders (e.g., `{{ oops_channel }}`) added to `docs/*.md`, replacing hardcoded installation-specific literals. The GH Pages build gains `mkdocs-macros-plugin` configured with `on_undefined: strict` (IMPORTANT: the plugin's default `on_undefined: keep` silently passes undefined variables through even under `mkdocs build --strict` — strict mode must be set explicitly for the CI drift guard to work) and generic default values under `extra:` in `mkdocs.yml`; the app renders the same placeholders at runtime via Jinja2 with live config values. One source, explicit markers, both renderers fail loudly on drift.
- **Interpolated values (initial set):** exactly ONE placeholder: `oops_channel` ← `SLACK_OOPS_CHANNEL`. (Investigation found no doc text that needs `ESB_BASE_URL` — do not add unused placeholders.) Mechanism is a single mapping dict in the docs service, extensible later. Slack slash command names are fixed in code, not config — they stay literal.
- **Pre-existing Jinja collision (MUST FIX):** `docs/administrators.md:519` contains `docker inspect --format '{{.State.Health.Status}}' ...` inside a fenced bash block. This is a Jinja2 `TemplateSyntaxError` for BOTH the runtime renderer and mkdocs-macros — the fenced block must be wrapped in `{% raw %}` / `{% endraw %}` (Task 7), and the rendered administrators page will legitimately contain the literal text `{{.State.Health.Status}}` in a code block. Tests/ACs therefore check for unrendered *placeholder-style* patterns (`{{ word }}` with identifier content), not bare `{{`.
- **Markdown rendering:** Add `Markdown` (python-markdown) as a runtime dependency. Extensions: `tables`, `fenced_code`, `admonition`, `toc` — the only features actually used by the five guides today. NOTE: `mkdocs.yml` additionally enables `pymdownx.details`, `pymdownx.superfences`, `attr_list`, `md_in_html`, which the runtime renderer does NOT support — if future doc edits adopt those features they will build green on GH Pages but render as garbage at `/docs/` (see Notes). Admonition/toc output needs small CSS to render acceptably under Bootstrap.
- **Link/image rewriting:** At render time, rewrite inter-doc links (`members.md` → `/docs/members`, `staff.md#anchor` → `/docs/staff#anchor`) and image refs (`images/foo.png` → docs image route). Serve `docs/images/` via a dedicated route with path-traversal protection (model: `serve_upload` in `esb/views/public.py:228-243`).
- **Version at runtime:** The Docker image copies source but never pip-installs the package, so `importlib.metadata` will NOT work. Parse `pyproject.toml` with stdlib `tomllib` (cached at first use); display "unknown" if unavailable.
- **About page:** running version, link to GitHub repo, MIT license note + link, link to GH Pages docs site (`https://jantman.github.io/equipment-status-board/`), report-an-issue link (GitHub issues URL). Note: the site-wide `_footer.html` already shows the GitHub repo + MIT license links on every page; the About page repeats them in its body (per the issue) — tests must assert against body-unique markers (version string, issues URL, docs-site URL), not links the footer already satisfies.
- **Footer/header links:** `base.html` navbar gets a "Docs" link (visible to all). For public pages, the docs link goes into the EXISTING `components/_footer.html` partial guarded by a context flag (e.g., `{% if show_docs_link %}`), with `base_public.html` setting the flag via `{% with show_docs_link = true %}` around its include — NOT a second footer element. `base_kiosk.html` and `base.html` include the same partial WITHOUT the flag and are untouched at the footer: kiosk gets no docs link at all (per issue), and authed pages deliberately carry the link in the navbar only — their footer omitting it is intentional, not an oversight.
- **Caching:** Rendered pages are static per-process (content ships with the image; config is fixed at startup) — render-once-and-cache per page is acceptable and avoids per-request markdown parsing.

## Implementation Plan

### Tasks

- [x] Task 1: Add dependencies
  - File: `requirements.txt`
  - Action: Add `Markdown>=3.7` (python-markdown, runtime dependency for server-side rendering). The Dockerfile installs from this file — it is what makes the library available in the image. (Do not skip because `import markdown` already works locally — that's the transitive mkdocs dependency, absent from the production image.)
  - File: `requirements-docs.txt` (NEW)
  - Action: Create with the docs toolchain: `mkdocs>=1.6`, `mkdocs-material>=9.5`, `mkdocs-macros-plugin>=1.0`. Single source of truth for BOTH workflows (PR gate and Pages deploy) so they can't drift apart.
  - File: `requirements-dev.txt`
  - Action: Replace the existing `mkdocs>=1.6` and `mkdocs-material>=9.5` lines with `-r requirements-docs.txt`. This file is what `make setup` (Makefile line 8) and `ci.yml` (lines 30, 44) actually install — pyproject dev extras are installed by nothing.
  - File: `pyproject.toml`
  - Action: Mirror for consistency: add `"Markdown>=3.7"` to `[project] dependencies`; add `"mkdocs-macros-plugin>=1.0"` to `[project.optional-dependencies] dev`.

- [x] Task 2: Create docs service
  - File: `esb/services/docs_service.py` (NEW)
  - Action: Implement the docs rendering service:
    - `DOC_PAGES`: ordered dict mapping slug → `{'file': '<name>.md', 'title': '<nav title>'}` for exactly: `index` → `index.md` / "Home", `members` → `members.md` / "Members Guide", `technicians` → `technicians.md` / "Technicians Guide", `staff` → `staff.md` / "Staff Guide", `administrators` → `administrators.md` / "Administrators Guide". (Mirrors the `nav:` in `mkdocs.yml`. `manual_testing.md` and `original_requirements_doc.md` are deliberately excluded.)
    - `get_docs_dir()`: a FUNCTION (not a module constant — `current_app` raises `RuntimeError` outside an app context at import time) returning `Path(current_app.root_path).parent / 'docs'` (the repo-root `docs/` directory, which `Dockerfile` line 23 `COPY . .` ships into the image at `/app/docs`).
    - `get_placeholder_values()`: returns the interpolation dict from live config: `{'oops_channel': current_app.config['SLACK_OOPS_CHANNEL']}`. Exactly one placeholder initially; this dict is the single extension point for future placeholders. Every key here MUST also exist in `mkdocs.yml extra:`.
    - `render_page(slug)`: returns `(title, html)`; raises `KeyError` for a slug not in `DOC_PAGES` (→ 404 in the view). A slug that IS in `DOC_PAGES` whose file is missing or unreadable must NOT be masked as a 404: let the `OSError` propagate (→ 500) — that's a broken deployment (e.g., a future `.dockerignore` excluding `docs/`), and the fail-loud philosophy applies. No startup-time validation is required; the test suite renders all five pages, which catches a missing file in CI. Pipeline: (1) read the markdown file; (2) render placeholders with `jinja2.Environment(undefined=StrictUndefined).from_string(text).render(**get_placeholder_values())` — StrictUndefined makes a typo'd placeholder fail loudly in tests rather than render `{{ ... }}` to users. The docs honor `{% raw %}` blocks (needed for the docker-inspect example in administrators.md — see Task 7); (3) rewrite links/images in markdown source via regex on link targets: `(<page>.md)` → `(/docs/<slug>)`, `(<page>.md#anchor)` → `(/docs/<slug>#anchor)` (the anchor variant falls out of the same regex — no guide currently uses a cross-page anchor, fine), `(images/<file>)` → `(/docs/images/<file>)` (technically redundant — relative `src` already resolves correctly under the no-trailing-slash `/docs/<slug>` URLs — but kept for explicitness; the rendered-`src` test in Task 10 covers it either way). Rewrite ONLY the five served page names — investigation confirmed no guide links to a non-served `.md` file, so no fallback rule is needed (the no-`.md`-href test in Task 10 will flag any future case and force an explicit decision); (4) convert with `markdown.markdown(text, extensions=['tables', 'fenced_code', 'admonition', 'toc'])` — the only features the five guides use today (see divergence note in Notes section).
    - Per-app render cache: store rendered results in a dict on `app.extensions.setdefault('docs_cache', {})` keyed by slug. Do NOT use a module-level cache — tests create a fresh app per test with different config, and a module-level cache would serve stale interpolations across tests.
    - `_pyproject_path()`: small helper returning the repo-root `pyproject.toml` path — exists so tests can monkeypatch it to exercise the version-fallback path (AC 9).
    - `get_version()`: parse `_pyproject_path()` with stdlib `tomllib`, return `project.version`; cache per-app; return `'unknown'` on any failure (missing file, parse error). NOTE: `importlib.metadata.version()` will NOT work — the Docker image copies source and installs only `requirements.txt`; the `equipment-status-board` package itself is never pip-installed.
    - Module constants for the About page: `GITHUB_URL = 'https://github.com/jantman/equipment-status-board'`, `DOCS_SITE_URL = 'https://jantman.github.io/equipment-status-board/'`, `ISSUES_URL = GITHUB_URL + '/issues'`, `LICENSE_NAME = 'MIT'`, `LICENSE_URL = GITHUB_URL + '/blob/main/LICENSE'`.
  - Notes: Trust boundary, document in a comment: rendered HTML goes through `|safe`, which is acceptable because BOTH inputs are trusted — the markdown content ships with the repo (no user input), and the interpolated placeholder values come from environment config set by the deployment administrator (not end users). They are injected unescaped; if a future placeholder ever carries non-admin-controlled data, escaping must be added. Also document the `{% raw %}` requirement for any literal `{{`/`{%`/`{#` in future doc content — note that `{#...#}` is a Jinja COMMENT delimiter that both renderers silently swallow rather than error on.

- [x] Task 3: Create docs blueprint
  - File: `esb/views/docs.py` (NEW)
  - Action: `docs_bp = Blueprint('docs', __name__, url_prefix='/docs')` with routes:
    - `GET /` → `index()`: render `docs/page.html` with the rendered `index` page.
    - `GET /about` → `about()`: render `docs/about.html` with version + link constants from the service. (Declare BEFORE `/<slug>` or rely on Flask routing — a distinct literal rule wins over the converter rule either way, but keep it above for readability.)
    - `GET /<slug>` → `page(slug)`: for the slug `index`, return `redirect(url_for('docs.index'), code=301)` — otherwise `/docs/index` is a duplicate URL for the Home page that mis-highlights the sub-nav. Render `docs/page.html` for other slugs in `DOC_PAGES`; `abort(404)` for unknown slugs (catch `KeyError`).
    - `GET /images/<path:filename>` → `image(filename)`: serve files from `get_docs_dir() / 'images'` via `send_from_directory(..., max_age=86400)` (which handles path-traversal protection); 404 if missing. The explicit `max_age` gives the dozen full-size screenshot PNGs a 1-day browser cache — they only change with releases; without it Flask sends revalidate-only headers. Model: `serve_upload` at `esb/views/public.py:228-243`.
  - Notes: Lazy-import the service inside handlers, matching the convention in `esb/views/public.py`. No auth decorators — fully public.

- [x] Task 4: Register blueprint
  - File: `esb/views/__init__.py`
  - Action: Import `docs_bp` and add `app.register_blueprint(docs_bp)` in `register_blueprints()` (lines 10-16).

- [x] Task 5: Docs page templates
  - File: `esb/templates/docs/page.html` (NEW)
  - Action: `{% extends "base.html" if current_user.is_authenticated else "base_public.html" %}` (same conditional pattern as `esb/templates/public/status_dashboard.html` line 1). Blocks: `title` = page title; `content` = the docs sub-nav (see contract below) above the rendered markdown emitted with `{{ content|safe }}` inside a wrapper `<div class="docs-content">`.
  - Sub-nav data contract (do NOT hardcode page lists in templates — they'd drift from `DOC_PAGES` silently): every docs view passes `nav_pages` (list of `(slug, title)` derived from `DOC_PAGES` in the service, with the index entry linking to `url_for('docs.index')`) and `current_slug` (the About view passes `current_slug='about'`); `_subnav.html` iterates `nav_pages` plus a static About entry, applying `active` where slug == `current_slug`. Task 10 asserts sub-nav completeness on every docs page.
  - File: `esb/templates/docs/about.html` (NEW)
  - Action: Same conditional extends + same docs sub-nav (extract the sub-nav into `esb/templates/docs/_subnav.html` and `{% include %}` it from both templates). Body: "About Equipment Status Board" — running version, link to GitHub project, MIT license (link to LICENSE on GitHub), link to the online docs site, report-an-issue link.
  - File: `esb/static/css/app.css`
  - Action: Append minimal styles scoped under `.docs-content` so python-markdown output renders acceptably under Bootstrap: `.admonition` (bordered/tinted box with bold `.admonition-title`, distinct tint for `.warning` vs `.note`), table borders/padding (python-markdown emits bare `<table>`; add Bootstrap-like styling for tables inside `.docs-content`), constrained `img { max-width: 100%; }`, and code block background.

- [x] Task 6: Header/footer links
  - File: `esb/templates/base.html`
  - Action: Add a nav item `<a class="nav-link" href="{{ url_for('docs.index') }}">Docs</a>` to the navbar list (lines 20-46), visible to ALL users (no auth conditional), with the `active` highlight when `request.endpoint` starts with `'docs.'` (follow the pattern used by the Repairs link at lines 31-35).
  - File: `esb/templates/components/_footer.html`
  - Action: `base_public.html` ALREADY includes this footer partial (line 17) — do NOT add a second footer. Add a conditional docs link inside the existing `<small>` content, guarded by a context flag, e.g. `{% if show_docs_link %}<a href="{{ url_for('docs.index') }}">Documentation &amp; Help</a>{% endif %}`.
  - File: `esb/templates/base_public.html`
  - Action: Set the flag around the existing include: `{% with show_docs_link = true %}{% include 'components/_footer.html' %}{% endwith %}`.
  - Notes: `base_kiosk.html` includes the SAME `_footer.html` partial — it is NOT modified and does not set the flag, so the docs link stays off kiosk views (AC 11). The flag-guard is what prevents the leak; an unconditional link in the partial would violate the issue's kiosk exclusion.

- [x] Task 7: Edit docs content (placeholder + raw-wrap)
  - File: `docs/staff.md`
  - Action: Line 235: replace the literal `` `#oops` `` with `` `{{ oops_channel }}` `` (the sentence describes runtime notification behavior — installation-specific). This is the ONLY placeholder substitution in this change — investigation audited all five guides and found no other literal that describes installation-specific runtime behavior. (`administrators.md` line 86 documents the `SLACK_OOPS_CHANNEL` env var and its `#oops` default — config documentation stays literal, as do example URLs/ports in deployment instructions and the Slack slash command names, which are fixed in code.)
  - File: `docs/administrators.md`
  - Action: Wrap the fenced bash block at lines 518-520 containing `docker inspect --format '{{.State.Health.Status}}' equipment-status-board-worker-1` in `{% raw %}` (line before the opening ```` ``` ```` at 518) and `{% endraw %}` (line after the closing ```` ``` ```` at 520). Without this, BOTH the runtime Jinja render and the mkdocs-macros build throw `TemplateSyntaxError` on `{{.State...}}`. Verify no other Jinja-meaningful sequence exists in ANY `docs/*.md` file — mkdocs-macros Jinja-processes every `.md` in `docs/`, including the non-nav `manual_testing.md` and `original_requirements_doc.md` (both clean today): `grep -n '{{\|{%\|{#' docs/*.md` should afterwards show only the intended placeholder and the raw-wrapped block. The `{#` check matters: it's Jinja's COMMENT delimiter, which both renderers would silently swallow (content vanishes, no error from StrictUndefined or `on_undefined: strict`) — the one drift case the loud-failure design can't catch.
  - Notes: Every placeholder used in any .md file MUST exist both in `get_placeholder_values()` (Task 2) and in `mkdocs.yml extra:` (Task 8) — StrictUndefined (runtime) and `on_undefined: strict` macros config (CI) both fail otherwise, which is the desired sync guarantee.

- [x] Task 8: mkdocs macros configuration
  - File: `mkdocs.yml`
  - Action: Add:
    ```yaml
    plugins:
      - search
      - macros:
          on_undefined: strict
    extra:
      oops_channel: '#oops'
    ```
  - Notes: CRITICAL ×2 — (1) adding a `plugins:` key disables the implicit default `search` plugin, so `search` must be listed explicitly; (2) mkdocs-macros' DEFAULT behavior is `on_undefined: keep`, which silently leaves undefined `{{ var }}` in the output and passes `mkdocs build --strict` — `on_undefined: strict` is REQUIRED for the CI drift guard to actually fail on undefined placeholders. The `extra:` values are the generic defaults rendered on the public GH Pages site.

- [x] Task 9: Docs CI
  - File: `.github/workflows/docs.yml`
  - Action: Three changes only: (1) line 32: replace `pip install mkdocs mkdocs-material` with `pip install -r requirements-docs.txt` — same toolchain file as the PR gate, so the two can't drift; (2) align the job's `setup-python` to `python-version: "3.14"` with `allow-prereleases: true`, matching `ci.yml`, so the gate actually tests the deploy environment; (3) the push trigger is PATH-FILTERED (lines 7-9: `docs/**`, `mkdocs.yml` — not a bare push-to-main trigger): extend the `paths:` list with `requirements-docs.txt` and `.github/workflows/docs.yml` so toolchain or workflow changes also re-deploy (otherwise a mkdocs-material security bump would never deploy until the next content edit). Do NOT add a `pull_request` trigger to this workflow — it has a `workflow_dispatch` trigger (line 10) used for manual deploys that an `event_name == 'push'` deploy gate would silently break, a shared `concurrency: group: pages` (lines 17-19) that PR builds would pollute (a queued main deploy could be cancelled by a PR build), and an artifact-upload step that PR runs would execute pointlessly.
  - File: `.github/workflows/ci.yml`
  - Action: Add a `docs-build` job (alongside `lint`/`test`/`screenshots-check`/`docker-build`, which already run on every push to main and every PR): checkout + setup-python 3.14 (`allow-prereleases: true`, matching the existing jobs) + `pip install -r requirements-docs.txt` + `mkdocs build --strict`. Installing only `requirements-docs.txt` (not `requirements-dev.txt`) keeps the gate from pulling the whole app stack (boto3, Pillow, playwright…) just to run mkdocs.
  - Notes: This is the pre-merge half of the placeholder-drift guard: `mkdocs build --strict` with `on_undefined: strict` (Task 8) fails the PR check on undefined placeholders or Jinja syntax errors in any `docs/*.md`. `docs.yml` remains deploy-only (push to main + manual dispatch). Both workflows and local dev now install the docs toolchain from the single `requirements-docs.txt`.

- [x] Task 10: Tests
  - File: `tests/test_views/test_docs_views.py` (NEW)
  - Action: Following `tests/test_views/test_public_views.py` conventions (classes per view, unauthenticated `client` fixture, status + content assertions):
    - `TestDocsPages`: each of the six routes (`/docs/`, `/docs/members`, `/docs/technicians`, `/docs/staff`, `/docs/administrators`, `/docs/about`) returns 200 unauthenticated; `/docs/index` returns a 301 redirect to `/docs/` (no duplicate Home URL); unknown slug `/docs/nope` returns 404; every rendered guide contains NO unrendered *placeholder-style* pattern (`re.search(r'\{\{\s*\w+\s*\}\}', html)` is None — NOT a bare `'{{' not in html` check, because the administrators guide legitimately contains the literal `{{.State.Health.Status}}` docker-inspect example in a raw-wrapped code block) and NO intra-doc `.md` hrefs (`re.search(r'href="[^"]*\.md[#"]', html)` is None).
    - `TestDocsRendering` (AC 2 — without this, an empty/typo'd extensions list ships pipe-soup with all tests green): rendered administrators guide contains `<table>`, `class="admonition` (NO closing quote — python-markdown always emits the qualifier, e.g. `class="admonition warning"`, so the closed-quote substring never matches), and `<pre><code>` (or `<pre>` + `<code>` nesting per python-markdown output), plus the literal `{{.State.Health.Status}}` text; a guide with images (e.g., members) contains `<img` tags.
    - `TestDocsAnchors` (intra-page fragment links — the only thing exercising the `toc` extension): for each rendered guide, every `href="#fragment"` in the output has a matching `id="fragment"` attribute in the same document (the four real anchor links live in technicians.md and administrators.md; assert generically so future anchors are covered).
    - `TestDocsLinkResolution` (AC 4): collect every `href="/docs/..."` (strip `#anchors`) from each rendered guide and GET each one — all must return 200. Likewise collect every `<img src="...">` from each rendered guide and GET each — all must return 200 (AC 5; guards the image rewrite, which is otherwise unobservable since relative srcs also resolve). Guards against rewrite rules emitting broken slugs.
    - Sub-nav completeness (AC 14): every docs page (six routes) contains links to all five guides AND `/docs/about` in the sub-nav, with exactly one marked active matching the current page — pins the `nav_pages` contract so the template can't silently drift from `DOC_PAGES`.
    - `TestDocsInterpolation`: set `app.config['SLACK_OOPS_CHANNEL'] = '#custom-chan'` BEFORE first render (per-app cache), GET `/docs/staff`, assert `#custom-chan` appears and `#oops` does not appear in the interpolated sentence.
    - `TestDocsAbout`: assert content that is UNIQUE to the About body — the version string read via `tomllib` in the test (don't hardcode `0.9.0`), the issues URL (`.../issues`), and the GH Pages docs-site URL. (The site-wide `_footer.html` already renders GitHub-repo and MIT-license links on EVERY page, so assertions on those alone would pass trivially; if asserted at all, scope them to the About body markup, not the whole response.)
    - `TestDocsVersionFallback` (AC 9): monkeypatch `docs_service._pyproject_path` with a callable returning a nonexistent path (it is a function — patch the function, not assign a path value), on a fresh app so the per-app cache is cold; GET `/docs/about`, assert 200 and `unknown` displayed as the version.
    - `TestDocsImages`: GET an image that exists under `docs/images/` returns 200 with image content-type AND a `Cache-Control` header containing `max-age=86400`; GET `/docs/images/../index.md` (traversal) returns 404; GET missing image returns 404.
    - `TestDocsNavLinks`: authenticated page (e.g., `staff_client` GET `/equipment/`) contains `href="/docs/"` in the navbar; public page (`client` GET a QR equipment page via `make_equipment`) contains the footer docs link; kiosk pages do NOT contain `href="/docs/"` — for `/public/kiosk/<area_id>` create the area first via `make_area` and `assert response.status_code == 200` BEFORE the negative assertion (asserting against a 404 error page would pass vacuously). This also guards the `_footer.html` flag (kiosk includes the same partial; an unconditional link in it would fail here).
    - `TestDocsCache`: directly verify the cache is per-app, not module-level: in one test, build TWO apps via `create_app('testing')` with different `SLACK_OOPS_CHANNEL` values, render `/docs/staff` in each, and assert each response reflects its own app's channel (a module-level cache would leak the first app's rendering into the second). A second GET on the same app returning identical content is a secondary sanity check only.
  - Notes: No DB models involved; most tests need only `client`.

- [x] Task 11: Lint + full test pass + drift-guard verification
  - File: n/a
  - Action: `make lint` and `make test` green. Verify the GH Pages build locally: `venv/bin/pip install -r requirements-docs.txt && venv/bin/mkdocs build --strict` succeeds. THEN run the NEGATIVE check (AC 12): temporarily remove `oops_channel` from `extra:` in `mkdocs.yml`, run `mkdocs build --strict` again, and confirm it FAILS; restore the line. This proves `on_undefined: strict` is actually wired up — a typo'd option key silently falls back to the plugin's default `keep` mode, which would leave the entire CI drift guard inert while every positive check passes.

- [x] Task 12: Version bump
  - File: `pyproject.toml`
  - Action: Bump `version` with a MINOR increment per the project's release procedure in CLAUDE.md — `0.10.0` as of this writing, but re-check at merge time: the bump must be strictly greater than the latest GitHub release tag *when the PR merges*. If another PR ships `0.10.0` first, this branch's identical one-line change merges conflict-free and the release workflow silently no-ops (it only releases when `pyproject.toml` > latest tag). After merge, verify a release was actually cut (new `v<version>` tag + GitHub Release + image on ghcr.io); if not, push a follow-up bump. Without any bump, the release no-ops and the About page advertises a stale version.

- [x] Task 13: Regenerate committed screenshots
  - File: `docs/images/*.png`
  - Action: AFTER all template changes (Tasks 5-6) are final, regenerate the committed screenshots with `make screenshots` (Makefile lines 37-39 → `scripts/generate_screenshots.py`; requires playwright chromium, see the `screenshots-check` job in `ci.yml` for the install steps) and commit the updated PNGs.
  - Notes: Task 6 changes the chrome of nearly every captured page (navbar "Docs" item on authed pages; footer docs link on public pages, several captured `full_page=True`). The committed PNGs are displayed on the new `/docs/` pages themselves and on GH Pages — without regeneration, the docs ship screenshots of a UI that lacks the feature's own links. CI will NOT catch this: `screenshots-check` only verifies the files exist, not that they're current.

### Acceptance Criteria

- [x] AC 1: Given an unauthenticated visitor, when they GET `/docs/`, then the rendered Home guide is returned with HTTP 200 and no login is required.
- [x] AC 2: Given the five guides collectively, when each is GET at `/docs/<slug>`, then every markdown feature used across them renders as proper HTML — tables/admonitions/fenced code via the administrators guide (which contains NO images), images via the guides that have them (index, members, technicians, staff) — and the administrators guide displays the literal `docker inspect --format '{{.State.Health.Status}}'` example intact inside its code block.
- [x] AC 3: Given `SLACK_OOPS_CHANNEL=#custom-chan` in the app config (the same value Task 10's `TestDocsInterpolation` uses), when a visitor GETs `/docs/staff`, then the notification sentence shows `#custom-chan` and no unrendered placeholder-style pattern (`{{ identifier }}`) appears in any rendered guide (the raw-wrapped docker-inspect literal in the administrators guide is expressly NOT a violation).
- [x] AC 4: Given a guide containing a cross-link to another guide (e.g., `members.md`), when the page is rendered, then the link points to `/docs/members` (not a `.md` file) and resolves with HTTP 200.
- [x] AC 5: Given a guide containing an image reference (`images/<file>.png`), when the page is rendered, then every `<img>` src in the output serves HTTP 200 (verified by extracting and GETting rendered srcs, not by inspecting the route alone), and image responses carry `Cache-Control: max-age=86400`.
- [x] AC 6: Given a request for `/docs/images/../<anything>` (path traversal) or a nonexistent image, when the route handles it, then HTTP 404 is returned.
- [x] AC 7: Given an unknown slug, when a visitor GETs `/docs/whatever`, then HTTP 404 is returned; given `/docs/index`, then a 301 redirect to `/docs/` is returned (no duplicate Home URL).
- [x] AC 8: Given the About page at `/docs/about`, when rendered, then its BODY (not merely the site-wide footer, which already carries GitHub/license links) shows the running version (matching `pyproject.toml`), a link to https://github.com/jantman/equipment-status-board, the MIT license with a link, a link to the online GH Pages docs site, and a report-an-issue link.
- [x] AC 9: Given `pyproject.toml` is unreadable at runtime (verified via monkeypatched `_pyproject_path`), when the About page renders, then the version displays as "unknown" and the page still returns HTTP 200.
- [x] AC 10: Given any authenticated page using `base.html`, when rendered, then the navbar contains a "Docs" link to `/docs/` visible regardless of role; given any public page using `base_public.html` (e.g., a QR equipment page), then a footer link to `/docs/` is present.
- [x] AC 11: Given any kiosk view (`/public/kiosk`, `/public/kiosk/<area_id>`), when rendered, then NO docs link is present.
- [x] AC 12: Given the modified `docs/*.md`, `mkdocs.yml` (macros plugin with `on_undefined: strict`), and docs workflow, when `mkdocs build --strict` runs with `mkdocs-material` and `mkdocs-macros-plugin` installed, then the build succeeds, the GH Pages output renders the generic default values (e.g., `#oops`) where placeholders appear, and removing a variable from `extra:` makes the build FAIL (drift-guard verification).
- [x] AC 13: Given any pull request, when CI runs, then the `docs-build` job in `ci.yml` executes `mkdocs build --strict` as a PR check — placeholder breakage cannot reach `main` unflagged — and `docs.yml` remains deploy-only with its `workflow_dispatch` manual-deploy path intact; both workflows install the docs toolchain from the same `requirements-docs.txt` on the same Python version.
- [x] AC 14: Given any of the six docs pages, when rendered, then the sub-nav contains links to all five guides and the About page, derived from `DOC_PAGES` (not hardcoded), with exactly the current page marked active.
- [x] AC 15: Given the merged feature, when the release workflow runs on `main`, then `pyproject.toml` carries version `0.10.0` and a release is cut (Task 12).

## Additional Context

### Dependencies

- **New runtime dependency:** `Markdown>=3.7` (python-markdown) — pure-Python, no system libs, safe addition to the Docker image. Goes in `requirements.txt` (what the Dockerfile installs) + pyproject `[project] dependencies`.
- **New dev/CI dependency:** `mkdocs-macros-plugin>=1.0` — lives in the new `requirements-docs.txt` (the single docs-toolchain file consumed by `docs.yml`, the `ci.yml` docs-build job, and `requirements-dev.txt` via `-r`); mirrored in pyproject dev extras.
- **No Dockerfile change needed:** `COPY . .` (line 23) already ships `docs/` and `pyproject.toml`; there is no `.dockerignore`.
- **No DB/migration impact.** No service or model dependencies beyond reading Flask config.

### Testing Strategy

- **Unit/integration:** `tests/test_views/test_docs_views.py` per Task 10 — route status codes, markdown feature rendering (tables/admonitions/code/images — AC 2), intra-page anchor integrity (toc), interpolation, link + image resolution from rendered output (ACs 4-5), sub-nav completeness (AC 14), About body content, version fallback via monkeypatched `_pyproject_path` (AC 9), traversal protection + cache headers, nav/footer link presence, kiosk exclusion, per-app cache isolation.
- **CI:** Existing `make lint` / `make test` via `ci.yml`, plus the new `docs-build` job in `ci.yml` running `mkdocs build --strict` with `on_undefined: strict` macros config (plain `--strict` does NOT catch undefined macros on its own) on every PR — drift is caught pre-merge. `docs.yml` stays deploy-only; both install from `requirements-docs.txt`. One-time negative verification of the drift guard in Task 11 (AC 12).
- **Manual:** `make run`, visit `/docs/` logged-out and logged-in (navbar variant), scan a QR equipment page for the footer link, check `/public/kiosk` has no link, eyeball admonition/table/code CSS in the rendered Administrators guide (heaviest text formatting — note it has NO images; check images on e.g. the Members guide) including the literal docker-inspect example, confirm About shows the version.

### Notes

- **Risk — placeholder drift:** a placeholder added to a `.md` without a matching value fails *loudly* in both halves (StrictUndefined at runtime/tests; `on_undefined: strict` macros config in docs CI — the plugin's default `keep` mode would pass silently, so do NOT omit that setting). This is intentional; do not soften to silent defaults.
- **Risk — `plugins:` key in mkdocs.yml:** adding it disables the implicit `search` plugin; `search` must be listed explicitly (Task 8).
- **Risk — Jinja syntax collision (one KNOWN instance):** `docs/administrators.md:519` contains the literal `{{.State.Health.Status}}` docker-inspect example — Task 7 wraps its code block in `{% raw %}`/`{% endraw %}`, which both renderers honor. Any future literal `{{`/`{%`/`{#` in doc content needs the same treatment — note this in a comment in `docs_service.py`. (`{{`/`{%` mistakes fail loudly in the PR docs build; `{#` is the exception — Jinja comments are silently swallowed by both renderers, which is why Task 7's grep includes it.)
- **Risk — renderer divergence:** `mkdocs.yml` enables `pymdownx.details`, `pymdownx.superfences`, `attr_list`, `md_in_html` which the runtime python-markdown renderer does not support. The guides use none of these today, but a future doc edit using them (e.g., a `???` collapsible or `{: .class }`) would build green on GH Pages and render as literal text at `/docs/`. Mitigation: comment in `docs_service.py` listing the supported extension subset; consider aligning `mkdocs.yml` extensions down or adding `pymdown-extensions` at runtime if/when needed. One further ACCEPTED cosmetic delta: `mkdocs.yml` configures `toc: permalink: true` (¶ links on GH Pages headings) while the runtime uses bare `toc` — heading anchor IDs are identical either way (the anchor tests are unaffected); the runtime deliberately skips permalinks, which look cluttered without mkdocs-material's styling.
- **Limitation — post-merge deploy:** even with the PR `docs-build` check in `ci.yml`, the actual Pages *deploy* still only happens on push to `main` (or manual `workflow_dispatch`); deploy-time-only failures (Pages outages, permissions) remain post-merge by nature.
- **Limitation — GitHub repo file view (accepted):** GitHub's native rendering of `docs/*.md` in the repo browser will show `{% raw %}`/`{% endraw %}` markers and `{{ oops_channel }}` verbatim. Accepted cosmetic cost — the canonical reading surfaces are the GH Pages site and the built-in `/docs/`, both of which render them correctly.
- **Limitation:** docs render uses python-markdown, not mkdocs-material — the built-in site will look simpler than GH Pages (no theme nav/search). Accepted; the sub-nav covers navigation and search is out of scope.
- **Future (out of scope):** docs search; serving `manual_testing.md`; per-role docs landing (e.g., technicians land on their guide); an `esb_base_url` placeholder if doc text ever needs the installation URL (deliberately NOT added now — no current doc uses it); linking the static status page URL once a public URL config exists for it.

## Review Notes

- Adversarial review completed (isolated subagent, information-asymmetric — diff only, no implementation context).
- Findings: 11 total, 4 fixed, 7 acknowledged (by-design/documented or noise).
- Resolution approach: auto-fix selected findings (F1, F2, F9, F5).
- **F1 (Critical, fixed):** `docs_cache` namespace collision — `get_version()` shared the page-slug keyspace, so `/docs/version` returned 500 (`ValueError: too many values to unpack`) after the About page was rendered. Fixed by looking up `DOC_PAGES[slug]` before the cache and namespacing cache keys (`('page', slug)` / `('meta', 'version')`). Regression test added.
- **F2 (High, fixed):** the view's blanket `except KeyError` masked a missing placeholder config key as a 404; replaced with an explicit `DOC_PAGES` membership check so genuine errors fail loud (500). Regression test added.
- **F9 (Low, fixed):** narrowed `get_version()`'s `except Exception` to `(OSError, KeyError, tomllib.TOMLDecodeError)`.
- **F5 (Medium, fixed):** added `test_cross_page_anchors_resolve` validating that rewritten `/docs/<slug>#frag` links point at a real id on the target page (the existing test stripped fragments before checking).
- Acknowledged (no change): F3 (whole-doc Jinja pass — intended fail-loud + `{% raw %}` design), F4 (link-regex edge cases — no current cases; no-`.md`-href test guards future), F6 (extension drift — documented), F7 (`|safe` trust boundary — documented, admin-controlled inputs), F8 (image-route extension allow-list — `docs/images/` holds only repo-shipped PNGs), F10 (`rel` without `target=_blank` — cosmetic), F11 (noise — `docs.yml` does not run on PRs, so the `ci.yml docs-build` job is the intended PR gate, not redundant).
- Post-fix verification: `ruff` clean, full suite **1701 passed**, `mkdocs build --strict` succeeds, drift-guard negative check confirmed (build fails when `extra.oops_channel` removed).
