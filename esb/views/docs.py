"""Built-in docs/help site (public, no auth).

Serves the repo-root ``docs/*.md`` guides rendered server-side with
installation-specific config interpolated, plus an About page and the docs
images. Fully public, matching the status dashboard and QR pages.
"""

from flask import Blueprint, abort, redirect, render_template, url_for

docs_bp = Blueprint('docs', __name__, url_prefix='/docs')


@docs_bp.route('/')
def index():
    """Docs home (the index guide)."""
    from esb.services import docs_service

    title, html = docs_service.render_page('index')
    return render_template(
        'docs/page.html',
        title=title,
        content=html,
        nav_pages=docs_service.nav_pages(),
        current_slug='index',
    )


@docs_bp.route('/about')
def about():
    """About page: version + project links."""
    from esb.services import docs_service

    return render_template(
        'docs/about.html',
        version=docs_service.get_version(),
        github_url=docs_service.GITHUB_URL,
        docs_site_url=docs_service.DOCS_SITE_URL,
        issues_url=docs_service.ISSUES_URL,
        license_name=docs_service.LICENSE_NAME,
        license_url=docs_service.LICENSE_URL,
        nav_pages=docs_service.nav_pages(),
        current_slug='about',
    )


@docs_bp.route('/<slug>')
def page(slug):
    """Render a docs guide by slug; 404 for unknown slugs."""
    from esb.services import docs_service

    # /docs/index is a duplicate URL for the Home page (mis-highlights the
    # sub-nav); redirect it to the canonical /docs/.
    if slug == 'index':
        return redirect(url_for('docs.index'), code=301)

    # Distinguish an unknown slug (404) from a genuine error inside rendering
    # (e.g. a missing config key, an unreadable file) which must fail loud as a
    # 500 rather than be masked as a 404 by a blanket KeyError catch.
    if slug not in docs_service.DOC_PAGES:
        abort(404)

    title, html = docs_service.render_page(slug)

    return render_template(
        'docs/page.html',
        title=title,
        content=html,
        nav_pages=docs_service.nav_pages(),
        current_slug=slug,
    )


@docs_bp.route('/images/<path:filename>')
def image(filename):
    """Serve docs images. send_from_directory handles path-traversal protection.

    Explicit 1-day cache: the full-size screenshot PNGs only change with
    releases; without max_age Flask sends revalidate-only headers.
    """
    from flask import send_from_directory

    from esb.services import docs_service

    images_dir = docs_service.get_docs_dir() / 'images'
    return send_from_directory(images_dir, filename, max_age=86400)
