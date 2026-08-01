"""Tests for reservation calendar views."""

import re
from datetime import UTC, datetime, timedelta

from esb.extensions import db
from esb.models.equipment_reservation_settings import EquipmentReservationSettings
from esb.models.reservation import Reservation


def _settings(equipment, *, enabled=True):
    settings = EquipmentReservationSettings(
        equipment_id=equipment.id,
        reservation_slug=f'{equipment.id}-reservation-view',
        reservations_enabled=enabled,
        min_advance_notice_minutes=120,
        max_advance_notice_minutes=14 * 24 * 60,
        min_duration_minutes=30,
        max_duration_minutes=120,
        slot_granularity_minutes=30,
    )
    db.session.add(settings)
    db.session.commit()
    return settings


def _reservation(equipment, user, *, starts_at):
    reservation = Reservation(
        equipment_id=equipment.id,
        user_id=user.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status='active',
        notes='private note',
        created_via='admin',
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


class TestReservationCalendarView:
    def test_accessible_without_login(self, client):
        response = client.get('/reservations/')

        assert response.status_code == 200
        assert b'Reservations' in response.data

    def test_renders_daypilot_calendar_for_staff(
        self, staff_client, staff_user, make_area, make_equipment,
    ):
        area = make_area(name='Shop')
        reservable = make_equipment(name='Laser Cutter', area=area)
        ordinary = make_equipment(name='Ordinary Tool', area=area)
        _settings(reservable)
        _reservation(
            reservable,
            staff_user,
            starts_at=datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0),
        )

        response = staff_client.get('/reservations/')

        assert response.status_code == 200
        html = response.data.decode()
        assert 'Reservations' in html
        assert 'daypilot-javascript.min.js' in html
        assert 'cdn.jsdelivr.net' not in html
        assert '<label class="visually-hidden" for="reservation-date">Reservation date</label>' in html
        assert 'reservation-calendar-data' in html
        assert 'Laser Cutter' in html
        assert 'Reserved' in html
        calendar_json = re.search(
            r'<script type="application/json" id="reservation-calendar-data">(.*?)</script>',
            html,
        ).group(1)
        assert staff_user.display_name not in calendar_json
        assert 'private note' not in calendar_json
        assert ordinary.name not in html

    def test_nav_links_to_reservations(self, staff_client):
        response = staff_client.get('/equipment/')

        assert response.status_code == 200
        assert 'href="/reservations/"' in response.data.decode()

    def test_authenticated_calendar_uses_navbar_and_marks_reservations_active(self, app, staff_client):
        response = staff_client.get('/reservations/')

        assert response.status_code == 200
        html = response.data.decode()
        assert '<nav class="navbar ' in html
        assert 'navbar-local' not in html
        assert 'bg-dark' in html
        assert re.search(r'class="nav-link active"\s+href="/reservations/"', html)

        app.config['DEBUG'] = True
        local_html = staff_client.get('/reservations/').data.decode()
        assert 'navbar-local' in local_html
        assert 'bg-dark' not in local_html

    def test_empty_state_when_no_reservable_tools(self, staff_client):
        response = staff_client.get('/reservations/')

        assert response.status_code == 200
        assert b'No reservable tools are configured yet.' in response.data

    def test_day_navigation_uses_local_date_formatting(self, client):
        response = client.get('/reservations/')

        assert response.status_code == 200
        html = response.data.decode()
        assert 'formatLocalDate(current)' in html
        assert 'toISOString().slice(0, 10)' not in html
