---
title: 'Built-in Docs/Help Site'
slug: 'built-in-docs-site'
created: '2026-06-07'
status: 'ready-for-dev'
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
  - 'docs/staff.md, docs/administrators.md'
  - 'mkdocs.yml'
  - '.github/workflows/docs.yml'
  - '.github/workflows/ci.yml'
  - 'requirements.txt + requirements-dev.txt + pyproject.toml'
  - 'tests/test_views/test_docs_views.py (NEW)'
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
- **Markdown:** No markdown rendering exists anywhere in the app today, and NO markdown library is currently a dependency at any level. `mkdocs`/`mkdocs-material` (the docs site generator, not a rendering library usable in-app) appear in `requirements-dev.txt` and pyproject dev extras, and are installed in the docs CI workflow only. Note: dev tooling is installed from `requirements-dev.txt` (`make setup` → Makefile line 8; `ci.yml` lines 30/44) — the pyproject `[project.optional-dependencies] dev` extras are never pip-installed by anything; `requirements-dev.txt` is the operative file.
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
| `.github/workflows/docs.yml` | Pages deploy workflow (push to main + workflow_dispatch; `pages` concurrency group) — ONLY change: add macros plugin to pip install |
| `.github/workflows/ci.yml` | Runs on every PR — gains the `docs-build` job (`mkdocs build --strict`) |
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

- [ ] Task 1: Add dependencies
  - File: `requirements.txt`
  - Action: Add `Markdown>=3.7` (python-markdown, runtime dependency for server-side rendering). The Dockerfile installs from this file — it is what makes the library available in the image.
  - File: `requirements-dev.txt`
  - Action: Add `mkdocs-macros-plugin>=1.0` (alongside the existing `mkdocs`/`mkdocs-material` lines). This is the file `make setup` (Makefile line 8) and `ci.yml` (lines 30, 44) actually install — pyproject dev extras are installed by nothing.
  - File: `pyproject.toml`
  - Action: Mirror for consistency: add `"Markdown>=3.7"` to `[project] dependencies`; add `"mkdocs-macros-plugin>=1.0"` to `[project.optional-dependencies] dev`.

- [ ] Task 2: Create docs service
  - File: `esb/services/docs_service.py` (NEW)
  - Action: Implement the docs rendering service:
    - `DOC_PAGES`: ordered dict mapping slug → `{'file': '<name>.md', 'title': '<nav title>'}` for exactly: `index` → `index.md` / "Home", `members` → `members.md` / "Members Guide", `technicians` → `technicians.md` / "Technicians Guide", `staff` → `staff.md` / "Staff Guide", `administrators` → `administrators.md` / "Administrators Guide". (Mirrors the `nav:` in `mkdocs.yml`. `manual_testing.md` and `original_requirements_doc.md` are deliberately excluded.)
    - `get_docs_dir()`: a FUNCTION (not a module constant — `current_app` raises `RuntimeError` outside an app context at import time) returning `Path(current_app.root_path).parent / 'docs'` (the repo-root `docs/` directory, which `Dockerfile` line 23 `COPY . .` ships into the image at `/app/docs`).
    - `get_placeholder_values()`: returns the interpolation dict from live config: `{'oops_channel': current_app.config['SLACK_OOPS_CHANNEL']}`. Exactly one placeholder initially; this dict is the single extension point for future placeholders. Every key here MUST also exist in `mkdocs.yml extra:`.
    - `render_page(slug)`: returns `(title, html)` or raises `KeyError` for unknown slug. Pipeline: (1) read the markdown file; (2) render placeholders with `jinja2.Environment(undefined=StrictUndefined).from_string(text).render(**get_placeholder_values())` — StrictUndefined makes a typo'd placeholder fail loudly in tests rather than render `{{ ... }}` to users. The docs honor `{% raw %}` blocks (needed for the docker-inspect example in administrators.md — see Task 7); (3) rewrite links/images in markdown source via regex on link targets: `(<page>.md)` → `(/docs/<slug>)`, `(<page>.md#anchor)` → `(/docs/<slug>#anchor)`, `(images/<file>)` → `(/docs/images/<file>)`. Rewrite ONLY the five served page names — investigation confirmed no guide links to a non-served `.md` file, so no fallback rule is needed (the no-`.md`-href test in Task 10 will flag any future case and force an explicit decision); (4) convert with `markdown.markdown(text, extensions=['tables', 'fenced_code', 'admonition', 'toc'])` — the only features the five guides use today (see divergence note in Notes section).
    - Per-app render cache: store rendered results in a dict on `app.extensions.setdefault('docs_cache', {})` keyed by slug. Do NOT use a module-level cache — tests create a fresh app per test with different config, and a module-level cache would serve stale interpolations across tests.
    - `_pyproject_path()`: small helper returning the repo-root `pyproject.toml` path — exists so tests can monkeypatch it to exercise the version-fallback path (AC 9).
    - `get_version()`: parse `_pyproject_path()` with stdlib `tomllib`, return `project.version`; cache per-app; return `'unknown'` on any failure (missing file, parse error). NOTE: `importlib.metadata.version()` will NOT work — the Docker image copies source and installs only `requirements.txt`; the `equipment-status-board` package itself is never pip-installed.
    - Module constants for the About page: `GITHUB_URL = 'https://github.com/jantman/equipment-status-board'`, `DOCS_SITE_URL = 'https://jantman.github.io/equipment-status-board/'`, `ISSUES_URL = GITHUB_URL + '/issues'`, `LICENSE_NAME = 'MIT'`, `LICENSE_URL = GITHUB_URL + '/blob/main/LICENSE'`.
  - Notes: Markdown content is trusted (ships with the repo; no user input), so rendering with `|safe` downstream is acceptable — no bleach/sanitization needed. Document this in a comment, along with the `{% raw %}` requirement for any literal `{{`/`{%` in future doc content.

