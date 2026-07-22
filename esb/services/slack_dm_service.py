"""Shared Slack direct-message delivery primitives."""

from flask import current_app


def deliver_direct_message(
    *,
    recipient_email: str,
    text: str,
    timeout: int,
    client_factory=None,
) -> None:
    """Resolve a Slack user by email, open a DM, and post ``text``.

    Callers choose whether an error should be surfaced synchronously or left to
    the notification worker's retry policy.
    """
    token = current_app.config.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not configured -- cannot deliver Slack DMs")
    if client_factory is None:
        from slack_sdk import WebClient

        client_factory = WebClient

    client = client_factory(token=token, timeout=timeout)
    lookup = client.users_lookupByEmail(email=recipient_email)
    slack_user_id = lookup["user"]["id"]
    opened = client.conversations_open(users=[slack_user_id])
    dm_channel_id = opened["channel"]["id"]
    client.chat_postMessage(channel=dm_channel_id, text=text)
