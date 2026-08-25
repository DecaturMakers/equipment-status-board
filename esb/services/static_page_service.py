"""Static status page generation and push service."""

import logging
import os
import posixpath
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app, render_template

from esb.utils.logging import log_mutation

logger = logging.getLogger(__name__)

HTML_CONTENT_TYPE = 'text/html; charset=utf-8'
JSON_CONTENT_TYPE = 'application/json; charset=utf-8'
CACHE_CONTROL = 'no-cache, no-store, must-revalidate'


def _compute_generated_at() -> tuple[str, int]:
    """Compute the generation timestamp string and year in the system's local timezone.

    Returns:
        (timestamp_str, year) where timestamp_str is formatted like
        '2026-05-11 14:32:15 EDT'. year is the local-tz year of the
        same instant (datetime.astimezone() returns a datetime whose
        .year reflects the converted zone, not the source UTC year).

    Raises:
        RuntimeError: if the local timezone has no resolvable tzname
            (indicates the runtime is missing tzdata, e.g. a stripped
            Docker image). The Dockerfile pins tzdata; this guard is
            defense-in-depth against future image-content drift.
    """
    dt = datetime.now().astimezone()
    tzname = dt.tzname()
    if not tzname:
        raise RuntimeError(
            "Local timezone has no resolvable tzname; tzdata may be missing."
        )
    return (dt.strftime('%Y-%m-%d %H:%M:%S ') + tzname, dt.year)


def generate() -> str:
    """Render the static status page with current equipment status data.

    Uses status_service.get_area_status_dashboard() for data and renders
    the public/static_page.html Jinja2 template within the Flask app context.

    Returns:
        Rendered HTML string (self-contained, no external dependencies).
    """
    from esb.models.repair_record import REPAIR_SEVERITIES
    from esb.services import status_service

    areas = status_service.get_area_status_dashboard()
    generated_at, generated_year = _compute_generated_at()
    return render_template(
        'public/static_page.html',
        areas=areas,
        generated_at=generated_at,
        generated_year=generated_year,
        repair_severities=REPAIR_SEVERITIES,
    )


def generate_reservations() -> tuple[str, str]:
    """Render the standalone reservation calendar and its anonymous JSON data."""
    import json

    from esb.services import reservation_read_service
    from esb.utils.timezones import MAKERSPACE_TIMEZONE, utc_naive_to_local

    now = datetime.now(UTC)
    availability = reservation_read_service.get_public_availability(now=now)
    columns = []
    events = []
    for equipment in availability['equipment']:
        slug = equipment['reservation_slug']
        columns.append({'id': slug, 'name': equipment['name']})
        for reservation in equipment['reservations']:
            starts_at = datetime.fromisoformat(reservation['starts_at']).replace(tzinfo=None)
            ends_at = datetime.fromisoformat(reservation['ends_at']).replace(tzinfo=None)
            events.append({
                'resource': slug,
                'start': utc_naive_to_local(starts_at).replace(tzinfo=None).isoformat(timespec='seconds'),
                'end': utc_naive_to_local(ends_at).replace(tzinfo=None).isoformat(timespec='seconds'),
                'text': 'Reserved',
                'backColor': '#2f6f73',
                'barColor': '#164e52',
                'fontColor': '#ffffff',
            })

    data = {
        'generatedAt': now.isoformat(),
        'timeZone': str(MAKERSPACE_TIMEZONE),
        'startDate': now.astimezone(MAKERSPACE_TIMEZONE).date().isoformat(),
        'columns': columns,
        'events': events,
    }
    daypilot_source = (Path(current_app.static_folder) / 'js' / 'daypilot-javascript.min.js').read_text(
        encoding='utf-8'
    )
    html = render_template(
        'public/static_reservations.html',
        daypilot_source=daypilot_source,
        generated_year=now.astimezone(MAKERSPACE_TIMEZONE).year,
    )
    return html, json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def push(html_content: str) -> None:
    """Push the rendered static page to the configured destination.

    Dispatches to _push_local(), _push_s3(), or _push_gcs() based on
    STATIC_PAGE_PUSH_METHOD config value. For the s3 backend, when the
    CLOUDFRONT_DISTRIBUTION_ID config is set, a CloudFront invalidation
    is issued for the uploaded key after each successful upload.

    Args:
        html_content: The rendered HTML string to push.

    Raises:
        RuntimeError: if push method is unknown, target is empty, or push fails.
    """
    method = current_app.config.get('STATIC_PAGE_PUSH_METHOD', 'local')
    target = current_app.config.get('STATIC_PAGE_PUSH_TARGET', '')

    if not target:
        raise RuntimeError('STATIC_PAGE_PUSH_TARGET is not configured')

    invalidation_id: str | None = None
    if method == 'local':
        _push_local(html_content, target, 'index.html')
    elif method == 's3':
        invalidation_id = _push_s3(html_content, target)
    elif method == 'gcs':
        _push_gcs(html_content, target)
    else:
        raise RuntimeError(f'Unknown STATIC_PAGE_PUSH_METHOD: {method!r}')

    mutation_data: dict = {'method': method, 'target': target}
    if invalidation_id:
        mutation_data['cloudfront_invalidation_id'] = invalidation_id
    log_mutation('static_page.pushed', 'system', mutation_data)

    logger.info('Static page pushed via %s to %s', method, target)


