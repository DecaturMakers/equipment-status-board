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
  - 'esb/templates/base.html'
  - 'esb/templates/base_public.html'
  - 'docs/index.md, docs/members.md, docs/technicians.md, docs/staff.md, docs/administrators.md'
  - 'mkdocs.yml'
  - '.github/workflows/docs.yml'
  - 'requirements.txt + pyproject.toml'
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
- Runtime markdown rendering with placeholder interpolation (e.g., base URL, Slack channel, static page URL)
- Header link in `base.html` and `base_public.html` (not `base_kiosk.html`)
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
- **Templates:** Three bases. `base.html` — full Bootstrap navbar (lines 13-63) with role-conditional items (`current_user.is_authenticated` / `role == 'staff'` checks at lines 24-46). `base_public.html` — minimal 23-line template, **no nav/header at all**, just flash messages + `{% block content %}`. `base_kiosk.html` — no nav (intentional, excluded per issue). Public templates live in `esb/templates/public/` and use blocks `title`, `content`, optional `extra_css`/`extra_js`.
- **Context processors:** `create_app()` registers `inject_current_year` and `inject_repair_constants` (`esb/__init__.py:83-89`) — precedent for injecting template globals.
- **Jinja filters:** registered in `esb/utils/filters.py:99-105` (`format_date`, `filesize`, etc.).
- **Markdown:** No markdown rendering exists anywhere in the app today; `markdown` and `mkdocs-material` appear only in dev dependencies (`pyproject.toml` lines 22-23) and the CI docs build.
- **Tests:** `tests/test_views/test_public_views.py` is the model — class-per-view (`TestStatusDashboardView`), unauthenticated `client` fixture, factory fixtures (`make_area`, `make_equipment`), assertions on `response.status_code` and `response.data` content (bytes or decoded + regex).

### Files to Reference

| File | Purpose |
| ---- | ------- |
| `esb/views/public.py` | Model for a public, no-auth blueprint (routes, lazy service imports) |
| `esb/views/__init__.py` | `register_blueprints()` — add new `docs_bp` here |
| `esb/__init__.py` | App factory: blueprint registration, context processors, filter registration |
| `esb/templates/base.html` | Authed navbar (lines 13-63) — add Docs nav link |
| `esb/templates/base_public.html` | Public base (no nav) — add footer with Docs link |
| `esb/templates/base_kiosk.html` | Kiosk base — explicitly NOT touched |
| `esb/config.py` | Config values for interpolation (`SLACK_OOPS_CHANNEL` line 48, `ESB_BASE_URL` line 34) |
| `docs/*.md` | Source content: index, members, technicians, staff, administrators (+ `docs/images/`) |
| `mkdocs.yml` | GH Pages nav + markdown_extensions; add macros plugin + extra vars |
| `.github/workflows/docs.yml` | CI docs build (`mkdocs build --strict`); add mkdocs-macros-plugin install |
| `Dockerfile` | `COPY . .` (line 23) already ships `docs/`; app NOT pip-installed (version gotcha) |
| `pyproject.toml` | `version = "0.9.0"` (line 3) — runtime source of truth for About page via `tomllib` |
| `LICENSE` | MIT — referenced on About page |
| `tests/conftest.py` | Fixtures: `app`, `client`, factory fixtures |
| `tests/test_views/test_public_views.py` | Test pattern model for public views |

### Technical Decisions

