"""Tests for the static page service."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from esb.services import static_page_service


class TestGenerate:
    """Tests for generate()."""

    def test_returns_html_with_area_and_equipment(self, app, make_area, make_equipment):
        """generate() renders HTML with area and equipment data."""
        area = make_area(name='Woodshop')
        make_equipment(name='SawStop', area=area)

        html = static_page_service.generate()

        assert 'Woodshop' in html
        assert 'SawStop' in html

    def test_produces_self_contained_html(self, app, make_area, make_equipment):
        """generate() produces HTML with no external CSS/JS links."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert '<link' not in html
        assert '<script src=' not in html
        assert '<!DOCTYPE html>' in html

    def test_includes_status_dot_classes(self, app, make_area, make_equipment):
        """generate() includes status dot CSS classes."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert 'status-green' in html

    def test_includes_generated_timestamp(self, app, make_area, make_equipment):
        """generate() includes a generation timestamp."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert 'Generated:' in html
        assert 'UTC' in html

    def test_includes_csp_meta_tag(self, app, make_area, make_equipment):
        """generate() includes Content-Security-Policy meta tag."""
        area = make_area(name='TestArea')
        make_equipment(name='TestEquip', area=area)

        html = static_page_service.generate()

        assert 'Content-Security-Policy' in html

    def test_renders_yellow_status_for_degraded_equipment(self, app, make_area, make_equipment, make_repair_record):
        """generate() renders status-yellow for equipment with Degraded severity repair."""
        area = make_area(name='TestArea')
        equip = make_equipment(name='DegradedEquip', area=area)
        make_repair_record(equipment=equip, severity='Degraded')

        html = static_page_service.generate()

        assert 'status-yellow' in html
        assert 'DegradedEquip' in html

    def test_renders_red_status_for_down_equipment(self, app, make_area, make_equipment, make_repair_record):
        """generate() renders status-red for equipment with Down severity repair."""
        area = make_area(name='TestArea')
        equip = make_equipment(name='DownEquip', area=area)
        make_repair_record(equipment=equip, severity='Down')

        html = static_page_service.generate()

        assert 'status-red' in html
        assert 'DownEquip' in html

    def test_renders_no_equipment_message_for_empty_area(self, app, make_area):
        """generate() renders fallback text for an area with no equipment."""
        make_area(name='EmptyArea')

        html = static_page_service.generate()

        assert 'EmptyArea' in html
        assert 'No equipment in this area.' in html

    def test_generate_includes_eta_when_set(self, app, make_area, make_equipment, make_repair_record):
        from datetime import date
        area = make_area(name='Lab')
        eq = make_equipment(name='Microscope', area=area)
        make_repair_record(
            equipment=eq, status='New', severity='Down',
            description='Broken', eta=date(2026, 6, 15),
        )
        html = static_page_service.generate()
        expected = 'ETA: ' + date(2026, 6, 15).strftime('%b %d, %Y')
        assert expected in html
        assert 'eta-label' in html

    def test_generate_omits_eta_when_unset(self, app, make_area, make_equipment, make_repair_record):
        area = make_area(name='Lab')
        eq = make_equipment(name='Microscope', area=area)
        make_repair_record(
            equipment=eq, status='New', severity='Down', description='Broken',
        )
        html = static_page_service.generate()
        assert 'ETA:' not in html


