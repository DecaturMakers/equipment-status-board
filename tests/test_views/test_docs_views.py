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
        # The oops-channel placeholder lives in the Slack-gated Notification
        # Triggers section, so Slack must be enabled for it to render.
        app.config['SLACK_OOPS_CHANNEL'] = '#custom-chan'
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-test'
        app.config['SLACK_APP_TOKEN'] = 'xapp-test'
        html = client.get('/docs/staff').data.decode()
        assert '#custom-chan' in html
        assert '#oops' not in html


# Config that flips each gated feature on. Slack needs BOTH tokens.
SLACK_ON = {'SLACK_BOT_TOKEN': 'xoxb-x', 'SLACK_APP_TOKEN': 'xapp-x'}
QR_ON = {'ESB_BASE_URL': 'https://esb.example.com'}
STATIC_ON = {'STATIC_PAGE_PUBLIC_URL': 'https://status.example.com/'}


def _render(slug, overrides):
    """Render a guide in a fresh app so per-app caching never leaks config.

    Config must be set before the first GET (the render cache is populated on
    first request and assumes startup-fixed config).
    """
    app = create_app('testing')
    app.config.update(overrides)
    return app.test_client().get(GUIDE_PATHS[slug]).data.decode()


class TestDocsFeatureGating:
    """Feature sections appear only when the feature is actually configured."""

    def test_slack_sections_hidden_when_disabled(self):
        html = _render('members', {})
        assert '/esb-status' not in html
        assert 'Checking Status via Slack' not in html

    def test_slack_sections_shown_when_enabled(self):
        html = _render('members', SLACK_ON)
        assert '/esb-status' in html
        assert 'Checking Status via Slack' in html

    def test_technician_slack_flows_gated(self):
        assert 'Using Slack Commands' not in _render('technicians', {})
        assert 'Using Slack Commands' in _render('technicians', SLACK_ON)

    def test_index_slack_feature_gated(self):
        assert '/esb-repair' not in _render('index', {})
        assert '/esb-repair' in _render('index', SLACK_ON)

    def test_qr_section_hidden_when_base_url_unset(self):
        assert 'Using QR Code Equipment Pages' not in _render('members', {})

    def test_qr_section_shown_when_base_url_set(self):
        assert 'Using QR Code Equipment Pages' in _render('members', QR_ON)

    def test_static_page_section_gated_on_members(self):
        assert 'Static Status Page' not in _render('members', {})
        assert 'Static Status Page' in _render('members', STATIC_ON)

    def test_static_page_section_gated_on_staff(self):
        # STATIC_PAGE_PUBLIC_URL governs both the Members and Staff guides.
        assert 'Static Status Page' not in _render('staff', {})
        assert 'Static Status Page' in _render('staff', STATIC_ON)


class TestDocsValueSubstitution:
    """Installation-specific values replace the old generic phrases."""

    def test_base_url_substituted_when_set(self):
        assert 'https://esb.example.com' in _render('members', QR_ON)

    def test_base_url_fallback_phrase_when_unset(self):
        html = _render('members', {})
        assert 'the Equipment Status Board URL provided by your makerspace' in html

    def test_static_page_url_rendered(self):
        assert 'https://status.example.com/' in _render('members', STATIC_ON)

    def test_qr_disabled_notice_only_when_disabled(self):
        assert 'ESB_BASE_URL not configured' in _render('staff', {})
        assert 'ESB_BASE_URL not configured' not in _render('staff', QR_ON)


class TestDocsBranding:
    """Org name/URL/blurb are configurable (defaults preserve current text)."""

    def test_org_defaults_rendered(self):
        html = _render('index', {})
        assert 'Decatur Makers' in html
        assert 'https://decaturmakers.org' in html
        assert '600 members' in html

    def test_org_overridden(self):
        html = _render('index', {
            'ORG_NAME': 'Acme Makerspace',
            'ORG_URL': 'https://acme.example.org',
            'ORG_BLURB': '',
        })
        assert 'Acme Makerspace' in html
        assert 'https://acme.example.org' in html
        # Org branding (link + blurb) is overridden. The copyright footer's fixed
        # "Jason Antman / Decatur Makers" attribution is intentionally NOT white-labeled.
        assert 'https://decaturmakers.org' not in html
        assert '600 members' not in html  # blurb omitted when empty


