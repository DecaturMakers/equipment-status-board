"""Reservation calendar routes."""

from flask import Blueprint, render_template

from esb.services import reservation_read_service

reservations_bp = Blueprint("reservations", __name__, url_prefix="/reservations")


@reservations_bp.route("/")
def index():
    """Reservation calendar for reservable equipment."""
    calendar_data = reservation_read_service.get_public_calendar_data()
    return render_template(
        "reservations/index.html",
        calendar_data=calendar_data,
    )