class TestPushLocal:
    """Tests for push() with method='local'."""

    def test_writes_file_to_target_directory(self, app, tmp_path):
        """push() with method='local' writes index.html to target directory."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = str(tmp_path)

        static_page_service.push('<html>test</html>')

        output_file = tmp_path / 'index.html'
        assert output_file.exists()
        assert output_file.read_text() == '<html>test</html>'

    def test_creates_directory_if_needed(self, app, tmp_path, capture):
        """push() with method='local' creates target directory if it doesn't exist."""
        target = str(tmp_path / 'new_subdir')
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = target

        static_page_service.push('<html>test</html>')

        assert os.path.exists(os.path.join(target, 'index.html'))

    def test_os_error_raises_runtime_error(self, app):
        """push() with method='local' raises RuntimeError when OS write fails."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/tmp/test-esb-local'

        with patch('esb.services.static_page_service.os.makedirs',
                   side_effect=OSError('Permission denied')):
            with pytest.raises(RuntimeError, match='Failed to write static page'):
                static_page_service.push('<html>test</html>')


class TestPushS3:
    """Tests for push() with method='s3'."""

    def test_calls_boto3_put_object(self, app, capture):
        """push() with method='s3' calls boto3 put_object with correct params."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/status/index.html'

        import boto3
        mock_s3 = MagicMock()

        with patch.object(boto3, 'client', return_value=mock_s3) as mock_client:
            static_page_service.push('<html>test</html>')

            mock_client.assert_called_once_with('s3')
            mock_s3.put_object.assert_called_once_with(
                Bucket='my-bucket',
                Key='status/index.html',
                Body=b'<html>test</html>',
                ContentType='text/html; charset=utf-8',
                CacheControl='no-cache, no-store, must-revalidate',
            )

    def test_handles_client_error(self, app):
        """push() with method='s3' handles ClientError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        import boto3
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        error_response = {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}}
        mock_s3.put_object.side_effect = ClientError(error_response, 'PutObject')

        with patch.object(boto3, 'client', return_value=mock_s3):
            with pytest.raises(RuntimeError, match='S3 upload failed'):
                static_page_service.push('<html>test</html>')

    def test_handles_no_credentials_error(self, app):
        """push() with method='s3' handles NoCredentialsError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        import boto3
        from botocore.exceptions import NoCredentialsError

        mock_s3 = MagicMock()
        mock_s3.put_object.side_effect = NoCredentialsError()

        with patch.object(boto3, 'client', return_value=mock_s3):
            with pytest.raises(RuntimeError, match='AWS credentials not configured'):
                static_page_service.push('<html>test</html>')

    def test_empty_bucket_raises_runtime_error(self, app):
        """push() with method='s3' and target starting with / raises RuntimeError for empty bucket."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/key/path'

        with pytest.raises(RuntimeError, match='bucket name is empty'):
            static_page_service.push('<html>test</html>')

    def test_default_key_when_no_path(self, app, capture):
        """push() with method='s3' defaults key to index.html when target has no path."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 's3'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket'

        import boto3
        mock_s3 = MagicMock()

        with patch.object(boto3, 'client', return_value=mock_s3):
            static_page_service.push('<html>test</html>')

            call_kwargs = mock_s3.put_object.call_args[1]
            assert call_kwargs['Bucket'] == 'my-bucket'
            assert call_kwargs['Key'] == 'index.html'