- **Content source:** Single source of truth — render the same `docs/*.md` files used by the mkdocs GitHub Pages site at runtime; ship them in the Docker image (already covered by `COPY . .`). No duplicated content.
- **Access:** Fully public, no login required (matches public status dashboard and QR pages).
- **Guides included:** All five mkdocs-nav pages (Home/index, Members, Technicians, Staff, Administrators) plus About. `manual_testing.md` and `original_requirements_doc.md` are not in the mkdocs nav and are excluded.
- **Placeholder mechanism:** Jinja-style placeholders (e.g., `{{ oops_channel }}`) added to `docs/*.md`, replacing hardcoded installation-specific literals (`#oops` in staff.md/administrators.md/manual_testing.md, etc.). The GH Pages build gains `mkdocs-macros-plugin` with generic default values defined under `extra:` in `mkdocs.yml`; the app renders the same placeholders at runtime via Jinja2 with live config values. One source, explicit markers, `--strict` build stays green.
- **Interpolated values (initial set):** `oops_channel` ← `SLACK_OOPS_CHANNEL`, `esb_base_url` ← `ESB_BASE_URL` (with sensible fallback when unset). Mechanism is a single mapping dict in the docs service, extensible later. Slack slash command names are fixed in code, not config — they stay literal.
- **Markdown rendering:** Add `Markdown` (python-markdown) as a runtime dependency. Extensions: `tables`, `fenced_code`, `admonition`, `toc` — the only features actually used by the five guides. Admonition/toc output needs small CSS to render acceptably under Bootstrap.
- **Link/image rewriting:** At render time, rewrite inter-doc links (`members.md` → `/docs/members`, `staff.md#anchor` → `/docs/staff#anchor`) and image refs (`images/foo.png` → docs image route). Serve `docs/images/` via a dedicated route with path-traversal protection (model: `serve_upload` in `esb/views/public.py:228-243`).
- **Version at runtime:** The Docker image copies source but never pip-installs the package, so `importlib.metadata` will NOT work. Parse `pyproject.toml` with stdlib `tomllib` (cached at first use); display "unknown" if unavailable.
- **About page:** running version, link to GitHub repo, MIT license note + link, link to GH Pages docs site (`https://jantman.github.io/equipment-status-board/`), report-an-issue link (GitHub issues URL).
- **Header links:** `base.html` navbar gets a "Docs" link (visible to all). `base_public.html` gets a small **footer** with a Docs link (user choice — avoids adding a header bar to QR/public pages). `base_kiosk.html` untouched.
- **Caching:** Rendered pages are static per-process (content ships with the image; config is fixed at startup) — render-once-and-cache per page is acceptable and avoids per-request markdown parsing.

## Implementation Plan

### Tasks

- [ ] Task 1: Add dependencies
  - File: `requirements.txt`
  - Action: Add `Markdown>=3.7` (python-markdown, runtime dependency for server-side rendering).
  - File: `pyproject.toml`
  - Action: Add `"Markdown>=3.7"` to `[project] dependencies`; add `"mkdocs-macros-plugin>=1.0"` to `[project.optional-dependencies] dev` (alongside existing `mkdocs`/`mkdocs-material`).
  - Notes: Correction from investigation — `markdown` is NOT currently a dev dep; dev deps are `pytest`, `ruff`, `mkdocs`, `mkdocs-material`. The Dockerfile installs from `requirements.txt`, so that file is what makes the library available in the image.

