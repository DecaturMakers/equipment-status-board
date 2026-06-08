"""Tests for the built-in docs/help site views (public, no auth)."""

import re
import tomllib
from pathlib import Path

import pytest

from esb import create_app
from esb.services import docs_service

# All five served guide slugs plus the about page.
GUIDE_SLUGS = ['index', 'members', 'technicians', 'staff', 'administrators']
GUIDE_PATHS = {
    'index': '/docs/',
    'members': '/docs/members',
    'technicians': '/docs/technicians',
    'staff': '/docs/staff',
    'administrators': '/docs/administrators',
}
ALL_ROUTES = list(GUIDE_PATHS.values()) + ['/docs/about']

# Placeholder-style pattern: `{{ identifier }}`. NOT a bare `{{` check — the
# administrators guide legitimately renders the literal `{{.State.Health.Status}}`
# docker-inspect example (dotted, no surrounding spaces, raw-wrapped).
PLACEHOLDER_RE = re.compile(r'\{\{\s*\w+\s*\}\}')
MD_HREF_RE = re.compile(r'href="[^"]*\.md[#"]')


class TestDocsPages:
    """Route status codes and absence of unrendered markup."""

    @pytest.mark.parametrize('path', ALL_ROUTES)
    def test_route_returns_200_unauthenticated(self, client, path):
        assert client.get(path).status_code == 200

    def test_index_slug_redirects_to_canonical(self, client):
        resp = client.get('/docs/index')
        assert resp.status_code == 301
        assert resp.headers['Location'].endswith('/docs/')

    def test_unknown_slug_404(self, client):
        assert client.get('/docs/nope').status_code == 404

    def test_version_slug_404_even_after_about_rendered(self, client):
        """Regression: the version value lives in the same per-app cache as
        page renders; a non-slug like 'version' must stay a 404 after the About
        page has populated that cache (no namespace collision)."""
        assert client.get('/docs/about').status_code == 200
        assert client.get('/docs/version').status_code == 404

    def test_missing_placeholder_config_fails_loud_not_404(self, app, client):
        """Regression: a missing placeholder config key must fail loud (a 500
        in production), not be masked as a 404 by an over-broad except in the
        view. Under TESTING the exception propagates to the caller."""
        del app.config['SLACK_OOPS_CHANNEL']
        with pytest.raises(KeyError):
            client.get('/docs/staff')

    @pytest.mark.parametrize('path', list(GUIDE_PATHS.values()))
    def test_no_unrendered_placeholder(self, client, path):
        html = client.get(path).data.decode()
        assert PLACEHOLDER_RE.search(html) is None

    @pytest.mark.parametrize('path', list(GUIDE_PATHS.values()))
    def test_no_intra_doc_md_hrefs(self, client, path):
        html = client.get(path).data.decode()
        assert MD_HREF_RE.search(html) is None


class TestDocsRendering:
    """Markdown features render as proper HTML (AC 2)."""

    def test_administrators_renders_table_admonition_code(self, client):
        html = client.get('/docs/administrators').data.decode()
        assert '<table>' in html
        # python-markdown always emits a qualifier, e.g. class="admonition warning"
        assert 'class="admonition' in html
        assert '<pre>' in html and '<code>' in html
        # The raw-wrapped docker-inspect literal survives intact.
        assert '{{.State.Health.Status}}' in html

    def test_guide_with_images_has_img_tags(self, client):
        html = client.get('/docs/members').data.decode()
        assert '<img' in html


class TestDocsAnchors:
    """Intra-page fragment links resolve to an id in the same document (toc)."""

    @pytest.mark.parametrize('path', list(GUIDE_PATHS.values()))
    def test_fragment_links_have_matching_ids(self, client, path):
        html = client.get(path).data.decode()
        ids = set(re.findall(r'id="([^"]+)"', html))
        for fragment in re.findall(r'href="#([^"]+)"', html):
            assert fragment in ids, f'no id for #{fragment} on {path}'


class TestDocsLinkResolution:
    """Rewritten intra-doc links and image srcs all resolve (AC 4, AC 5)."""

    @pytest.mark.parametrize('path', list(GUIDE_PATHS.values()))
    def test_internal_doc_links_resolve(self, client, path):
        html = client.get(path).data.decode()
        for href in re.findall(r'href="(/docs/[^"]*)"', html):
            target = href.split('#')[0]
            assert client.get(target).status_code == 200, target

    @pytest.mark.parametrize('path', list(GUIDE_PATHS.values()))
    def test_image_srcs_resolve(self, client, path):
        html = client.get(path).data.decode()
        for src in re.findall(r'<img[^>]+src="([^"]+)"', html):
            assert client.get(src).status_code == 200, src

    @pytest.mark.parametrize('path', list(GUIDE_PATHS.values()))
    def test_cross_page_anchors_resolve(self, client, path):
        """A rewritten cross-page link `/docs/<slug>#frag` must point at an
        id that actually exists on the target page (not stripped before the
        check, unlike test_internal_doc_links_resolve). No cross-page anchors
        exist today; this guards the case when one is added."""
        html = client.get(path).data.decode()
        for href in re.findall(r'href="(/docs/[^"]*#[^"]+)"', html):
            target, fragment = href.split('#', 1)
            target_html = client.get(target).data.decode()
            ids = set(re.findall(r'id="([^"]+)"', target_html))
            assert fragment in ids, f'{href} on {path} has no matching id'


