"""Docs rendering service.

Renders the repo-root ``docs/*.md`` markdown files (the same source the mkdocs
GitHub Pages site builds) at runtime with installation-specific config values
interpolated, for the public ``/docs/`` blueprint.

Trust boundary: rendered HTML is emitted into templates via ``|safe`` (it is
markdown-generated HTML, not auto-escaped). This is acceptable because BOTH
inputs are trusted: the markdown content ships with the repo (no user input),
and the interpolated placeholder values (``get_placeholder_values()``) come
from environment config set by the deployment administrator, not from end
users. They are injected unescaped. If a future placeholder ever carries
non-admin-controlled data, escaping MUST be added before it reaches the
template.

Placeholder / raw-block rules: placeholders use Jinja syntax (``{{ name }}``)
and every name MUST exist both here in ``get_placeholder_values()`` and in
``mkdocs.yml`` ``extra:`` — StrictUndefined here and ``on_undefined: strict``
in the macros plugin both fail loudly on drift, which is the desired sync
guarantee. Any literal ``{{``/``{%``/``{#`` that should appear verbatim in doc
content (e.g. the docker-inspect example in administrators.md) MUST be wrapped
in ``{% raw %}``/``{% endraw %}`` — note ``{#...#}`` is a Jinja COMMENT
delimiter that both renderers silently swallow rather than error on.

Feature conditionals: beyond simple value substitution, the guides use Jinja
``{% if feature_enabled %}…{% endif %}`` blocks to tailor the live site to what
a deployment actually has configured (Slack, QR codes, the static status page,
WiFi info). The booleans below derive from live config. On the public GitHub
Pages build these booleans default to ``true`` in ``mkdocs.yml`` ``extra:`` so
the general-reference site documents every feature.

Cache & mutable config: rendered pages are cached per-app under ``('page',
slug)`` keys. Most placeholder values come from env config fixed at startup, but
the WiFi values come from the runtime-mutable ``app_config`` table. Whenever a
docs-relevant ``AppConfig`` key changes, the admin config view calls
``invalidate_page_cache()`` so the next render reflects the new value rather than
serving stale HTML.

Supported markdown extensions (runtime): ``tables``, ``fenced_code``,
``admonition``, ``toc`` — the only features the five guides use today.
``mkdocs.yml`` additionally enables ``pymdownx.details``,
``pymdownx.superfences``, ``attr_list``, ``md_in_html`` which this renderer does
NOT support: a future doc edit adopting them would build green on GH Pages but
render as literal text here. Align the extension sets (or add
``pymdown-extensions`` at runtime) if/when that happens.
"""

import re
import tomllib
from collections import OrderedDict
from pathlib import Path

import jinja2
import markdown
from flask import current_app

# Ordered slug → page metadata. Mirrors the ``nav:`` in mkdocs.yml.
# manual_testing.md and original_requirements_doc.md are deliberately excluded
# (not in the mkdocs nav).
DOC_PAGES = OrderedDict([
    ('index', {'file': 'index.md', 'title': 'Home'}),
    ('members', {'file': 'members.md', 'title': 'Members Guide'}),
    ('technicians', {'file': 'technicians.md', 'title': 'Technicians Guide'}),
    ('staff', {'file': 'staff.md', 'title': 'Staff Guide'}),
    ('administrators', {'file': 'administrators.md', 'title': 'Administrators Guide'}),
])

# About-page constants.
GITHUB_URL = 'https://github.com/jantman/equipment-status-board'
DOCS_SITE_URL = 'https://jantman.github.io/equipment-status-board/'
ISSUES_URL = GITHUB_URL + '/issues'
LICENSE_NAME = 'MIT'
LICENSE_URL = GITHUB_URL + '/blob/main/LICENSE'

MARKDOWN_EXTENSIONS = ['tables', 'fenced_code', 'admonition', 'toc']

# Matches inter-doc markdown links to a served page, e.g. ``(members.md)`` or
# ``(staff.md#anchor)``. Only the five served page names are rewritten — no
# guide links to a non-served .md file (the no-.md-href test guards future
# cases).
_SERVED_PAGE_NAMES = [meta['file'] for meta in DOC_PAGES.values()]
_LINK_RE = re.compile(
    r'\((' + '|'.join(re.escape(name) for name in _SERVED_PAGE_NAMES) + r')(#[^)]*)?\)'
)
# Matches image references, e.g. ``(images/foo.png)``.
_IMAGE_RE = re.compile(r'\(images/([^)]+)\)')


def get_docs_dir():
    """Return the repo-root ``docs/`` directory.

    A function, not a module constant: ``current_app`` raises RuntimeError
    outside an app context (e.g. at import time). ``Dockerfile`` ``COPY . .``
    ships this directory into the image at ``/app/docs``.
    """
    return Path(current_app.root_path).parent / 'docs'


def _pyproject_path():
    """Return the repo-root ``pyproject.toml`` path.

    Separate function so tests can monkeypatch it to exercise the version
    fallback path.
    """
    return Path(current_app.root_path).parent / 'pyproject.toml'