- [ ] Task 2: Create docs service
  - File: `esb/services/docs_service.py` (NEW)
  - Action: Implement the docs rendering service:
    - `DOC_PAGES`: ordered dict mapping slug → `{'file': '<name>.md', 'title': '<nav title>'}` for exactly: `index` → `index.md` / "Home", `members` → `members.md` / "Members Guide", `technicians` → `technicians.md` / "Technicians Guide", `staff` → `staff.md` / "Staff Guide", `administrators` → `administrators.md` / "Administrators Guide". (Mirrors the `nav:` in `mkdocs.yml`. `manual_testing.md` and `original_requirements_doc.md` are deliberately excluded.)
    - `DOCS_DIR`: resolved as `Path(current_app.root_path).parent / 'docs'` (the repo-root `docs/` directory, which `Dockerfile` line 23 `COPY . .` ships into the image at `/app/docs`).
    - `get_placeholder_values()`: returns the interpolation dict from live config: `{'oops_channel': current_app.config['SLACK_OOPS_CHANNEL'], 'esb_base_url': current_app.config['ESB_BASE_URL'] or request-independent fallback ''}`. Single extension point for future placeholders.
    - `render_page(slug)`: returns `(title, html)` or raises `KeyError` for unknown slug. Pipeline: (1) read the markdown file; (2) render placeholders with `jinja2.Environment(undefined=StrictUndefined).from_string(text).render(**get_placeholder_values())` — StrictUndefined makes a typo'd placeholder fail loudly in tests rather than render `{{ ... }}` to users; (3) rewrite links/images in markdown source via regex on link targets: `(<page>.md)` → `(/docs/<slug>)`, `(<page>.md#anchor)` → `(/docs/<slug>#anchor)`, `(images/<file>)` → `(/docs/images/<file>)`; links to non-served files (e.g., `manual_testing.md`) rewrite to the GH Pages site URL `https://jantman.github.io/equipment-status-board/<page>/`; (4) convert with `markdown.markdown(text, extensions=['tables', 'fenced_code', 'admonition', 'toc'])` — the only features the five guides use (verified by investigation).
    - Per-app render cache: store rendered results in a dict on `app.extensions.setdefault('docs_cache', {})` keyed by slug. Do NOT use a module-level cache — tests create a fresh app per test with different config, and a module-level cache would serve stale interpolations across tests.
    - `get_version()`: parse repo-root `pyproject.toml` with stdlib `tomllib`, return `project.version`; cache per-app; return `'unknown'` on any failure (missing file, parse error). NOTE: `importlib.metadata.version()` will NOT work — the Docker image copies source and installs only `requirements.txt`; the `equipment-status-board` package itself is never pip-installed.
    - Module constants for the About page: `GITHUB_URL = 'https://github.com/jantman/equipment-status-board'`, `DOCS_SITE_URL = 'https://jantman.github.io/equipment-status-board/'`, `ISSUES_URL = GITHUB_URL + '/issues'`, `LICENSE_NAME = 'MIT'`, `LICENSE_URL = GITHUB_URL + '/blob/main/LICENSE'`.
  - Notes: Markdown content is trusted (ships with the repo; no user input), so rendering with `|safe` downstream is acceptable — no bleach/sanitization needed. Document this in a comment.

- [ ] Task 3: Create docs blueprint
  - File: `esb/views/docs.py` (NEW)
  - Action: `docs_bp = Blueprint('docs', __name__, url_prefix='/docs')` with routes:
    - `GET /` → `index()`: render `docs/page.html` with the rendered `index` page.
    - `GET /about` → `about()`: render `docs/about.html` with version + link constants from the service. (Declare BEFORE `/<slug>` or rely on Flask routing — a distinct literal rule wins over the converter rule either way, but keep it above for readability.)
    - `GET /<slug>` → `page(slug)`: render `docs/page.html` for slugs in `DOC_PAGES`; `abort(404)` for unknown slugs (catch `KeyError`).
    - `GET /images/<path:filename>` → `image(filename)`: serve files from `DOCS_DIR / 'images'` via `send_from_directory` (which handles path-traversal protection); 404 if missing. Model: `serve_upload` at `esb/views/public.py:228-243`.
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
  - Action: Add a nav item `<a class="nav-link" href="{{ url_for('docs.index') }}">Docs</a>` to the navbar list (lines 20-46), visible to ALL users (no auth conditional), with the `active` highlight when `request.endpoint` starts with `'docs.'` (follow the pattern used by the Repairs link at lines 31-36).
  - File: `esb/templates/base_public.html`
  - Action: Add a small footer after the `<main>` block: muted, centered, e.g. `<footer class="container mt-4 mb-3 text-center text-muted small"><a href="{{ url_for('docs.index') }}">Documentation &amp; Help</a></footer>`.
  - Notes: `base_kiosk.html` is NOT modified (kiosk views excluded per issue).

- [ ] Task 7: Add placeholders to docs content
  - File: `docs/staff.md`
  - Action: Line 235: replace the literal `` `#oops` `` with `` `{{ oops_channel }}` `` (the sentence describes runtime notification behavior — installation-specific).
  - File: `docs/index.md`, `docs/members.md`, `docs/technicians.md`, `docs/administrators.md`
  - Action: Audit for other user-facing installation-specific literals and replace where the text describes *this installation's* runtime behavior. Do NOT replace literals that document configuration itself (e.g., `administrators.md` line 86 documents the `SLACK_OOPS_CHANNEL` env var and its `#oops` default — keep literal; same for example URLs/ports in deployment instructions). Slack slash command names (`/esb-report` etc.) are fixed in code, not config — keep literal.
  - Notes: Keep the placeholder set minimal: `oops_channel`, `esb_base_url`. Every placeholder used in any .md file MUST exist both in `get_placeholder_values()` and in `mkdocs.yml extra:` (Task 8) — StrictUndefined (runtime) and `mkdocs build --strict` with macros (CI) both fail otherwise, which is the desired sync guarantee.