- [ ] Task 3: Create docs blueprint
  - File: `esb/views/docs.py` (NEW)
  - Action: `docs_bp = Blueprint('docs', __name__, url_prefix='/docs')` with routes:
    - `GET /` → `index()`: render `docs/page.html` with the rendered `index` page.
    - `GET /about` → `about()`: render `docs/about.html` with version + link constants from the service. (Declare BEFORE `/<slug>` or rely on Flask routing — a distinct literal rule wins over the converter rule either way, but keep it above for readability.)
    - `GET /<slug>` → `page(slug)`: render `docs/page.html` for slugs in `DOC_PAGES`; `abort(404)` for unknown slugs (catch `KeyError`).
    - `GET /images/<path:filename>` → `image(filename)`: serve files from `get_docs_dir() / 'images'` via `send_from_directory` (which handles path-traversal protection); 404 if missing. Model: `serve_upload` at `esb/views/public.py:228-243`.
  - Notes: Lazy-import the service inside handlers, matching the convention in `esb/views/public.py`. No auth decorators — fully public.

- [ ] Task 4: Register blueprint
  - File: `esb/views/__init__.py`
  - Action: Import `docs_bp` and add `app.register_blueprint(docs_bp)` in `register_blueprints()` (lines 10-16).

- [ ] Task 5: Docs page templates
  - File: `esb/templates/docs/page.html` (NEW)
  - Action: `{% extends "base.html" if current_user.is_authenticated else "base_public.html" %}` (same conditional pattern as `esb/templates/public/status_dashboard.html` line 1). Blocks: `title` = page title; `content` = a docs sub-nav (horizontal Bootstrap nav pills/tabs linking to all five guides + About, current page highlighted) above the rendered markdown emitted with `{{ content|safe }}` inside a wrapper `<div class="docs-content">`.
  - File: `esb/templates/docs/about.html` (NEW)
  - Action: Same conditional extends + same docs sub-nav (extract the sub-nav into `esb/templates/docs/_subnav.html` and `{% include %}` it from both templates). Body: "About Equipment Status Board" — running version, link to GitHub project, MIT license (link to LICENSE on GitHub), link to the online docs site, report-an-issue link.
  - File: `esb/static/css/app.css`
  - Action: Append minimal styles scoped under `.docs-content` so python-markdown output renders acceptably under Bootstrap: `.admonition` (bordered/tinted box with bold `.admonition-title`, distinct tint for `.warning` vs `.note`), table borders/padding (python-markdown emits bare `<table>`; add Bootstrap-like styling for tables inside `.docs-content`), constrained `img { max-width: 100%; }`, and code block background.