def get_placeholder_values():
    """Return the placeholder interpolation dict from live config.

    This dict is the single extension point for placeholders and feature
    conditionals; every key here MUST also exist in mkdocs.yml ``extra:`` (the
    drift guard). ``oops_channel`` is read with ``[]`` (not ``.get``) so a
    missing key fails loud — a deliberately tested invariant.

    Values are derived from env config (fixed at startup) except the WiFi keys,
    which come from the runtime-mutable ``app_config`` table; see
    ``invalidate_page_cache()``.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from esb.extensions import db
    from esb.services import config_service

    cfg = current_app.config
    base_url = cfg.get('ESB_BASE_URL', '')
    static_page_url = cfg.get('STATIC_PAGE_PUBLIC_URL', '')
    # The docs site is public and unauthenticated; it must stay up even on a
    # fresh deployment that has not yet run `flask db upgrade` (no app_config
    # table) or during a transient DB outage. Treat any DB failure as "WiFi not
    # configured" rather than 500-ing every guide page.
    try:
        wifi_ssid = config_service.get_config('wifi_ssid', '')
    except SQLAlchemyError:
        db.session.rollback()
        wifi_ssid = ''
    return {
        # Values
        'oops_channel': cfg['SLACK_OOPS_CHANNEL'],
        'base_url': base_url,
        # Human-friendly fallback so an unset base URL never renders a broken
        # sentence ("Navigate to  in your browser").
        'base_url_display': base_url or 'the Equipment Status Board URL provided by your makerspace',
        'static_page_url': static_page_url,
        'wifi_ssid': wifi_ssid,
        'org_name': cfg.get('ORG_NAME', ''),
        'org_url': cfg.get('ORG_URL', ''),
        'org_blurb': cfg.get('ORG_BLURB', ''),
        # Feature conditionals
        'qr_enabled': bool(base_url),
        'slack_enabled': bool(cfg.get('SLACK_BOT_TOKEN') and cfg.get('SLACK_APP_TOKEN')),
        'static_page_enabled': bool(static_page_url),
        'wifi_configured': bool(wifi_ssid),
    }


def invalidate_page_cache():
    """Evict cached rendered pages so the next render re-reads live config.

    Call after a docs-relevant ``AppConfig`` change (WiFi settings). Only the
    ``('page', …)`` entries are dropped; the ``('meta', 'version')`` entry (env-
    immutable) is left intact. Safe no-op if nothing has been cached yet.
    """
    cache = current_app.extensions.get('docs_cache')
    if not cache:
        return
    for key in [k for k in cache if k[0] == 'page']:
        del cache[key]


def _file_to_slug():
    """Map served markdown filename → slug (for link rewriting)."""
    return {meta['file']: slug for slug, meta in DOC_PAGES.items()}


def _rewrite_links(text):
    """Rewrite inter-doc links and image refs in markdown source.

    ``(members.md)`` → ``(/docs/members)``, ``(staff.md#anchor)`` →
    ``(/docs/staff#anchor)``, ``(images/foo.png)`` → ``(/docs/images/foo.png)``.
    """
    file_to_slug = _file_to_slug()

    def _link_sub(match):
        slug = file_to_slug[match.group(1)]
        anchor = match.group(2) or ''
        return f'(/docs/{slug}{anchor})'

    text = _LINK_RE.sub(_link_sub, text)
    text = _IMAGE_RE.sub(lambda m: f'(/docs/images/{m.group(1)})', text)
    return text


def render_page(slug):
    """Render a docs page, returning ``(title, html)``.

    Raises ``KeyError`` for a slug not in ``DOC_PAGES`` (→ 404 in the view). A
    slug that IS in ``DOC_PAGES`` but whose file is missing/unreadable lets the
    ``OSError`` propagate (→ 500): that's a broken deployment, and fail-loud
    applies. Results are cached per-app (config is fixed at startup).
    """
    # Look up metadata BEFORE consulting the cache so an unknown slug always
    # raises KeyError (→ 404) regardless of cache state. Page results are stored
    # under ('page', slug) keys so they cannot collide with get_version()'s
    # ('meta', 'version') entry in the same dict.
    meta = DOC_PAGES[slug]  # KeyError for unknown slug → 404
    title = meta['title']

    cache = current_app.extensions.setdefault('docs_cache', {})
    cache_key = ('page', slug)
    if cache_key in cache:
        return cache[cache_key]

    path = get_docs_dir() / meta['file']
    text = path.read_text(encoding='utf-8')  # OSError propagates → 500

    # (1) interpolate placeholders with StrictUndefined so a typo'd placeholder
    # fails loudly rather than rendering ``{{ ... }}`` to users; honor
    # {% raw %} blocks (needed for the docker-inspect example in
    # administrators.md).
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    text = env.from_string(text).render(**get_placeholder_values())

    # (2) rewrite inter-doc links and image refs in the markdown source.
    text = _rewrite_links(text)

    # (3) convert markdown → HTML.
    html = markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)

    result = (title, html)
    cache[cache_key] = result
    return result


def get_version():
    """Return the running version from ``pyproject.toml`` via stdlib tomllib.

    ``importlib.metadata`` will NOT work — the Docker image copies source and
    installs only ``requirements.txt``; the package itself is never
    pip-installed. Cached per-app; returns ``'unknown'`` on any failure.
    """
    cache = current_app.extensions.setdefault('docs_cache', {})
    cache_key = ('meta', 'version')
    if cache_key in cache:
        return cache[cache_key]

    try:
        with open(_pyproject_path(), 'rb') as fh:
            data = tomllib.load(fh)
        version = data['project']['version']
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        version = 'unknown'

    cache[cache_key] = version
    return version


def nav_pages():
    """Return ``[(slug, title), ...]`` for the sub-nav, derived from DOC_PAGES."""
    return [(slug, meta['title']) for slug, meta in DOC_PAGES.items()]
