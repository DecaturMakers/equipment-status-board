"""Tests for admin views (user management, area management)."""

import json
import re
from unittest.mock import MagicMock, patch

from esb.extensions import db as _db
from esb.models.area import Area
from esb.models.user import User


class TestListUsers:
    """Tests for GET /admin/users."""

    def test_staff_sees_user_table(self, staff_client, staff_user, tech_user):
        """Staff user sees a table of users."""
        resp = staff_client.get('/admin/users')
        assert resp.status_code == 200
        assert b'User Management' in resp.data
        assert b'staffuser' in resp.data
        assert b'techuser' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on user management page."""
        resp = tech_client.get('/admin/users')
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self, client, app):
        """Unauthenticated user redirected to login."""
        resp = client.get('/admin/users')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_user_table_shows_columns(self, staff_client, staff_user):
        """User table shows username, email, slack handle, role, status columns."""
        resp = staff_client.get('/admin/users')
        assert b'Username' in resp.data
        assert b'Email' in resp.data
        assert b'Slack Handle' in resp.data
        assert b'Role' in resp.data
        assert b'Status' in resp.data

    def test_slack_handle_shown_when_set(self, staff_client, staff_user):
        """User table shows Slack handle when set."""
        staff_user.slack_handle = '@slackadmin'
        _db.session.commit()
        resp = staff_client.get('/admin/users')
        assert b'@slackadmin' in resp.data

    def test_slack_handle_dash_shown_when_not_set(self, staff_client, staff_user):
        """User table shows dash placeholder when Slack handle is not set."""
        assert staff_user.slack_handle is None
        resp = staff_client.get('/admin/users')
        # Em dash placeholder for empty handle
        assert '—'.encode() in resp.data

    def test_add_user_button_visible(self, staff_client, staff_user):
        """Add User button is visible on the user list."""
        resp = staff_client.get('/admin/users')
        assert b'Add User' in resp.data

    def test_inline_role_change_form(self, staff_client, staff_user, tech_user):
        """Each user row has an inline role change form."""
        resp = staff_client.get('/admin/users')
        assert b'Update' in resp.data
        assert b'select' in resp.data

    def test_admin_nav_shows_areas_link(self, staff_client, staff_user):
        """Admin sub-navigation includes Areas link on users page."""
        resp = staff_client.get('/admin/users')
        assert b'/admin/areas' in resp.data


class TestCreateUserForm:
    """Tests for GET /admin/users/new."""

    def test_renders_creation_form(self, staff_client, staff_user):
        """Staff user sees user creation form."""
        resp = staff_client.get('/admin/users/new')
        assert resp.status_code == 200
        assert b'Add User' in resp.data
        assert b'Username' in resp.data
        assert b'Email' in resp.data
        assert b'Role' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on creation form."""
        resp = tech_client.get('/admin/users/new')
        assert resp.status_code == 403