class TestDocsWifiCacheInvalidation:
    """WiFi SSID is DB-backed and mutable; the page cache must be evictable."""

    def test_wifi_ssid_reflected_after_invalidation(self, app, client):
        from esb.services import config_service, docs_service

        # QR section (which contains the WiFi note) must be enabled.
        app.config['ESB_BASE_URL'] = 'https://esb.example.com'
        first = client.get('/docs/members').data.decode()
        assert 'makerspace WiFi' in first  # generic branch, no SSID configured
        assert 'DM-Members' not in first

        with app.app_context():
            config_service.set_config('wifi_ssid', 'DM-Members', changed_by='test')
            docs_service.invalidate_page_cache()

        second = client.get('/docs/members').data.decode()
        assert 'DM-Members' in second

    def test_invalidate_preserves_version_meta(self, app, client):
        """invalidate_page_cache() drops page renders but not the cached
        version (an env-immutable ('meta', 'version') entry)."""
        from esb.services import docs_service

        client.get('/docs/about')  # populates ('meta', 'version')
        client.get('/docs/staff')  # populates ('page', 'staff')
        with app.app_context():
            docs_service.invalidate_page_cache()
            cache = app.extensions['docs_cache']
            assert ('meta', 'version') in cache
            assert not any(k[0] == 'page' for k in cache)

    def test_invalidate_swaps_dict_leaving_old_intact(self, app, client):
        """invalidate_page_cache() replaces the dict rather than mutating in
        place, so a concurrent reader holding the old reference never sees a
        key vanish mid-lookup (the 2-thread-worker race)."""
        from esb.services import docs_service

        client.get('/docs/staff')  # populates ('page', 'staff')
        with app.app_context():
            old = app.extensions['docs_cache']
            docs_service.invalidate_page_cache()
            assert app.extensions['docs_cache'] is not old  # swapped, not mutated
            assert ('page', 'staff') in old  # old reference still complete


class TestDocsWifiQueryResilience:
    """A missing/failed app_config query must not 500 the public docs."""

    def test_missing_app_config_table_fails_safe_and_logs(self, caplog):
        docs_service._wifi_query_failed_once = False  # reset per-process latch
        app = create_app('testing')  # tables deliberately NOT created
        with caplog.at_level('WARNING', logger='esb.services.docs_service'):
            resp = app.test_client().get('/docs/members')
        assert resp.status_code == 200  # fail-safe, not a 500
        assert any('wifi_ssid' in r.message for r in caplog.records)


class TestDocsPlaceholderParity:
    """Drift guard: every runtime placeholder has a mkdocs.yml extra default."""

    def test_mkdocs_extra_keys_match_placeholder_values(self):
        import yaml

        app = create_app('testing')
        with app.app_context():
            runtime_keys = set(docs_service.get_placeholder_values().keys())
        mkdocs_path = Path(__file__).resolve().parents[2] / 'mkdocs.yml'
        with open(mkdocs_path) as fh:
            extra_keys = set(yaml.safe_load(fh)['extra'].keys())
        assert runtime_keys == extra_keys


class TestDocsAbout:
    """About body shows version + project links (AC 8)."""

    def test_about_body_markers(self, client):
        html = client.get('/docs/about').data.decode()
        # Read version via tomllib rather than hardcoding it.
        pyproject = Path(__file__).resolve().parents[2] / 'pyproject.toml'
        with open(pyproject, 'rb') as fh:
            version = tomllib.load(fh)['project']['version']
        assert version in html
        assert 'https://github.com/DecaturMakers/equipment-status-board/issues' in html
        assert 'https://decaturmakers.github.io/equipment-status-board/' in html


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
        # Slack enabled so the oops-channel placeholder (in the Slack-gated
        # Notification Triggers section) actually renders.
        app_a = create_app('testing')
        app_a.config.update(SLACK_BOT_TOKEN='x', SLACK_APP_TOKEN='x', SLACK_OOPS_CHANNEL='#chan-a')
        app_b = create_app('testing')
        app_b.config.update(SLACK_BOT_TOKEN='x', SLACK_APP_TOKEN='x', SLACK_OOPS_CHANNEL='#chan-b')

        html_a = app_a.test_client().get('/docs/staff').data.decode()
        html_b = app_b.test_client().get('/docs/staff').data.decode()

        assert '#chan-a' in html_a and '#chan-b' not in html_a
        assert '#chan-b' in html_b and '#chan-a' not in html_b

    def test_second_get_same_app_consistent(self, client):
        first = client.get('/docs/staff').data
        second = client.get('/docs/staff').data
        assert first == second