- [ ] Task 6: Header/footer links
  - File: `esb/templates/base.html`
  - Action: Add a nav item `<a class="nav-link" href="{{ url_for('docs.index') }}">Docs</a>` to the navbar list (lines 20-46), visible to ALL users (no auth conditional), with the `active` highlight when `request.endpoint` starts with `'docs.'` (follow the pattern used by the Repairs link at lines 31-35).
  - File: `esb/templates/components/_footer.html`
  - Action: `base_public.html` ALREADY includes this footer partial (line 17) — do NOT add a second footer. Add a conditional docs link inside the existing `<small>` content, guarded by a context flag, e.g. `{% if show_docs_link %}<a href="{{ url_for('docs.index') }}">Documentation &amp; Help</a>{% endif %}`.
  - File: `esb/templates/base_public.html`
  - Action: Set the flag around the existing include: `{% with show_docs_link = true %}{% include 'components/_footer.html' %}{% endwith %}`.
  - Notes: `base_kiosk.html` includes the SAME `_footer.html` partial — it is NOT modified and does not set the flag, so the docs link stays off kiosk views (AC 11). The flag-guard is what prevents the leak; an unconditional link in the partial would violate the issue's kiosk exclusion.

- [ ] Task 7: Edit docs content (placeholder + raw-wrap)
  - File: `docs/staff.md`
  - Action: Line 235: replace the literal `` `#oops` `` with `` `{{ oops_channel }}` `` (the sentence describes runtime notification behavior — installation-specific). This is the ONLY placeholder substitution in this change — investigation audited all five guides and found no other literal that describes installation-specific runtime behavior. (`administrators.md` line 86 documents the `SLACK_OOPS_CHANNEL` env var and its `#oops` default — config documentation stays literal, as do example URLs/ports in deployment instructions and the Slack slash command names, which are fixed in code.)
  - File: `docs/administrators.md`
  - Action: Wrap the fenced bash block at lines 518-520 containing `docker inspect --format '{{.State.Health.Status}}' equipment-status-board-worker-1` in `{% raw %}` (line before the opening ```` ``` ```` at 518) and `{% endraw %}` (line after the closing ```` ``` ```` at 520). Without this, BOTH the runtime Jinja render and the mkdocs-macros build throw `TemplateSyntaxError` on `{{.State...}}`. Verify no other literal `{{`/`{%` exists in ANY `docs/*.md` file — mkdocs-macros Jinja-processes every `.md` in `docs/`, including the non-nav `manual_testing.md` and `original_requirements_doc.md` (both clean today): `grep -n '{{\|{%' docs/*.md` should afterwards show only the intended placeholder and the raw-wrapped block.
  - Notes: Every placeholder used in any .md file MUST exist both in `get_placeholder_values()` (Task 2) and in `mkdocs.yml extra:` (Task 8) — StrictUndefined (runtime) and `on_undefined: strict` macros config (CI) both fail otherwise, which is the desired sync guarantee.

- [ ] Task 8: mkdocs macros configuration
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

