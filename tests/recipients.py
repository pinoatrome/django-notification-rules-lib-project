"""The tests' resolvers, discovered as an app's `recipients.py`."""

from django.contrib.auth import get_user_model

from django_notification_rules.recipients import recipients


@recipients("customer")
def customer(event):
    """The order's customer (the user named in the payload)."""
    return get_user_model().objects.filter(username=event.data.get("customer") or "")


@recipients("broken")
def broken(event):
    """A resolver that fails."""
    raise RuntimeError("no customers today")