class TestPushGCS:
    """Tests for push() with method='gcs'."""

    def test_calls_gcs_upload_from_string(self, app, capture):
        """push() with method='gcs' calls GCS upload_from_string with correct params."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/status/index.html'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client) as mock_cls:
            static_page_service.push('<html>test</html>')

            mock_cls.assert_called_once()
            mock_client.bucket.assert_called_once_with('my-bucket')
            mock_bucket.blob.assert_called_once_with('status/index.html')
            assert mock_blob.cache_control == 'no-cache, no-store, must-revalidate'
            mock_blob.upload_from_string.assert_called_once_with(
                '<html>test</html>', content_type='text/html; charset=utf-8'
            )

    def test_handles_google_api_error(self, app):
        """push() with method='gcs' handles GoogleAPIError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        from google.api_core.exceptions import GoogleAPIError
        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.upload_from_string.side_effect = GoogleAPIError('Forbidden')

        with patch.object(storage, 'Client', return_value=mock_client):
            with pytest.raises(RuntimeError, match='GCS upload failed'):
                static_page_service.push('<html>test</html>')

    def test_handles_default_credentials_error(self, app):
        """push() with method='gcs' handles DefaultCredentialsError by raising RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        from google.auth.exceptions import DefaultCredentialsError
        from google.cloud import storage

        with patch.object(storage, 'Client', side_effect=DefaultCredentialsError('msg')):
            with pytest.raises(RuntimeError, match='Google Cloud credentials not configured'):
                static_page_service.push('<html>test</html>')

    def test_empty_bucket_raises_runtime_error(self, app):
        """push() with method='gcs' and target starting with / raises RuntimeError for empty bucket."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/key/path'

        with pytest.raises(RuntimeError, match='bucket name is empty'):
            static_page_service.push('<html>test</html>')

    def test_default_key_when_no_path(self, app, capture):
        """push() with method='gcs' defaults key to index.html when target has no path."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client):
            static_page_service.push('<html>test</html>')

            mock_bucket.blob.assert_called_once_with('index.html')

    def test_trailing_slash_defaults_key_to_index_html(self, app, capture):
        """push() with method='gcs' and trailing slash target defaults key to index.html."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client):
            static_page_service.push('<html>test</html>')

            mock_client.bucket.assert_called_once_with('my-bucket')
            mock_bucket.blob.assert_called_once_with('index.html')

    def test_import_error_raises_runtime_error(self, app):
        """push() with method='gcs' raises RuntimeError when google-cloud-storage not installed."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        with patch.dict('sys.modules', {'google.cloud': None, 'google.api_core': None,
                                         'google.api_core.exceptions': None, 'google.auth': None,
                                         'google.auth.exceptions': None, 'google.cloud.storage': None,
                                         'google': None}):
            with pytest.raises(RuntimeError, match='google-cloud-storage is required'):
                static_page_service.push('<html>test</html>')


class TestPushErrors:
    """Tests for push() error handling."""

    def test_empty_target_raises_runtime_error(self, app):
        """push() with empty target raises RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = ''

        with pytest.raises(RuntimeError, match='STATIC_PAGE_PUSH_TARGET is not configured'):
            static_page_service.push('<html>test</html>')

    def test_unknown_method_raises_runtime_error(self, app):
        """push() with unknown method raises RuntimeError."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'ftp'
        app.config['STATIC_PAGE_PUSH_TARGET'] = '/tmp/test'

        with pytest.raises(RuntimeError, match='Unknown STATIC_PAGE_PUSH_METHOD'):
            static_page_service.push('<html>test</html>')


class TestPushMutationLogging:
    """Tests for mutation logging on push."""

    def test_logs_mutation_on_local_push(self, app, tmp_path, capture):
        """push() logs a mutation event on successful local push."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'local'
        app.config['STATIC_PAGE_PUSH_TARGET'] = str(tmp_path)

        static_page_service.push('<html>test</html>')

        assert len(capture.records) == 1
        log_data = json.loads(capture.records[0].message)
        assert log_data['event'] == 'static_page.pushed'
        assert log_data['data']['method'] == 'local'

    def test_logs_mutation_on_gcs_push(self, app, capture):
        """push() logs a mutation event on successful GCS push."""
        app.config['STATIC_PAGE_PUSH_METHOD'] = 'gcs'
        app.config['STATIC_PAGE_PUSH_TARGET'] = 'my-bucket/index.html'

        from google.cloud import storage
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        with patch.object(storage, 'Client', return_value=mock_client):
            static_page_service.push('<html>test</html>')

        assert len(capture.records) == 1
        log_data = json.loads(capture.records[0].message)
        assert log_data['event'] == 'static_page.pushed'
        assert log_data['data']['method'] == 'gcs'


class TestGenerateAndPush:
    """Tests for generate_and_push()."""

    def test_calls_generate_then_push(self, app):
        """generate_and_push() calls generate() then push()."""
        with patch.object(static_page_service, 'generate', return_value='<html>mock</html>') as mock_gen, \
             patch.object(static_page_service, 'push') as mock_push:
            static_page_service.generate_and_push()

            mock_gen.assert_called_once()
            mock_push.assert_called_once_with('<html>mock</html>')