class TestCreateUserPost:
    """Tests for POST /admin/users/new."""

    def test_creates_user_with_valid_data(self, staff_client, staff_user):
        """Valid submission creates user and redirects to password display."""
        resp = staff_client.post('/admin/users/new', data={
            'username': 'newuser',
            'email': 'newuser@example.com',
            'role': 'technician',
        })
        assert resp.status_code == 302
        assert '/created' in resp.headers['Location']

        # Verify user was created in DB
        user = _db.session.execute(
            _db.select(User).filter_by(username='newuser')
        ).scalar_one_or_none()
        assert user is not None
        assert user.role == 'technician'

    def test_duplicate_username_shows_error(self, staff_client, staff_user):
        """Duplicate username shows danger flash."""
        resp = staff_client.post('/admin/users/new', data={
            'username': 'staffuser',
            'email': 'other@example.com',
            'role': 'technician',
        })
        assert resp.status_code == 200
        assert b'already exists' in resp.data

    def test_duplicate_email_shows_error(self, staff_client, staff_user):
        """Duplicate email shows danger flash."""
        resp = staff_client.post('/admin/users/new', data={
            'username': 'uniqueuser',
            'email': 'staffuser@example.com',
            'role': 'technician',
        })
        assert resp.status_code == 200
        assert b'already exists' in resp.data

    def test_missing_username_shows_validation(self, staff_client, staff_user):
        """Missing username shows validation error."""
        resp = staff_client.post('/admin/users/new', data={
            'username': '',
            'email': 'valid@example.com',
            'role': 'technician',
        })
        assert resp.status_code == 200
        # Form not submitted (validation failure), re-renders

    def test_missing_email_shows_validation(self, staff_client, staff_user):
        """Missing email shows validation error."""
        resp = staff_client.post('/admin/users/new', data={
            'username': 'validuser',
            'email': '',
            'role': 'technician',
        })
        assert resp.status_code == 200

    def test_invalid_email_shows_validation(self, staff_client, staff_user):
        """Invalid email format shows validation error."""
        resp = staff_client.post('/admin/users/new', data={
            'username': 'validuser',
            'email': 'not-an-email',
            'role': 'technician',
        })
        assert resp.status_code == 200

    def test_creates_user_with_slack_handle(self, staff_client, staff_user):
        """User creation stores slack handle."""
        staff_client.post('/admin/users/new', data={
            'username': 'slackuser',
            'email': 'slackuser@example.com',
            'role': 'technician',
            'slack_handle': '@slackuser',
        })
        user = _db.session.execute(
            _db.select(User).filter_by(username='slackuser')
        ).scalar_one_or_none()
        assert user is not None
        assert user.slack_handle == '@slackuser'

    @patch('esb.services.user_service._slack_sdk_available', True)
    @patch('esb.services.user_service.WebClient')
    def test_slack_success_redirects_to_users(self, mock_client_cls, staff_client, staff_user, app):
        """When Slack delivery succeeds, redirects to user list with success flash."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-fake-token'
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.users_lookupByEmail.return_value = {'user': {'id': 'U12345'}}
        mock_client.conversations_open.return_value = {'channel': {'id': 'D12345'}}

        resp = staff_client.post('/admin/users/new', data={
            'username': 'slackdelivered',
            'email': 'slackdelivered@example.com',
            'role': 'technician',
            'slack_handle': '@slackdelivered',
        })
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

        resp = staff_client.get('/admin/users')
        assert b'sent via Slack' in resp.data


class TestChangeRole:
    """Tests for POST /admin/users/<id>/role."""

    def test_changes_role_successfully(self, staff_client, staff_user, tech_user):
        """Staff can change a user's role."""
        resp = staff_client.post(f'/admin/users/{tech_user.id}/role', data={
            'user_id': str(tech_user.id),
            'role': 'staff',
        })
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

        # Verify change persisted
        user = _db.session.get(User, tech_user.id)
        assert user.role == 'staff'

    def test_invalid_role_shows_error(self, staff_client, staff_user, tech_user):
        """Invalid role flashes error and redirects."""
        resp = staff_client.post(f'/admin/users/{tech_user.id}/role', data={
            'user_id': str(tech_user.id),
            'role': 'superadmin',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid role change request' in resp.data

    def test_technician_gets_403(self, tech_client, tech_user):
        """Technician cannot change roles."""
        resp = tech_client.post(f'/admin/users/{tech_user.id}/role', data={
            'user_id': str(tech_user.id),
            'role': 'staff',
        })
        assert resp.status_code == 403


class TestTempPasswordDisplay:
    """Tests for GET /admin/users/<id>/created."""

    def test_shows_temp_password(self, staff_client, staff_user):
        """Temp password display page shows password when available."""
        # Create a user to get temp password in session
        resp = staff_client.post('/admin/users/new', data={
            'username': 'tempuser',
            'email': 'tempuser@example.com',
            'role': 'technician',
        })
        assert resp.status_code == 302
        redirect_url = resp.headers['Location']

        # Follow redirect to password display
        resp = staff_client.get(redirect_url)
        assert resp.status_code == 200
        assert b'Temporary Password' in resp.data
        assert b'tempuser' in resp.data
        assert b'only be shown once' in resp.data

    def test_second_visit_redirects(self, staff_client, staff_user):
        """Second visit to password page redirects (password cleared)."""
        # Create user
        resp = staff_client.post('/admin/users/new', data={
            'username': 'onceuser',
            'email': 'onceuser@example.com',
            'role': 'technician',
        })
        redirect_url = resp.headers['Location']

        # First visit - shows password
        resp = staff_client.get(redirect_url)
        assert resp.status_code == 200
        assert b'Temporary Password' in resp.data

        # Second visit - redirects (password no longer available)
        resp = staff_client.get(redirect_url)
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

    def test_back_to_users_button(self, staff_client, staff_user):
        """Password display page has Back to Users button."""
        resp = staff_client.post('/admin/users/new', data={
            'username': 'btnuser',
            'email': 'btnuser@example.com',
            'role': 'technician',
        })
        redirect_url = resp.headers['Location']
        resp = staff_client.get(redirect_url)
        assert b'Back to Users' in resp.data


class TestResetPassword:
    """Tests for POST /admin/users/<id>/reset-password."""

    def test_staff_resets_password(self, staff_client, staff_user, tech_user):
        """Staff can reset a user's password."""
        resp = staff_client.post(f'/admin/users/{tech_user.id}/reset-password')
        assert resp.status_code == 302
        # Redirects to temp password display
        assert '/created' in resp.headers['Location']

    def test_technician_gets_403(self, tech_client, tech_user, staff_user):
        """Technician cannot reset passwords."""
        resp = tech_client.post(f'/admin/users/{staff_user.id}/reset-password')
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self, client, app, tech_user):
        """Unauthenticated user redirected to login."""
        resp = client.post(f'/admin/users/{tech_user.id}/reset-password')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_temp_password_displayed_once(self, staff_client, staff_user, tech_user):
        """After reset, temp password page shows once then redirects."""
        resp = staff_client.post(f'/admin/users/{tech_user.id}/reset-password')
        redirect_url = resp.headers['Location']

        # First visit shows temp password
        resp = staff_client.get(redirect_url)
        assert resp.status_code == 200
        assert b'Temporary Password' in resp.data

        # Second visit redirects (password cleared from session)
        resp = staff_client.get(redirect_url)
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

    def test_nonexistent_user_shows_error(self, staff_client, staff_user):
        """Resetting nonexistent user flashes error and redirects."""
        resp = staff_client.post('/admin/users/99999/reset-password', follow_redirects=True)
        assert resp.status_code == 200
        assert b'not found' in resp.data

    def test_self_reset_blocked(self, staff_client, staff_user):
        """Staff cannot reset their own password via this route."""
        resp = staff_client.post(
            f'/admin/users/{staff_user.id}/reset-password', follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Use Change Password' in resp.data

    def test_old_password_no_longer_works(self, staff_client, staff_user, tech_user):
        """After reset, the old password no longer works."""
        staff_client.post(f'/admin/users/{tech_user.id}/reset-password')
        user = _db.session.get(User, tech_user.id)
        assert not user.check_password('testpass')

    def test_logs_password_reset_mutation(self, staff_client, staff_user, tech_user, capture):
        """Password reset logs mutation event."""
        capture.records.clear()
        staff_client.post(f'/admin/users/{tech_user.id}/reset-password')
        entries = [
            json.loads(r.message) for r in capture.records
            if 'user.password_reset' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['event'] == 'user.password_reset'
        assert entry['user'] == 'staffuser'
        assert entry['data']['username'] == 'techuser'
        assert entry['data']['reset_by'] == 'staffuser'
        # Verify no password values leaked in data
        assert 'password' not in json.dumps(entry['data'])

    @patch('esb.services.user_service._slack_sdk_available', True)
    @patch('esb.services.user_service.WebClient')
    def test_slack_delivery_redirects_to_users(self, mock_client_cls, staff_client, staff_user, tech_user, app):
        """When Slack succeeds, redirects to user list with success flash."""
        app.config['SLACK_BOT_TOKEN'] = 'xoxb-fake-token'
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.users_lookupByEmail.return_value = {'user': {'id': 'U12345'}}
        mock_client.conversations_open.return_value = {'channel': {'id': 'D12345'}}

        tech_user.slack_handle = '@techuser'
        _db.session.commit()

        resp = staff_client.post(f'/admin/users/{tech_user.id}/reset-password')
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

        resp = staff_client.get('/admin/users')
        assert b'sent via Slack' in resp.data


class TestMutationLogging:
    """Tests for mutation logging in admin views."""

    def test_user_created_event_logged(self, staff_client, staff_user, capture):
        """User creation logs user.created mutation event."""
        # Clear login records
        capture.records.clear()
        staff_client.post('/admin/users/new', data={
            'username': 'logcreate',
            'email': 'logcreate@example.com',
            'role': 'technician',
        })
        created_entries = [
            json.loads(r.message) for r in capture.records
            if 'user.created' in r.message
        ]
        assert len(created_entries) == 1
        entry = created_entries[0]
        assert entry['event'] == 'user.created'
        assert entry['user'] == 'staffuser'
        assert entry['data']['username'] == 'logcreate'
        assert 'password' not in json.dumps(entry)

    def test_role_changed_event_logged(self, staff_client, staff_user, tech_user, capture):
        """Role change logs user.role_changed mutation event."""
        capture.records.clear()
        staff_client.post(f'/admin/users/{tech_user.id}/role', data={
            'user_id': str(tech_user.id),
            'role': 'staff',
        })
        changed_entries = [
            json.loads(r.message) for r in capture.records
            if 'user.role_changed' in r.message
        ]
        assert len(changed_entries) == 1
        entry = changed_entries[0]
        assert entry['event'] == 'user.role_changed'
        assert entry['user'] == 'staffuser'
        assert entry['data']['old_role'] == 'technician'
        assert entry['data']['new_role'] == 'staff'


class TestEditSlackHandle:
    """Tests for POST /admin/users/<id>/slack-handle."""

    def test_updates_slack_handle_successfully(self, staff_client, staff_user, tech_user):
        """Valid POST sets the user's Slack handle and redirects to user list."""
        resp = staff_client.post(
            f'/admin/users/{tech_user.id}/slack-handle',
            data={'slack_handle': '@techhandle'},
        )
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

        updated = _db.session.get(User, tech_user.id)
        assert updated.slack_handle == '@techhandle'

    def test_clears_slack_handle_with_empty_string(self, staff_client, staff_user, tech_user):
        """Posting an empty slack_handle clears the user's handle."""
        tech_user.slack_handle = '@existing'
        _db.session.commit()

        resp = staff_client.post(
            f'/admin/users/{tech_user.id}/slack-handle',
            data={'slack_handle': ''},
        )
        assert resp.status_code == 302

        updated = _db.session.get(User, tech_user.id)
        assert updated.slack_handle is None

    def test_success_flash_message(self, staff_client, staff_user, tech_user):
        """Successful update shows success flash message."""
        resp = staff_client.post(
            f'/admin/users/{tech_user.id}/slack-handle',
            data={'slack_handle': '@newhandle'},
            follow_redirects=True,
        )
        assert b"Slack handle updated" in resp.data

    def test_user_not_found_shows_error(self, staff_client, staff_user):
        """Posting to nonexistent user redirects with error flash."""
        resp = staff_client.post(
            '/admin/users/99999/slack-handle',
            data={'slack_handle': '@handle'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'not found' in resp.data

    def test_technician_gets_403(self, tech_client, tech_user):
        """Technician gets 403 when trying to edit Slack handle."""
        resp = tech_client.post(
            f'/admin/users/{tech_user.id}/slack-handle',
            data={'slack_handle': '@handle'},
        )
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self, client, tech_user):
        """Unauthenticated user redirected to login."""
        resp = client.post(
            f'/admin/users/{tech_user.id}/slack-handle',
            data={'slack_handle': '@handle'},
        )
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_mutation_logged(self, staff_client, staff_user, tech_user, capture):
        """Slack handle update logs user.slack_handle_updated mutation event."""
        tech_user.slack_handle = '@old'
        _db.session.commit()
        capture.records.clear()

        staff_client.post(
            f'/admin/users/{tech_user.id}/slack-handle',
            data={'slack_handle': '@new'},
        )
        entries = [
            json.loads(r.message) for r in capture.records
            if 'user.slack_handle_updated' in r.message
        ]
        assert len(entries) == 1
        entry = entries[0]
        assert entry['event'] == 'user.slack_handle_updated'
        assert entry['user'] == 'staffuser'
        assert entry['data']['old_slack_handle'] == '@old'
        assert entry['data']['new_slack_handle'] == '@new'

    def test_edit_slack_handle_form_visible_in_user_list(self, staff_client, staff_user, tech_user):
        """User list shows an inline form for editing the Slack handle."""
        resp = staff_client.get('/admin/users')
        assert b'Update Slack' in resp.data
        assert b'slack-handle' in resp.data


class TestAdminIndex:
    """Tests for GET /admin/."""

    def test_redirects_to_users(self, staff_client, staff_user):
        """Admin index redirects to user list."""
        resp = staff_client.get('/admin/')
        assert resp.status_code == 302
        assert '/admin/users' in resp.headers['Location']

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on admin index."""
        resp = tech_client.get('/admin/')
        assert resp.status_code == 403


# --- Area Management View Tests ---


class TestListAreas:
    """Tests for GET /admin/areas."""

    def test_staff_sees_area_table(self, staff_client, staff_user, make_area):
        """Staff user sees area management page."""
        make_area('Woodshop', '#woodshop')
        make_area('Metal Shop', '#metal')
        resp = staff_client.get('/admin/areas')
        assert resp.status_code == 200
        assert b'Area Management' in resp.data
        assert b'Woodshop' in resp.data
        assert b'Metal Shop' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on area management page."""
        resp = tech_client.get('/admin/areas')
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self, client, app):
        """Unauthenticated user redirected to login."""
        resp = client.get('/admin/areas')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_area_table_shows_columns(self, staff_client, staff_user, make_area):
        """Area table shows Name, Slack Channel, Actions columns."""
        make_area('Woodshop', '#woodshop')
        resp = staff_client.get('/admin/areas')
        assert b'Name' in resp.data
        assert b'Slack Channel' in resp.data
        assert b'Actions' in resp.data

    def test_add_area_button_visible(self, staff_client, staff_user):
        """Add Area button is visible on the area list."""
        resp = staff_client.get('/admin/areas')
        assert b'Add Area' in resp.data

    def test_empty_state_when_no_areas(self, staff_client, staff_user):
        """Shows empty state message when no areas exist."""
        resp = staff_client.get('/admin/areas')
        assert b'No areas have been added yet' in resp.data

    def test_archived_areas_not_shown(self, staff_client, staff_user, make_area):
        """Archived areas do not appear in the list."""
        area = make_area('Archived Area', '#archived')
        area.is_archived = True
        _db.session.commit()
        make_area('Active Area', '#active')

        resp = staff_client.get('/admin/areas')
        assert b'Active Area' in resp.data
        assert b'Archived Area' not in resp.data

    def test_admin_nav_shows_users_link(self, staff_client, staff_user):
        """Admin sub-navigation includes Users link on areas page."""
        resp = staff_client.get('/admin/areas')
        assert b'/admin/users' in resp.data

    def test_table_shows_sort_order_column(self, staff_client, staff_user, make_area):
        """Areas list shows the Sort Order column and value."""
        make_area(name='Woodshop', slack_channel='#woodshop', sort_order=7)
        resp = staff_client.get('/admin/areas')
        assert b'Sort Order' in resp.data
        # Match the Woodshop row's sort_order cell, anchored on the row text
        # so the assertion isn't satisfied by a stray '7' elsewhere on the page.
        row_match = re.search(
            rb'<tr>\s*<td>Woodshop</td>\s*<td>7</td>',
            resp.data,
        )
        assert row_match is not None, resp.data

    def test_areas_listed_in_sort_order_then_name(
        self, staff_client, staff_user, make_area,
    ):
        """Areas in the admin list are ordered by (sort_order, name)."""
        make_area(name='Area A', slack_channel='#a', sort_order=10)
        make_area(name='Area B', slack_channel='#b', sort_order=5)
        make_area(name='Area C', slack_channel='#c', sort_order=5)
        resp = staff_client.get('/admin/areas')
        pos_b = resp.data.find(b'Area B')
        pos_c = resp.data.find(b'Area C')
        pos_a = resp.data.find(b'Area A')
        assert pos_b >= 0 and pos_c >= 0 and pos_a >= 0, resp.data
        assert pos_b < pos_c < pos_a


class TestCreateAreaForm:
    """Tests for GET /admin/areas/new."""

    def test_renders_creation_form(self, staff_client, staff_user):
        """Staff user sees area creation form."""
        resp = staff_client.get('/admin/areas/new')
        assert resp.status_code == 200
        assert b'Add Area' in resp.data
        assert b'Name' in resp.data
        assert b'Slack Channel' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on creation form."""
        resp = tech_client.get('/admin/areas/new')
        assert resp.status_code == 403


class TestCreateAreaPost:
    """Tests for POST /admin/areas/new."""

    def test_creates_area_with_valid_data(self, staff_client, staff_user):
        """Valid submission creates area and redirects to area list."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'Woodshop',
            'slack_channel': '#woodshop',
        })
        assert resp.status_code == 302
        assert '/admin/areas' in resp.headers['Location']

        area = _db.session.execute(
            _db.select(Area).filter_by(name='Woodshop')
        ).scalar_one_or_none()
        assert area is not None
        assert area.slack_channel == '#woodshop'

    def test_duplicate_name_shows_error(self, staff_client, staff_user, make_area):
        """Duplicate area name shows danger flash."""
        make_area('Woodshop', '#woodshop')
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'Woodshop',
            'slack_channel': '#woodshop2',
        })
        assert resp.status_code == 200
        assert b'already exists' in resp.data

    def test_missing_name_shows_validation(self, staff_client, staff_user):
        """Missing name shows validation error."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': '',
            'slack_channel': '#channel',
        })
        assert resp.status_code == 200

    def test_missing_slack_channel_shows_validation(self, staff_client, staff_user):
        """Missing slack channel shows validation error."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'Woodshop',
            'slack_channel': '',
        })
        assert resp.status_code == 200

    def test_success_flash_message(self, staff_client, staff_user):
        """Successful creation shows success flash."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'Woodshop',
            'slack_channel': '#woodshop',
        }, follow_redirects=True)
        assert b'Area created successfully' in resp.data

    def test_creates_area_with_sort_order(self, staff_client, staff_user):
        """POST with sort_order persists the value."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'X',
            'slack_channel': '#x',
            'sort_order': '7',
        })
        assert resp.status_code == 302
        area = _db.session.execute(
            _db.select(Area).filter_by(name='X')
        ).scalar_one_or_none()
        assert area is not None
        assert area.sort_order == 7

    def test_creates_area_with_empty_sort_order_defaults_to_zero(
        self, staff_client, staff_user,
    ):
        """POST with empty sort_order resolves to 0 (covers AC 10)."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'X',
            'slack_channel': '#x',
            'sort_order': '',
        })
        assert resp.status_code == 302
        area = _db.session.execute(
            _db.select(Area).filter_by(name='X')
        ).scalar_one_or_none()
        assert area is not None
        assert area.sort_order == 0

    def test_creates_area_rejects_negative_sort_order(
        self, staff_client, staff_user,
    ):
        """POST with negative sort_order re-renders with validation error (AC 6)."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'X',
            'slack_channel': '#x',
            'sort_order': '-3',
        })
        assert resp.status_code == 200
        assert b'Sort order must be between 0 and 999999.' in resp.data
        rows = _db.session.execute(_db.select(Area)).all()
        assert rows == []

    def test_creates_area_rejects_over_max_sort_order(
        self, staff_client, staff_user,
    ):
        """POST with sort_order over max re-renders with validation error (AC 6)."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'X',
            'slack_channel': '#x',
            'sort_order': '1000000',
        })
        assert resp.status_code == 200
        assert b'Sort order must be between 0 and 999999.' in resp.data
        rows = _db.session.execute(_db.select(Area)).all()
        assert rows == []

    def test_creates_area_rejects_non_integer_sort_order(
        self, staff_client, staff_user,
    ):
        """POST with non-integer sort_order re-renders with both validation errors (AC 6)."""
        resp = staff_client.post('/admin/areas/new', data={
            'name': 'X',
            'slack_channel': '#x',
            'sort_order': 'abc',
        })
        assert resp.status_code == 200
        assert b'Not a valid integer value.' in resp.data
        assert b'Sort order must be between 0 and 999999.' in resp.data
        rows = _db.session.execute(_db.select(Area)).all()
        assert rows == []


class TestEditArea:
    """Tests for GET/POST /admin/areas/<id>/edit."""

    def test_renders_edit_form(self, staff_client, staff_user, make_area):
        """Staff user sees area edit form with existing data."""
        area = make_area('Woodshop', '#woodshop')
        resp = staff_client.get(f'/admin/areas/{area.id}/edit')
        assert resp.status_code == 200
        assert b'Edit Area' in resp.data
        assert b'Woodshop' in resp.data
        assert b'#woodshop' in resp.data
        assert b'Sort Order' in resp.data
        match = re.search(rb'<input [^>]*name="sort_order"[^>]*>', resp.data)
        assert match is not None
        assert b'value="0"' in match.group(0)

    def test_updates_sort_order(self, staff_client, staff_user, make_area):
        """POST edit with new sort_order persists the value."""
        area = make_area('Area', '#area', sort_order=0)
        resp = staff_client.post(f'/admin/areas/{area.id}/edit', data={
            'name': 'Area',
            'slack_channel': '#area',
            'sort_order': '12',
        })
        assert resp.status_code == 302
        updated = _db.session.get(Area, area.id)
        assert updated.sort_order == 12

    def test_updates_area_with_valid_data(self, staff_client, staff_user, make_area):
        """Valid edit submission updates area and redirects."""
        area = make_area('Old Name', '#old')
        resp = staff_client.post(f'/admin/areas/{area.id}/edit', data={
            'name': 'New Name',
            'slack_channel': '#new',
        })
        assert resp.status_code == 302
        assert '/admin/areas' in resp.headers['Location']

        updated = _db.session.get(Area, area.id)
        assert updated.name == 'New Name'
        assert updated.slack_channel == '#new'

    def test_not_found_redirects_with_error(self, staff_client, staff_user):
        """Editing nonexistent area redirects with error flash."""
        resp = staff_client.get('/admin/areas/99999/edit', follow_redirects=True)
        assert resp.status_code == 200
        assert b'not found' in resp.data

    def test_name_conflict_shows_error(self, staff_client, staff_user, make_area):
        """Name conflict with another area shows error."""
        make_area('Existing', '#existing')
        area = make_area('Other', '#other')
        resp = staff_client.post(f'/admin/areas/{area.id}/edit', data={
            'name': 'Existing',
            'slack_channel': '#other',
        })
        assert resp.status_code == 200
        assert b'already exists' in resp.data

    def test_success_flash_message(self, staff_client, staff_user, make_area):
        """Successful edit shows success flash."""
        area = make_area('Woodshop', '#woodshop')
        resp = staff_client.post(f'/admin/areas/{area.id}/edit', data={
            'name': 'Woodshop Updated',
            'slack_channel': '#woodshop',
        }, follow_redirects=True)
        assert b'Area updated successfully' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on area edit."""
        resp = tech_client.get('/admin/areas/1/edit')
        assert resp.status_code == 403