- [ ] Task 9: Docs CI
  - File: `.github/workflows/docs.yml`
  - Action: Line 32 ONLY: change `pip install mkdocs mkdocs-material` → `pip install mkdocs mkdocs-material mkdocs-macros-plugin`. Do NOT add a `pull_request` trigger to this workflow — it has a `workflow_dispatch` trigger (line 10) used for manual deploys that an `event_name == 'push'` deploy gate would silently break, a shared `concurrency: group: pages` (lines 17-19) that PR builds would pollute (a queued main deploy could be cancelled by a PR build), and an artifact-upload step that PR runs would execute pointlessly.
  - File: `.github/workflows/ci.yml`
  - Action: Add a `docs-build` job (alongside `lint`/`test`/`screenshots-check`/`docker-build`, which already run on every push to main and every PR): checkout + setup-python 3.14 (`allow-prereleases: true`, matching the existing jobs) + `pip install -r requirements-dev.txt` + `mkdocs build --strict`. The macros plugin is in `requirements-dev.txt` after Task 1, so this needs no extra installs.
  - Notes: This is the pre-merge half of the placeholder-drift guard: `mkdocs build --strict` with `on_undefined: strict` (Task 8) fails the PR check on undefined placeholders or Jinja syntax errors in any `docs/*.md`. `docs.yml` remains deploy-only (push to main + manual dispatch), untouched except the plugin install.

- [ ] Task 10: Tests
  - File: `tests/test_views/test_docs_views.py` (NEW)
  - Action: Following `tests/test_views/test_public_views.py` conventions (classes per view, unauthenticated `client` fixture, status + content assertions):
    - `TestDocsPages`: each of the six routes (`/docs/`, `/docs/members`, `/docs/technicians`, `/docs/staff`, `/docs/administrators`, `/docs/about`) returns 200 unauthenticated; unknown slug `/docs/nope` returns 404; every rendered guide contains NO unrendered *placeholder-style* pattern (`re.search(r'\{\{\s*\w+\s*\}\}', html)` is None — NOT a bare `'{{' not in html` check, because the administrators guide legitimately contains the literal `{{.State.Health.Status}}` docker-inspect example in a raw-wrapped code block) and NO intra-doc `.md` hrefs (`re.search(r'href="[^"]*\.md[#"]', html)` is None).
    - `TestDocsLinkResolution` (AC 4): collect every `href="/docs/..."` (strip `#anchors`) from each rendered guide and GET each one — all must return 200. Guards against rewrite rules emitting broken slugs.
    - `TestDocsInterpolation`: set `app.config['SLACK_OOPS_CHANNEL'] = '#custom-chan'` BEFORE first render (per-app cache), GET `/docs/staff`, assert `#custom-chan` appears and `#oops` does not appear in the interpolated sentence.
    - `TestDocsAbout`: assert content that is UNIQUE to the About body — the version string read via `tomllib` in the test (don't hardcode `0.9.0`), the issues URL (`.../issues`), and the GH Pages docs-site URL. (The site-wide `_footer.html` already renders GitHub-repo and MIT-license links on EVERY page, so assertions on those alone would pass trivially; if asserted at all, scope them to the About body markup, not the whole response.)
    - `TestDocsVersionFallback` (AC 9): monkeypatch `docs_service._pyproject_path` with a callable returning a nonexistent path (it is a function — patch the function, not assign a path value), on a fresh app so the per-app cache is cold; GET `/docs/about`, assert 200 and `unknown` displayed as the version.
    - `TestDocsImages`: GET an image that exists under `docs/images/` returns 200 with image content-type; GET `/docs/images/../index.md` (traversal) returns 404; GET missing image returns 404.
    - `TestDocsNavLinks`: authenticated page (e.g., `staff_client` GET `/equipment/`) contains `href="/docs/"` in the navbar; public page (`client` GET a QR equipment page via `make_equipment`) contains the footer docs link; kiosk pages do NOT contain `href="/docs/"` — for `/public/kiosk/<area_id>` create the area first via `make_area` and `assert response.status_code == 200` BEFORE the negative assertion (asserting against a 404 error page would pass vacuously). This also guards the `_footer.html` flag (kiosk includes the same partial; an unconditional link in it would fail here).
    - `TestDocsCache`: directly verify the cache is per-app, not module-level: in one test, build TWO apps via `create_app('testing')` with different `SLACK_OOPS_CHANNEL` values, render `/docs/staff` in each, and assert each response reflects its own app's channel (a module-level cache would leak the first app's rendering into the second). A second GET on the same app returning identical content is a secondary sanity check only.
  - Notes: No DB models involved; most tests need only `client`.

