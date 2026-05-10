"""Static status page generation and push service."""

import logging
import os

from flask import current_app, render_template

from esb.utils.logging import log_mutation

logger = logging.getLogger(__name__)


def generate() -> str:
    """Render the static status page with current equipment status data.

    Uses status_service.get_area_status_dashboard() for data and renders
    the public/static_page.html Jinja2 template within the Flask app context.

    Returns:
        Rendered HTML string (self-contained, no external dependencies).
    """
    from datetime import UTC, datetime

    from esb.services import status_service

    areas = status_service.get_area_status_dashboard()
    generated_at = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    return render_template('public/static_page.html', areas=areas, generated_at=generated_at)


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
        _push_local(html_content, target)
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


def _push_local(html_content: str, target_path: str) -> None:
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
        output_path = os.path.join(target_path, 'index.html')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info('Static page written to %s', output_path)
    except OSError as e:
        raise RuntimeError(f'Failed to write static page to {target_path}: {e}') from e


def _push_s3(html_content: str, target: str) -> str | None:
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

    # Parse target: "bucket-name/optional/key/path"
    parts = target.split('/', 1)
    bucket = parts[0]
    if not bucket:
        raise RuntimeError(f'Invalid S3 target {target!r}: bucket name is empty')
    key = parts[1] if len(parts) > 1 and parts[1] else 'index.html'

    try:
        s3 = boto3.client('s3')
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=html_content.encode('utf-8'),
            ContentType='text/html; charset=utf-8',
            CacheControl='no-cache, no-store, must-revalidate',
        )
        logger.info('Static page uploaded to s3://%s/%s', bucket, key)
    except NoCredentialsError as e:
        raise RuntimeError('AWS credentials not configured for S3 push') from e
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = e.response['Error']['Message']
        raise RuntimeError(f'S3 upload failed ({error_code}): {error_msg}') from e

    distribution_id = current_app.config.get('CLOUDFRONT_DISTRIBUTION_ID', '')
    if distribution_id:
        return _create_cloudfront_invalidation(distribution_id, key)
    return None


def _create_cloudfront_invalidation(distribution_id: str, key: str) -> str:
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

    path = '/' + quote(key.lstrip('/'), safe='/')
    try:
        cf = boto3.client('cloudfront')
        response = cf.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                'Paths': {'Quantity': 1, 'Items': [path]},
                'CallerReference': f'esb-{uuid.uuid4()}',
            },
        )
        invalidation_id = response['Invalidation']['Id']
        logger.info(
            'Created CloudFront invalidation %s for distribution %s path %s',
            invalidation_id, distribution_id, path,
        )
        return invalidation_id
    except NoCredentialsError as e:
        raise RuntimeError('AWS credentials not configured for CloudFront invalidation') from e
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = e.response['Error']['Message']
        raise RuntimeError(f'CloudFront invalidation failed ({error_code}): {error_msg}') from e


def _push_gcs(html_content: str, target: str) -> None:
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

    # Parse target: "bucket-name/optional/key/path"
    parts = target.split('/', 1)
    bucket = parts[0]
    if not bucket:
        raise RuntimeError(f'Invalid GCS target {target!r}: bucket name is empty')
    key = parts[1] if len(parts) > 1 and parts[1] else 'index.html'

    try:
        client = storage.Client()
        bucket_obj = client.bucket(bucket)
        blob = bucket_obj.blob(key)
        blob.cache_control = 'no-cache, no-store, must-revalidate'
        blob.upload_from_string(html_content, content_type='text/html; charset=utf-8')
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