- [ ] Task 8: mkdocs macros configuration
  - File: `mkdocs.yml`
  - Action: Add:
    ```yaml
    plugins:
      - search
      - macros
    extra:
      oops_channel: '#oops'
      esb_base_url: ''
    ```
  - Notes: CRITICAL — adding a `plugins:` key disables the implicit default `search` plugin, so `search` must be listed explicitly. The `extra:` values are the generic defaults rendered on the public GH Pages site.

- [ ] Task 9: Docs CI workflow
  - File: `.github/workflows/docs.yml`
  - Action: Line 32: change `pip install mkdocs mkdocs-material` → `pip install mkdocs mkdocs-material mkdocs-macros-plugin`.
  - Notes: `mkdocs build --strict` (line 35) stays; macros plugin in strict mode fails the build on undefined placeholders — the CI-side half of the sync guarantee.

- [ ] Task 10: Tests
  - File: `tests/test_views/test_docs_views.py` (NEW)
  - Action: Following `tests/test_views/test_public_views.py` conventions (classes per view, unauthenticated `client` fixture, status + content assertions):
    - `TestDocsPages`: each of the six routes (`/docs/`, `/docs/members`, `/docs/technicians`, `/docs/staff`, `/docs/administrators`, `/docs/about`) returns 200 unauthenticated; unknown slug `/docs/nope` returns 404; every rendered guide contains NO unrendered placeholder (`'{{'` not in decoded response) and NO intra-doc `.md` hrefs (`re.search(r'href="[^"]*\.md', html)` is None).
    - `TestDocsInterpolation`: set `app.config['SLACK_OOPS_CHANNEL'] = '#custom-chan'` BEFORE first render (per-app cache), GET `/docs/staff`, assert `#custom-chan` appears and `#oops` does not appear in the interpolated sentence.
    - `TestDocsAbout`: assert version string from `pyproject.toml` appears (read expected value in the test via `tomllib` so the test doesn't hardcode `0.9.0`); assert GitHub repo link, license mention, online-docs link, and issues link present.
    - `TestDocsImages`: GET an image that exists under `docs/images/` returns 200 with image content-type; GET `/docs/images/../index.md` (traversal) returns 404; GET missing image returns 404.
    - `TestDocsNavLinks`: authenticated page (e.g., `staff_client` GET `/equipment/`) contains `href="/docs/"` in the navbar; public page (`client` GET a QR equipment page via `make_equipment`) contains the footer docs link; kiosk page (`client` GET `/public/kiosk`) does NOT contain `href="/docs/"`.
    - `TestDocsCache`: second GET of the same page returns identical content (sanity) — and the render cache is per-app (fresh app fixture per test means no cross-test bleed; implicitly verified by `TestDocsInterpolation` passing in any test order).
  - Notes: No DB models involved; most tests need only `client`.

- [ ] Task 11: Lint + full test pass
  - File: n/a
  - Action: `make lint` and `make test` green. Manually verify the GH Pages build locally: `venv/bin/pip install mkdocs mkdocs-material mkdocs-macros-plugin && venv/bin/mkdocs build --strict` succeeds.

### Acceptance Criteria

- [ ] AC 1: Given an unauthenticated visitor, when they GET `/docs/`, then the rendered Home guide is returned with HTTP 200 and no login is required.
- [ ] AC 2: Given any of the slugs `members`, `technicians`, `staff`, `administrators`, when a visitor GETs `/docs/<slug>`, then the corresponding guide from `docs/<slug>.md` is rendered as HTML with working tables, admonitions, fenced code blocks, and images.
- [ ] AC 3: Given `SLACK_OOPS_CHANNEL=#equipment-alerts` in the app config, when a visitor GETs `/docs/staff`, then the notification sentence shows `#equipment-alerts` and no `{{ ... }}` placeholder text appears anywhere in the response.
- [ ] AC 4: Given a guide containing a cross-link to another guide (e.g., `members.md`), when the page is rendered, then the link points to `/docs/members` (not a `.md` file) and resolves with HTTP 200.
- [ ] AC 5: Given a guide containing an image reference (`images/<file>.png`), when the page is rendered, then the `<img>` src points to `/docs/images/<file>.png` and that URL serves the image with HTTP 200.
- [ ] AC 6: Given a request for `/docs/images/../<anything>` (path traversal) or a nonexistent image, when the route handles it, then HTTP 404 is returned.
- [ ] AC 7: Given an unknown slug, when a visitor GETs `/docs/whatever`, then HTTP 404 is returned.
- [ ] AC 8: Given the About page at `/docs/about`, when rendered, then it shows the running version (matching `pyproject.toml`), a link to https://github.com/jantman/equipment-status-board, the MIT license with a link, a link to the online GH Pages docs site, and a report-an-issue link.
- [ ] AC 9: Given `pyproject.toml` is unreadable at runtime, when the About page renders, then the version displays as "unknown" and the page still returns HTTP 200.
- [ ] AC 10: Given any authenticated page using `base.html`, when rendered, then the navbar contains a "Docs" link to `/docs/` visible regardless of role; given any public page using `base_public.html` (e.g., a QR equipment page), then a footer link to `/docs/` is present.
- [ ] AC 11: Given any kiosk view (`/public/kiosk`, `/public/kiosk/<area_id>`), when rendered, then NO docs link is present.
- [ ] AC 12: Given the modified `docs/*.md`, `mkdocs.yml`, and docs workflow, when `mkdocs build --strict` runs with `mkdocs-material` and `mkdocs-macros-plugin` installed, then the build succeeds and the GH Pages output renders the generic default values (e.g., `#oops`) where placeholders appear.

## Additional Context

### Dependencies

- **New runtime dependency:** `Markdown>=3.7` (python-markdown) — pure-Python, no system libs, safe addition to the Docker image.
- **New dev/CI dependency:** `mkdocs-macros-plugin>=1.0` — used only by the GH Pages build (`.github/workflows/docs.yml`) and local docs preview.
- **No Dockerfile change needed:** `COPY . .` (line 23) already ships `docs/` and `pyproject.toml`; there is no `.dockerignore`.
- **No DB/migration impact.** No service or model dependencies beyond reading Flask config.

### Testing Strategy

- **Unit/integration:** `tests/test_views/test_docs_views.py` per Task 10 — route status codes, interpolation, link/image rewriting, About content, version fallback, traversal protection, nav/footer link presence, kiosk exclusion.
- **CI:** Existing `make lint` / `make test` via `ci.yml`; docs build verified by `docs.yml` (`mkdocs build --strict` fails on undefined macros — guards placeholder drift).
- **Manual:** `make run`, visit `/docs/` logged-out and logged-in (navbar variant), scan a QR equipment page for the footer link, check `/public/kiosk` has no link, eyeball admonition/table CSS in the rendered Administrators guide (heaviest formatting), confirm About shows the version.

### Notes

- **Risk — placeholder drift:** a placeholder added to a `.md` without a matching value fails *loudly* in both halves (StrictUndefined at runtime/tests; `--strict` macros in docs CI). This is intentional; do not soften to silent defaults.
- **Risk — `plugins:` key in mkdocs.yml:** adding it disables the implicit `search` plugin; `search` must be listed explicitly (Task 8).
- **Risk — Jinja syntax collision:** the five guides currently contain no literal `{{`/`{%` outside intended placeholders, but fenced code blocks in `administrators.md` contain YAML/bash. If a future doc needs a literal `{{`, wrap it in `{% raw %}` — note this in a comment in `docs_service.py`. (mkdocs-macros has the same constraint, so GH Pages CI would also catch it.)
- **Limitation:** docs render uses python-markdown, not mkdocs-material — the built-in site will look simpler than GH Pages (no theme nav/search). Accepted; the sub-nav covers navigation and search is out of scope.
- **Future (out of scope):** docs search; serving `manual_testing.md`; per-role docs landing (e.g., technicians land on their guide); linking the static status page URL once a public URL config exists for it.
