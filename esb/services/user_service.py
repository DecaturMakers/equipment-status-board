"""User service layer for account provisioning, role management, and password management.

All user management business logic lives here. Views call these functions;
they never query models directly.
"""

import logging
import secrets

from flask import current_app

from esb.extensions import db
from esb.models.user import User
from esb.utils.exceptions import ValidationError
from esb.utils.logging import log_mutation

logger = logging.getLogger(__name__)

# Guard import of slack_sdk -- optional dependency
_slack_sdk_available = False
WebClient = None
try:
    from slack_sdk import WebClient  # type: ignore[assignment]
    _slack_sdk_available = True
except ImportError:
    pass

VALID_ROLES = ('technician', 'staff')


def create_user(
    username: str,
    email: str,
    role: str,
    slack_handle: str | None = None,
    created_by: str = 'system',
) -> tuple[User, str, bool]:
    """Create a new user with a system-generated temporary password.

    Returns:
        Tuple of (user, temp_password, slack_delivered).

    Raises:
        ValidationError: if username or email already exists, or role is invalid.
    """
    if role not in VALID_ROLES:
        raise ValidationError(f'Invalid role: {role!r}. Must be one of {VALID_ROLES}')

    existing = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(f'A user with username {username!r} already exists')

    existing = db.session.execute(
        db.select(User).filter_by(email=email)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(f'A user with email {email!r} already exists')

    temp_password = secrets.token_urlsafe(12)

    user = User(
        username=username,
        email=email,
        role=role,
        slack_handle=slack_handle,
    )
    user.set_password(temp_password)
    db.session.add(user)
    db.session.commit()

    slack_delivered = _deliver_temp_password_via_slack(user, temp_password)

    log_mutation('user.created', created_by, {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'role': user.role,
        'slack_handle': user.slack_handle,
        'slack_delivered': slack_delivered,
    })

    return user, temp_password, slack_delivered


def list_users() -> list[User]:
    """Return all users ordered by username."""
    return list(
        db.session.execute(
            db.select(User).order_by(User.username)
        ).scalars().all()
    )


def get_user(user_id: int) -> User:
    """Get a single user by ID.

    Raises:
        ValidationError: if user not found.
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f'User with id {user_id} not found')
    return user


def change_role(user_id: int, new_role: str, changed_by: str) -> User:
    """Change a user's role.

    Raises:
        ValidationError: if user not found or role is invalid.
    """
    if new_role not in VALID_ROLES:
        raise ValidationError(f'Invalid role: {new_role!r}. Must be one of {VALID_ROLES}')

    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f'User with id {user_id} not found')

    old_role = user.role
    user.role = new_role
    db.session.commit()

    log_mutation('user.role_changed', changed_by, {
        'user_id': user.id,
        'username': user.username,
        'old_role': old_role,
        'new_role': new_role,
    })

    return user


def change_password(user_id: int, current_password: str, new_password: str) -> User:
    """Change a user's own password.

    Args:
        user_id: ID of the user changing their password.
        current_password: The user's current password (verified before changing).
        new_password: The new password to set.

    Returns:
        The updated User instance.

    Raises:
        ValidationError: if user not found or current password is incorrect.
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f'User with id {user_id} not found')

    if not user.check_password(current_password):
        raise ValidationError('Current password is incorrect')

    user.set_password(new_password)
    db.session.commit()

    log_mutation('user.password_changed', user.username, {
        'user_id': user.id,
        'username': user.username,
    })

    return user


def reset_password(user_id: int, reset_by: str) -> tuple[User, str, bool]:
    """Reset a user's password (Staff action).

    Generates a new temporary password, attempts Slack delivery.

    Args:
        user_id: ID of the user whose password is being reset.
        reset_by: Username of the Staff member performing the reset.

    Returns:
        Tuple of (user, temp_password, slack_delivered).

    Raises:
        ValidationError: if user not found.
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f'User with id {user_id} not found')

    temp_password = secrets.token_urlsafe(12)
    user.set_password(temp_password)
    db.session.commit()

    slack_delivered = _deliver_temp_password_via_slack(
        user, temp_password, action='reset',
    )

    log_mutation('user.password_reset', reset_by, {
        'user_id': user.id,
        'username': user.username,
        'reset_by': reset_by,
        'slack_delivered': slack_delivered,
    })

    return user, temp_password, slack_delivered


def update_slack_handle(user_id: int, slack_handle: str | None, updated_by: str) -> User:
    """Update a user's Slack handle.

    Args:
        user_id: ID of the user to update.
        slack_handle: New Slack handle (or None to clear).
        updated_by: Username of the Staff member performing the update.

    Returns:
        The updated User instance.

    Raises:
        ValidationError: if user not found or handle exceeds 80 characters.
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise ValidationError(f'User with id {user_id} not found')

    normalized = slack_handle.strip() if slack_handle else None
    if normalized == '':
        normalized = None
    if normalized is not None and len(normalized) > 80:
        raise ValidationError('Slack handle must be 80 characters or fewer.')

    old_slack_handle = user.slack_handle
    user.slack_handle = normalized
    db.session.commit()

    log_mutation('user.slack_handle_updated', updated_by, {
        'user_id': user.id,
        'username': user.username,
        'old_slack_handle': old_slack_handle,
        'new_slack_handle': user.slack_handle,
    })

    return user


def _deliver_temp_password_via_slack(
    user: User, temp_password: str, *, action: str = 'created',
) -> bool:
    """Attempt to deliver temporary password via Slack DM.

    Args:
        user: The user to deliver the password to.
        temp_password: The temporary password.
        action: Context for the message -- 'created' or 'reset'.

    Returns True on success, False on any failure or if not configured.
    """
    if not _slack_sdk_available or WebClient is None:
        return False

    token = current_app.config.get('SLACK_BOT_TOKEN', '')
    if not token:
        return False

    if not user.slack_handle:
        return False

    try:
        # timeout caps each Slack HTTP call so a hung connection cannot block
        # the request handler indefinitely.
        client = WebClient(token=token, timeout=15)
        resp = client.users_lookupByEmail(email=user.email)
        slack_user_id = resp['user']['id']

        resp = client.conversations_open(users=[slack_user_id])
        dm_channel_id = resp['channel']['id']

        if action == 'reset':
            intro = 'Your Equipment Status Board password has been reset.'
        else:
            intro = 'Your Equipment Status Board account has been created.'

        message = (
            f'{intro}\n'
            f'Username: {user.username}\n'
            f'Temporary password: {temp_password}\n\n'
            f'Please log in and change your password as soon as possible.'
        )
        client.chat_postMessage(channel=dm_channel_id, text=message)
        return True
    except Exception:
        logger.warning('Failed to deliver temp password via Slack for user %s', user.username)
        return False
