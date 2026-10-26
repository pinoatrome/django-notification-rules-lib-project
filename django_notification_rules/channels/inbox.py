from django.utils.translation import gettext_lazy as _

from .base import BaseChannel, ChannelError


class InboxChannel(BaseChannel):
    """The in-app inbox: an `InboxMessage` for the recipient, unread until they read it (the API marks it)."""

    label = _("In-app inbox")

    def send(self, delivery) -> None:
        from ..models import InboxMessage

        if delivery.recipient_id is None:
            raise ChannelError("The inbox writes to a user: the delivery has none")
        InboxMessage.objects.create(
            user_id=delivery.recipient_id,
            delivery=delivery,
            event_code=delivery.event.code,
            subject=delivery.subject,
            body=delivery.body,
            link=delivery.link,
        )