class TestDocsSubnav:
    """Sub-nav completeness on every docs page (AC 14)."""

    @pytest.mark.parametrize('path', ALL_ROUTES)
    def test_subnav_links_all_pages(self, client, path):
        html = client.get(path).data.decode()
        assert 'href="/docs/"' in html
        for slug in ['members', 'technicians', 'staff', 'administrators']:
            assert f'href="/docs/{slug}"' in html
        assert 'href="/docs/about"' in html

    @pytest.mark.parametrize('path', ALL_ROUTES)
    def test_exactly_one_active(self, client, path):
        html = client.get(path).data.decode()
        # Unauthenticated docs pages extend base_public.html (no navbar), so the
        # only nav-links are in the docs sub-nav.
        assert html.count('nav-link active') == 1


class TestDocsInterpolation:
    """Placeholder interpolation uses live config (AC 3)."""

    def test_custom_oops_channel_rendered(self, app, client):
        # Set BEFORE first render (cache is per-app, populated on first GET).
        app.config['SLACK_OOPS_CHANNEL'] = '#custom-chan'
        html = client.get('/docs/staff').data.decode()
        assert '#custom-chan' in html
        assert '#oops' not in html


class TestDocsAbout:
    """About body shows version + project links (AC 8)."""

    def test_about_body_markers(self, client):
        html = client.get('/docs/about').data.decode()
        # Read version via tomllib rather than hardcoding it.
        pyproject = Path(__file__).resolve().parents[2] / 'pyproject.toml'
        with open(pyproject, 'rb') as fh:
            version = tomllib.load(fh)['project']['version']
        assert version in html
        assert 'https://github.com/jantman/equipment-status-board/issues' in html
        assert 'https://jantman.github.io/equipment-status-board/' in html


class TestDocsVersionFallback:
    """Unreadable pyproject.toml → version 'unknown' (AC 9)."""

    def test_version_unknown_on_missing_pyproject(self, client, monkeypatch):
        # _pyproject_path is a function; patch the function, not a path value.
        monkeypatch.setattr(
            docs_service, '_pyproject_path',
            lambda: Path('/nonexistent/pyproject.toml'),
        )
        resp = client.get('/docs/about')
        assert resp.status_code == 200
        assert b'unknown' in resp.data


class TestDocsImages:
    """Image serving, cache header, traversal protection (AC 5, AC 6)."""

    def test_existing_image_served_with_cache_header(self, client):
        resp = client.get('/docs/images/status-dashboard.png')
        assert resp.status_code == 200
        assert resp.content_type.startswith('image/')
        assert 'max-age=86400' in resp.headers.get('Cache-Control', '')

    def test_traversal_404(self, client):
        assert client.get('/docs/images/../index.md').status_code == 404

    def test_missing_image_404(self, client):
        assert client.get('/docs/images/does-not-exist.png').status_code == 404


class TestDocsNavLinks:
    """Header navbar / footer docs link presence + kiosk exclusion (AC 10, 11)."""

    def test_authed_navbar_has_docs_link(self, staff_client):
        html = staff_client.get('/equipment/').data.decode()
        assert 'href="/docs/"' in html

    def test_public_page_has_footer_docs_link(self, client, make_equipment):
        equipment = make_equipment(name='Drill Press')
        html = client.get(f'/public/equipment/{equipment.id}').data.decode()
        assert 'href="/docs/"' in html

    def test_kiosk_all_has_no_docs_link(self, client):
        resp = client.get('/public/kiosk')
        assert resp.status_code == 200
        assert 'href="/docs/"' not in resp.data.decode()

    def test_kiosk_area_has_no_docs_link(self, client, make_area):
        area = make_area(name='Workshop')
        resp = client.get(f'/public/kiosk/{area.id}')
        assert resp.status_code == 200
        assert 'href="/docs/"' not in resp.data.decode()


class TestDocsCache:
    """Render cache is per-app, not module-level."""

    def test_cache_isolated_between_apps(self):
        app_a = create_app('testing')
        app_a.config['SLACK_OOPS_CHANNEL'] = '#chan-a'
        app_b = create_app('testing')
        app_b.config['SLACK_OOPS_CHANNEL'] = '#chan-b'

        html_a = app_a.test_client().get('/docs/staff').data.decode()
        html_b = app_b.test_client().get('/docs/staff').data.decode()

        assert '#chan-a' in html_a and '#chan-b' not in html_a
        assert '#chan-b' in html_b and '#chan-a' not in html_b

    def test_second_get_same_app_consistent(self, client):
        first = client.get('/docs/staff').data
        second = client.get('/docs/staff').data
        assert first == second