class TestArchiveArea:
    """Tests for POST /admin/areas/<id>/archive."""

    def test_archives_area_successfully(self, staff_client, staff_user, make_area):
        """Staff can archive an area."""
        area = make_area('Woodshop', '#woodshop')
        resp = staff_client.post(f'/admin/areas/{area.id}/archive')
        assert resp.status_code == 302
        assert '/admin/areas' in resp.headers['Location']

        updated = _db.session.get(Area, area.id)
        assert updated.is_archived is True

    def test_not_found_shows_error(self, staff_client, staff_user):
        """Archiving nonexistent area flashes error."""
        resp = staff_client.post('/admin/areas/99999/archive', follow_redirects=True)
        assert resp.status_code == 200
        assert b'not found' in resp.data

    def test_already_archived_shows_error(self, staff_client, staff_user, make_area):
        """Archiving already-archived area flashes error."""
        area = make_area('Woodshop', '#woodshop')
        area.is_archived = True
        _db.session.commit()

        resp = staff_client.post(f'/admin/areas/{area.id}/archive', follow_redirects=True)
        assert resp.status_code == 200
        assert b'already archived' in resp.data

    def test_success_flash_message(self, staff_client, staff_user, make_area):
        """Successful archive shows success flash."""
        area = make_area('Woodshop', '#woodshop')
        resp = staff_client.post(f'/admin/areas/{area.id}/archive', follow_redirects=True)
        assert b'Area archived successfully' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on archive."""
        resp = tech_client.post('/admin/areas/1/archive')
        assert resp.status_code == 403

    def test_unauthenticated_redirects_to_login(self, client, app):
        """Unauthenticated user redirected to login."""
        resp = client.post('/admin/areas/1/archive')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_archive_preserves_sort_order(self, staff_client, staff_user, make_area):
        """Archiving an area does not clear its sort_order value."""
        area = make_area('Woodshop', '#woodshop', sort_order=5)
        resp = staff_client.post(f'/admin/areas/{area.id}/archive')
        assert resp.status_code == 302
        found = _db.session.get(Area, area.id)
        assert found.is_archived is True
        assert found.sort_order == 5


class TestAppConfig:
    """Tests for GET/POST /admin/config."""

    def test_staff_sees_config_form(self, staff_client, staff_user):
        """Staff sees the config form with current values."""
        resp = staff_client.get('/admin/config')
        assert resp.status_code == 200
        assert b'App Configuration' in resp.data
        assert b'Technician Permissions' in resp.data

    def test_technician_gets_403(self, tech_client):
        """Technician gets 403 on config page."""
        resp = tech_client.get('/admin/config')
        assert resp.status_code == 403

    def test_staff_enables_tech_doc_edit(self, staff_client, staff_user):
        """Staff can enable tech doc editing."""
        resp = staff_client.post('/admin/config', data={
            'tech_doc_edit_enabled': 'y',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data

        from esb.services import config_service
        assert config_service.get_config('tech_doc_edit_enabled') == 'true'

    def test_staff_disables_tech_doc_edit(self, staff_client, staff_user):
        """Staff can disable tech doc editing."""
        from esb.services import config_service
        config_service.set_config('tech_doc_edit_enabled', 'true', 'test')

        resp = staff_client.post('/admin/config', data={
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data
        assert config_service.get_config('tech_doc_edit_enabled') == 'false'

    def test_config_mutation_logging(self, staff_client, staff_user, capture):
        """Config change logs mutation."""
        capture.records.clear()
        staff_client.post('/admin/config', data={
            'tech_doc_edit_enabled': 'y',
            'wifi_info_default': 'none',
        })
        entries = [
            json.loads(r.message) for r in capture.records
            if 'app_config.updated' in r.message
        ]
        # All 7 values change from defaults (tech_doc false→true, 6 triggers true→false)
        assert len(entries) == 7
        tech_doc_entries = [e for e in entries if e['data']['key'] == 'tech_doc_edit_enabled']
        assert len(tech_doc_entries) == 1
        assert tech_doc_entries[0]['data']['new_value'] == 'true'

    def test_config_nav_tab_visible(self, staff_client, staff_user):
        """Config tab is visible in admin navigation."""
        resp = staff_client.get('/admin/config')
        assert b'/admin/config' in resp.data
        assert b'Config' in resp.data

    def test_unauthenticated_redirects_to_login(self, client, app):
        """Unauthenticated user redirected to login."""
        resp = client.get('/admin/config')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


class TestAppConfigNotificationTriggers:
    """Tests for notification trigger configuration in /admin/config."""

    def test_config_shows_notification_triggers(self, staff_client, staff_user):
        """Config page shows notification trigger toggles."""
        resp = staff_client.get('/admin/config')
        assert resp.status_code == 200
        assert b'Notification Triggers' in resp.data
        assert b'notify_new_report' in resp.data
        assert b'notify_resolved' in resp.data
        assert b'notify_severity_changed' in resp.data
        assert b'notify_status_changed' in resp.data
        assert b'notify_assignee_changed' in resp.data
        assert b'notify_eta_updated' in resp.data

    def test_triggers_enabled_by_default(self, staff_client, staff_user):
        """Triggers are checked (enabled) by default when no config exists."""
        resp = staff_client.get('/admin/config')
        assert resp.status_code == 200
        html = resp.data.decode()
        # Each trigger input should be rendered with checked attribute
        for field_name in ('notify_new_report', 'notify_resolved',
                           'notify_severity_changed', 'notify_status_changed',
                           'notify_assignee_changed', 'notify_eta_updated'):
            # Find the input tag for this field and verify it has 'checked'
            idx = html.find(f'id="{field_name}"')
            assert idx != -1, f'{field_name} input not found'
            # Look at the surrounding input tag (within 200 chars before the id)
            tag_start = html.rfind('<input', max(0, idx - 200), idx)
            tag_end = html.find('>', idx)
            input_tag = html[tag_start:tag_end + 1]
            assert 'checked' in input_tag, f'{field_name} should be checked by default'

    def test_disable_trigger(self, staff_client, staff_user):
        """Staff can disable a notification trigger."""
        resp = staff_client.post('/admin/config', data={
            'tech_doc_edit_enabled': 'y',
            'notify_new_report': 'y',
            'notify_resolved': 'y',
            'notify_severity_changed': 'y',
            'notify_status_changed': 'y',
            'wifi_info_default': 'none',
            # notify_eta_updated NOT included = disabled
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data

        from esb.services import config_service
        assert config_service.get_config('notify_eta_updated') == 'false'

    def test_disable_status_changed_trigger(self, staff_client, staff_user):
        """Staff can disable the notify_status_changed trigger; subsequent open-status transitions are silent."""
        resp = staff_client.post('/admin/config', data={
            'tech_doc_edit_enabled': 'y',
            'notify_new_report': 'y',
            'notify_resolved': 'y',
            'notify_severity_changed': 'y',
            'notify_eta_updated': 'y',
            'wifi_info_default': 'none',
            # notify_status_changed NOT included = disabled
        }, follow_redirects=True)
        assert resp.status_code == 200
        from esb.services import config_service
        assert config_service.get_config('notify_status_changed') == 'false'

    def test_disable_assignee_changed_trigger(self, staff_client, staff_user, capture):
        """AC 20: staff can disable notify_assignee_changed; the change is persisted and logged."""
        capture.records.clear()
        resp = staff_client.post('/admin/config', data={
            'tech_doc_edit_enabled': 'y',
            'notify_new_report': 'y',
            'notify_resolved': 'y',
            'notify_severity_changed': 'y',
            'notify_status_changed': 'y',
            'notify_eta_updated': 'y',
            'wifi_info_default': 'none',
            # notify_assignee_changed NOT included = disabled
        }, follow_redirects=True)
        assert resp.status_code == 200
        from esb.services import config_service
        assert config_service.get_config('notify_assignee_changed') == 'false'

        entries = [
            json.loads(r.message) for r in capture.records
            if 'app_config.updated' in r.message
        ]
        assigned_entries = [e for e in entries if e['data']['key'] == 'notify_assignee_changed']
        assert len(assigned_entries) == 1
        assert assigned_entries[0]['data']['new_value'] == 'false'

    def test_enable_assignee_changed_trigger(self, staff_client, staff_user):
        """AC 20: staff can re-enable notify_assignee_changed after it was disabled."""
        from esb.services import config_service
        config_service.set_config('notify_assignee_changed', 'false', changed_by='test')

        resp = staff_client.post('/admin/config', data={
            'notify_assignee_changed': 'y',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data
        assert config_service.get_config('notify_assignee_changed') == 'true'

    def test_enable_trigger(self, staff_client, staff_user):
        """Staff can enable a notification trigger."""
        from esb.services import config_service
        config_service.set_config('notify_new_report', 'false', changed_by='test')

        resp = staff_client.post('/admin/config', data={
            'notify_new_report': 'y',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data
        assert config_service.get_config('notify_new_report') == 'true'

    def test_trigger_config_mutation_logging(self, staff_client, staff_user, capture):
        """Trigger config changes log mutations."""
        capture.records.clear()
        staff_client.post('/admin/config', data={
            'notify_new_report': 'y',
            'wifi_info_default': 'none',
        })
        entries = [
            json.loads(r.message) for r in capture.records
            if 'app_config.updated' in r.message
        ]
        # At least one notification trigger config change logged
        notify_entries = [e for e in entries if e['data']['key'].startswith('notify_')]
        assert len(notify_entries) >= 1

    def test_technician_cannot_access_config(self, tech_client):
        """Technician gets 403 on config page."""
        resp = tech_client.get('/admin/config')
        assert resp.status_code == 403


class TestAppConfigWiFi:
    """Tests for WiFi settings in /admin/config."""

    def test_config_shows_wifi_fields(self, staff_client, staff_user):
        resp = staff_client.get('/admin/config')
        assert resp.status_code == 200
        assert b'wifi_ssid' in resp.data
        assert b'wifi_password' in resp.data
        assert b'wifi_info_default' in resp.data
        assert b'WiFi / QR Label Settings' in resp.data

    def test_config_saves_wifi_ssid(self, staff_client, staff_user):
        resp = staff_client.post('/admin/config', data={
            'wifi_ssid': 'MyNetwork',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data
        from esb.services import config_service
        assert config_service.get_config('wifi_ssid') == 'MyNetwork'

    def test_config_saves_wifi_password(self, staff_client, staff_user):
        resp = staff_client.post('/admin/config', data={
            'wifi_password': 'secret123',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from esb.services import config_service
        assert config_service.get_config('wifi_password') == 'secret123'

    def test_config_saves_wifi_info_default(self, staff_client, staff_user):
        resp = staff_client.post('/admin/config', data={
            'wifi_info_default': 'header',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from esb.services import config_service
        assert config_service.get_config('wifi_info_default') == 'header'

    def test_config_clears_wifi_ssid(self, staff_client, staff_user):
        from esb.services import config_service
        config_service.set_config('wifi_ssid', 'OldNetwork', 'test')
        resp = staff_client.post('/admin/config', data={
            'wifi_ssid': '',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert config_service.get_config('wifi_ssid') == ''

    def test_config_wifi_mutation_logging(self, staff_client, staff_user, capture):
        capture.records.clear()
        staff_client.post('/admin/config', data={
            'wifi_ssid': 'NewNet',
            'wifi_info_default': 'none',
        })
        entries = [
            json.loads(r.message) for r in capture.records
            if 'app_config.updated' in r.message
        ]
        wifi_entries = [e for e in entries if e['data']['key'] == 'wifi_ssid']
        assert len(wifi_entries) == 1
        assert wifi_entries[0]['data']['new_value'] == 'NewNet'

    def test_config_wifi_password_masked_in_log(self, staff_client, staff_user, capture):
        capture.records.clear()
        staff_client.post('/admin/config', data={
            'wifi_password': 'supersecret',
            'wifi_info_default': 'none',
        })
        entries = [
            json.loads(r.message) for r in capture.records
            if 'app_config.updated' in r.message
        ]
        pw_entries = [e for e in entries if e['data']['key'] == 'wifi_password']
        assert len(pw_entries) == 1
        assert pw_entries[0]['data']['new_value'] == '***'
        assert 'supersecret' not in str(pw_entries[0])

    def test_config_wifi_password_clear_logs_distinguishable(self, staff_client, staff_user, capture):
        """Clearing a password produces a distinguishable audit entry (old='***', new='')."""
        from esb.services import config_service
        config_service.set_config('wifi_password', 'existingpw', 'test')
        capture.records.clear()
        staff_client.post('/admin/config', data={
            'wifi_password_clear': 'y',
            'wifi_info_default': 'none',
        })
        entries = [
            json.loads(r.message) for r in capture.records
            if 'app_config.updated' in r.message
        ]
        pw_entries = [e for e in entries if e['data']['key'] == 'wifi_password']
        assert len(pw_entries) == 1
        assert pw_entries[0]['data']['old_value'] == '***'
        assert pw_entries[0]['data']['new_value'] == ''
        assert 'existingpw' not in str(pw_entries[0])
        assert config_service.get_config('wifi_password') == ''

    def test_config_wifi_password_blank_means_unchanged(self, staff_client, staff_user):
        """Submitting blank password without the clear checkbox preserves existing value."""
        from esb.services import config_service
        config_service.set_config('wifi_password', 'keepme', 'test')
        staff_client.post('/admin/config', data={
            'wifi_password': '',
            'wifi_info_default': 'none',
        })
        assert config_service.get_config('wifi_password') == 'keepme'

    def test_config_wifi_password_not_prefilled_in_html(self, staff_client, staff_user):
        """Stored password value must not be reflected in the HTML value attribute."""
        from esb.services import config_service
        config_service.set_config('wifi_password', 'secret-no-leak', 'test')
        resp = staff_client.get('/admin/config')
        assert resp.status_code == 200
        assert b'secret-no-leak' not in resp.data

    def test_config_wifi_password_field_is_masked(self, staff_client, staff_user):
        resp = staff_client.get('/admin/config')
        assert resp.status_code == 200
        assert b'type="password"' in resp.data

    def test_config_wifi_ssid_preserves_whitespace(self, staff_client, staff_user):
        """SSIDs with leading/trailing spaces are valid — store verbatim."""
        resp = staff_client.post('/admin/config', data={
            'wifi_ssid': '  MyNet  ',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from esb.services import config_service
        assert config_service.get_config('wifi_ssid') == '  MyNet  '

    def test_config_wifi_password_preserves_whitespace(self, staff_client, staff_user):
        """Passwords can legitimately contain spaces — store verbatim."""
        resp = staff_client.post('/admin/config', data={
            'wifi_password': '  pass word  ',
            'wifi_info_default': 'none',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from esb.services import config_service
        assert config_service.get_config('wifi_password') == '  pass word  '

    def test_config_post_without_wifi_info_default_succeeds(self, staff_client, staff_user):
        """POST without wifi_info_default field should succeed (treated as 'none').

        Regression test: scripted clients or older tests that omit the field
        previously caused SelectField pre-validation to fail with 'Not a valid
        choice', blocking ALL config updates in the submission.
        """
        resp = staff_client.post('/admin/config', data={
            'tech_doc_edit_enabled': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Configuration updated successfully' in resp.data
        from esb.services import config_service
        assert config_service.get_config('tech_doc_edit_enabled') == 'true'


class TestAreaMutationLogging:
    """Tests for mutation logging in area admin views."""

    def test_area_created_event_logged(self, staff_client, staff_user, capture):
        """Area creation logs area.created mutation event."""
        capture.records.clear()
        staff_client.post('/admin/areas/new', data={
            'name': 'Woodshop',
            'slack_channel': '#woodshop',
        })
        created_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.created' in r.message
        ]
        assert len(created_entries) == 1
        entry = created_entries[0]
        assert entry['event'] == 'area.created'
        assert entry['user'] == 'staffuser'
        assert entry['data']['name'] == 'Woodshop'

    def test_area_updated_event_logged(self, staff_client, staff_user, capture, make_area):
        """Area edit logs area.updated mutation event."""
        area = make_area('Old Name', '#old')
        capture.records.clear()
        staff_client.post(f'/admin/areas/{area.id}/edit', data={
            'name': 'New Name',
            'slack_channel': '#new',
        })
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.updated' in r.message
        ]
        assert len(updated_entries) == 1
        entry = updated_entries[0]
        assert entry['event'] == 'area.updated'
        assert entry['user'] == 'staffuser'

    def test_area_archived_event_logged(self, staff_client, staff_user, capture, make_area):
        """Area archive logs area.archived mutation event."""
        area = make_area('Woodshop', '#woodshop')
        capture.records.clear()
        staff_client.post(f'/admin/areas/{area.id}/archive')
        archived_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.archived' in r.message
        ]
        assert len(archived_entries) == 1
        entry = archived_entries[0]
        assert entry['event'] == 'area.archived'
        assert entry['user'] == 'staffuser'
        assert entry['data']['name'] == 'Woodshop'

    def test_sort_order_change_logged(self, staff_client, staff_user, capture, make_area):
        """Editing sort_order logs the change in the area.updated payload."""
        area = make_area('Area', '#area', sort_order=0)
        capture.records.clear()
        staff_client.post(f'/admin/areas/{area.id}/edit', data={
            'name': 'Area',
            'slack_channel': '#area',
            'sort_order': '4',
        })
        updated_entries = [
            json.loads(r.message) for r in capture.records
            if 'area.updated' in r.message
        ]
        assert len(updated_entries) == 1
        assert updated_entries[0]['data']['changes']['sort_order'] == [0, 4]

    def test_no_log_when_sort_order_unchanged(
        self, staff_client, staff_user, capture, make_area,
    ):
        """Re-saving the same sort_order emits no area.updated entry."""
        # Cover both the non-zero->non-zero and zero->zero cases.
        for initial in (5, 0):
            area = make_area(
                f'Area {initial}', f'#area-{initial}', sort_order=initial,
            )
            capture.records.clear()
            staff_client.post(f'/admin/areas/{area.id}/edit', data={
                'name': f'Area {initial}',
                'slack_channel': f'#area-{initial}',
                'sort_order': str(initial),
            })
            updated_entries = [
                json.loads(r.message) for r in capture.records
                if 'area.updated' in r.message
            ]
            assert updated_entries == [], (initial, updated_entries)