def _push_local(content: str, target_path: str, filename: str) -> None:
    """Write the static page HTML to a local directory.

    Writes to {target_path}/index.html, creating the directory if needed.

    Args:
        html_content: Rendered HTML string.
        target_path: Directory path to write to.

    Raises:
        RuntimeError: if file write fails.
    """
    try:
        os.makedirs(target_path, exist_ok=True)
        output_path = os.path.join(target_path, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info('Static page written to %s', output_path)
    except OSError as e:
        raise RuntimeError(f'Failed to write static page to {target_path}: {e}') from e


def _object_target(target: str, filename: str | None = None) -> tuple[str, str]:
    """Return bucket and key, placing named artifacts beside the configured key."""
    parts = target.split('/', 1)
    bucket = parts[0]
    if not bucket:
        raise RuntimeError(f'Invalid object target {target!r}: bucket name is empty')
    configured_key = parts[1] if len(parts) > 1 and parts[1] else 'index.html'
    if filename:
        key = posixpath.join(posixpath.dirname(configured_key), filename)
    else:
        key = configured_key
    return bucket, key


def _push_s3(
    content: str,
    target: str,
    *,
    filename: str | None = None,
    content_type: str = HTML_CONTENT_TYPE,
    invalidate: bool = True,
) -> str | None:
    """Upload the static page HTML to an S3 bucket.

    Target format: "bucket-name/optional/key/path" (key defaults to index.html
    if target ends with / or has no key component).

    Invalidation is unconditional (no pre-upload diff guard) so that a worker
    retry after a CloudFront failure re-attempts the invalidation instead of
    short-circuiting because the bucket already holds the new bytes.

    Args:
        html_content: Rendered HTML string.
        target: S3 target in format "bucket/key".

    Returns:
        CloudFront invalidation ID, or None if no distribution was configured.

    Raises:
        RuntimeError: if boto3 is missing, the target is malformed, the S3
            upload fails, or the CloudFront invalidation fails.
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError as e:
        raise RuntimeError('boto3 is required for S3 push method. Install it with: pip install boto3') from e

    try:
        bucket, key = _object_target(target, filename)
    except RuntimeError as e:
        raise RuntimeError(str(e).replace('object target', 'S3 target')) from e

    try:
        s3 = boto3.client('s3')
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType=content_type,
            CacheControl=CACHE_CONTROL,
        )
        logger.info('Static page uploaded to s3://%s/%s', bucket, key)
    except NoCredentialsError as e:
        raise RuntimeError('AWS credentials not configured for S3 push') from e
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = e.response['Error']['Message']
        raise RuntimeError(f'S3 upload failed ({error_code}): {error_msg}') from e

    distribution_id = current_app.config.get('CLOUDFRONT_DISTRIBUTION_ID', '')
    if distribution_id and invalidate:
        return _create_cloudfront_invalidation(distribution_id, [key])
    return None


def _create_cloudfront_invalidation(distribution_id: str, keys: list[str]) -> str:
    """Create a CloudFront invalidation for the given object key.

    Args:
        distribution_id: CloudFront distribution ID.
        key: S3 object key. The invalidation path is `/` + URL-encoded key
            (so keys with spaces or special characters invalidate the path
            CloudFront actually serves).

    Returns:
        The CloudFront invalidation ID.

    Raises:
        RuntimeError: if AWS credentials are not configured, or the
            CreateInvalidation API call fails.
    """
    import uuid
    from urllib.parse import quote

    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    paths = ['/' + quote(key.lstrip('/'), safe='/') for key in keys]
    try:
        cf = boto3.client('cloudfront')
        response = cf.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                'Paths': {'Quantity': len(paths), 'Items': paths},
                'CallerReference': f'esb-{uuid.uuid4()}',
            },
        )
        invalidation_id = response['Invalidation']['Id']
        logger.info(
            'Created CloudFront invalidation %s for distribution %s path %s',
            invalidation_id, distribution_id, ', '.join(paths),
        )
        return invalidation_id
    except NoCredentialsError as e:
        raise RuntimeError('AWS credentials not configured for CloudFront invalidation') from e
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = e.response['Error']['Message']
        raise RuntimeError(f'CloudFront invalidation failed ({error_code}): {error_msg}') from e


def _push_gcs(
    content: str,
    target: str,
    *,
    filename: str | None = None,
    content_type: str = HTML_CONTENT_TYPE,
) -> None:
    """Upload the static page HTML to a Google Cloud Storage bucket.

    Target format: "bucket-name/optional/key/path" (key defaults to index.html
    if target ends with / or has no key component).

    Args:
        html_content: Rendered HTML string.
        target: GCS target in format "bucket/key".

    Raises:
        RuntimeError: if GCS upload fails.
    """
    try:
        from google.api_core.exceptions import GoogleAPIError
        from google.auth.exceptions import DefaultCredentialsError
        from google.cloud import storage
    except ImportError as e:
        raise RuntimeError(
            'google-cloud-storage is required for GCS push method. Install it with: pip install google-cloud-storage'
        ) from e

    try:
        bucket, key = _object_target(target, filename)
    except RuntimeError as e:
        raise RuntimeError(str(e).replace('object target', 'GCS target')) from e

    try:
        client = storage.Client()
        bucket_obj = client.bucket(bucket)
        blob = bucket_obj.blob(key)
        blob.cache_control = CACHE_CONTROL
        blob.upload_from_string(content, content_type=content_type)
        logger.info('Static page uploaded to gs://%s/%s', bucket, key)
    except DefaultCredentialsError as e:
        raise RuntimeError('Google Cloud credentials not configured for GCS push') from e
    except GoogleAPIError as e:
        raise RuntimeError(f'GCS upload failed: {e}') from e


def generate_and_push() -> None:
    """Generate the static status page and push it to the configured destination.

    Convenience function used by the notification worker handler.
    """
    html = generate()
    push(html)


def generate_and_push_reservations() -> None:
    """Generate and publish the standalone reservation HTML and JSON files."""
    html, json_content = generate_reservations()
    method = current_app.config.get('STATIC_PAGE_PUSH_METHOD', 'local')
    target = current_app.config.get('STATIC_PAGE_PUSH_TARGET', '')
    if not target:
        raise RuntimeError('STATIC_PAGE_PUSH_TARGET is not configured')

    invalidation_id = None
    if method == 'local':
        _push_local(json_content, target, 'reservations.json')
        _push_local(html, target, 'reservations.html')
    elif method == 's3':
        _push_s3(json_content, target, filename='reservations.json', content_type=JSON_CONTENT_TYPE, invalidate=False)
        _push_s3(html, target, filename='reservations.html', invalidate=False)
        distribution_id = current_app.config.get('CLOUDFRONT_DISTRIBUTION_ID', '')
        if distribution_id:
            _, json_key = _object_target(target, 'reservations.json')
            _, html_key = _object_target(target, 'reservations.html')
            invalidation_id = _create_cloudfront_invalidation(distribution_id, [json_key, html_key])
    elif method == 'gcs':
        _push_gcs(json_content, target, filename='reservations.json', content_type=JSON_CONTENT_TYPE)
        _push_gcs(html, target, filename='reservations.html')
    else:
        raise RuntimeError(f'Unknown STATIC_PAGE_PUSH_METHOD: {method!r}')

    mutation_data = {'method': method, 'target': target, 'artifacts': ['reservations.json', 'reservations.html']}
    if invalidation_id:
        mutation_data['cloudfront_invalidation_id'] = invalidation_id
    log_mutation('static_page.pushed', 'system', mutation_data)
