"""Area model for equipment location organization."""

from datetime import UTC, datetime

from esb.extensions import db


class Area(db.Model):
    """Physical area/location with optional Slack channel mapping."""

    __tablename__ = 'areas'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    slack_channel = db.Column(db.String(80), nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self):
        return f'<Area {self.name!r}>'