- [ ] Task 11: Lint + full test pass
  - File: n/a
  - Action: `make lint` and `make test` green. Manually verify the GH Pages build locally: `venv/bin/pip install mkdocs mkdocs-material mkdocs-macros-plugin && venv/bin/mkdocs build --strict` succeeds.

### Acceptance Criteria

- [ ] AC 1: Given an unauthenticated visitor, when they GET `/docs/`, then the rendered Home guide is returned with HTTP 200 and no login is required.
- [ ] AC 2: Given the five guides collectively, when each is GET at `/docs/<slug>`, then every markdown feature used across them renders as proper HTML — tables/admonitions/fenced code via the administrators guide (which contains NO images), images via the guides that have them (index, members, technicians, staff) — and the administrators guide displays the literal `docker inspect --format '{{.State.Health.Status}}'` example intact inside its code block.
- [ ] AC 3: Given `SLACK_OOPS_CHANNEL=#custom-chan` in the app config (the same value Task 10's `TestDocsInterpolation` uses), when a visitor GETs `/docs/staff`, then the notification sentence shows `#custom-chan` and no unrendered placeholder-style pattern (`{{ identifier }}`) appears in any rendered guide (the raw-wrapped docker-inspect literal in the administrators guide is expressly NOT a violation).
- [ ] AC 4: Given a guide containing a cross-link to another guide (e.g., `members.md`), when the page is rendered, then the link points to `/docs/members` (not a `.md` file) and resolves with HTTP 200.
- [ ] AC 5: Given a guide containing an image reference (`images/<file>.png`), when the page is rendered, then the `<img>` src points to `/docs/images/<file>.png` and that URL serves the image with HTTP 200.
- [ ] AC 6: Given a request for `/docs/images/../<anything>` (path traversal) or a nonexistent image, when the route handles it, then HTTP 404 is returned.
- [ ] AC 7: Given an unknown slug, when a visitor GETs `/docs/whatever`, then HTTP 404 is returned.
- [ ] AC 8: Given the About page at `/docs/about`, when rendered, then its BODY (not merely the site-wide footer, which already carries GitHub/license links) shows the running version (matching `pyproject.toml`), a link to https://github.com/jantman/equipment-status-board, the MIT license with a link, a link to the online GH Pages docs site, and a report-an-issue link.
- [ ] AC 9: Given `pyproject.toml` is unreadable at runtime (verified via monkeypatched `_pyproject_path`), when the About page renders, then the version displays as "unknown" and the page still returns HTTP 200.
- [ ] AC 10: Given any authenticated page using `base.html`, when rendered, then the navbar contains a "Docs" link to `/docs/` visible regardless of role; given any public page using `base_public.html` (e.g., a QR equipment page), then a footer link to `/docs/` is present.
- [ ] AC 11: Given any kiosk view (`/public/kiosk`, `/public/kiosk/<area_id>`), when rendered, then NO docs link is present.
- [ ] AC 12: Given the modified `docs/*.md`, `mkdocs.yml` (macros plugin with `on_undefined: strict`), and docs workflow, when `mkdocs build --strict` runs with `mkdocs-material` and `mkdocs-macros-plugin` installed, then the build succeeds, the GH Pages output renders the generic default values (e.g., `#oops`) where placeholders appear, and removing a variable from `extra:` makes the build FAIL (drift-guard verification).
- [ ] AC 13: Given any pull request, when CI runs, then the `docs-build` job in `ci.yml` executes `mkdocs build --strict` as a PR check — placeholder breakage cannot reach `main` unflagged — and `docs.yml` remains deploy-only with its `workflow_dispatch` manual-deploy path intact.

## Additional Context

### Dependencies

- **New runtime dependency:** `Markdown>=3.7` (python-markdown) — pure-Python, no system libs, safe addition to the Docker image. Goes in `requirements.txt` (what the Dockerfile installs) + pyproject `[project] dependencies`.
- **New dev/CI dependency:** `mkdocs-macros-plugin>=1.0` — goes in `requirements-dev.txt` (what `make setup` and `ci.yml` install; pyproject dev extras are installed by nothing) + mirrored in pyproject dev extras; installed explicitly in `.github/workflows/docs.yml`.
- **No Dockerfile change needed:** `COPY . .` (line 23) already ships `docs/` and `pyproject.toml`; there is no `.dockerignore`.
- **No DB/migration impact.** No service or model dependencies beyond reading Flask config.

### Testing Strategy

- **Unit/integration:** `tests/test_views/test_docs_views.py` per Task 10 — route status codes, interpolation, link/image rewriting + rewritten-link resolution (AC 4), About body content, version fallback via monkeypatched `_pyproject_path` (AC 9), traversal protection, nav/footer link presence, kiosk exclusion.
- **CI:** Existing `make lint` / `make test` via `ci.yml`, plus the new `docs-build` job in `ci.yml` running `mkdocs build --strict` with `on_undefined: strict` macros config (plain `--strict` does NOT catch undefined macros on its own) on every PR — drift is caught pre-merge. `docs.yml` stays deploy-only.
- **Manual:** `make run`, visit `/docs/` logged-out and logged-in (navbar variant), scan a QR equipment page for the footer link, check `/public/kiosk` has no link, eyeball admonition/table/code CSS in the rendered Administrators guide (heaviest text formatting — note it has NO images; check images on e.g. the Members guide) including the literal docker-inspect example, confirm About shows the version.

### Notes

- **Risk — placeholder drift:** a placeholder added to a `.md` without a matching value fails *loudly* in both halves (StrictUndefined at runtime/tests; `on_undefined: strict` macros config in docs CI — the plugin's default `keep` mode would pass silently, so do NOT omit that setting). This is intentional; do not soften to silent defaults.
- **Risk — `plugins:` key in mkdocs.yml:** adding it disables the implicit `search` plugin; `search` must be listed explicitly (Task 8).
- **Risk — Jinja syntax collision (one KNOWN instance):** `docs/administrators.md:519` contains the literal `{{.State.Health.Status}}` docker-inspect example — Task 7 wraps its code block in `{% raw %}`/`{% endraw %}`, which both renderers honor. Any future literal `{{`/`{%` in doc content needs the same treatment — note this in a comment in `docs_service.py`. (mkdocs-macros has the same constraint, so the PR docs build would also catch it.)
- **Risk — renderer divergence:** `mkdocs.yml` enables `pymdownx.details`, `pymdownx.superfences`, `attr_list`, `md_in_html` which the runtime python-markdown renderer does not support. The guides use none of these today, but a future doc edit using them (e.g., a `???` collapsible or `{: .class }`) would build green on GH Pages and render as literal text at `/docs/`. Mitigation: comment in `docs_service.py` listing the supported extension subset; consider aligning `mkdocs.yml` extensions down or adding `pymdown-extensions` at runtime if/when needed.
- **Limitation — post-merge deploy:** even with the PR `docs-build` check in `ci.yml`, the actual Pages *deploy* still only happens on push to `main` (or manual `workflow_dispatch`); deploy-time-only failures (Pages outages, permissions) remain post-merge by nature.
- **Limitation — GitHub repo file view (accepted):** GitHub's native rendering of `docs/*.md` in the repo browser will show `{% raw %}`/`{% endraw %}` markers and `{{ oops_channel }}` verbatim. Accepted cosmetic cost — the canonical reading surfaces are the GH Pages site and the built-in `/docs/`, both of which render them correctly.
- **Limitation:** docs render uses python-markdown, not mkdocs-material — the built-in site will look simpler than GH Pages (no theme nav/search). Accepted; the sub-nav covers navigation and search is out of scope.
- **Future (out of scope):** docs search; serving `manual_testing.md`; per-role docs landing (e.g., technicians land on their guide); an `esb_base_url` placeholder if doc text ever needs the installation URL (deliberately NOT added now — no current doc uses it); linking the static status page URL once a public URL config exists for it.
