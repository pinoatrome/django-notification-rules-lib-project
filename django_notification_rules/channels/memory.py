from django.utils.translation import gettext_lazy as _

from .base import BaseChannel, ChannelError

# What the memory channels sent, in order, in this process: a test's to read and clear (as Django's locmem mail
# backend's outbox). Not for a deployed project.
outbox: list[dict] = []


class MemoryChannel(BaseChannel):
    """Keeps each notification in `outbox`, for tests. `FAIL`: a message to fail every sending with."""

    label = _("Memory (tests)")

    def send(self, delivery) -> None:
        if self.options.get("FAIL"):
            raise ChannelError(self.options["FAIL"])
        outbox.append({
            "channel": self.code, "event": delivery.event.code, "recipient": delivery.recipient,
            "subject": delivery.subject, "body": delivery.body, "link": delivery.link, "language": delivery.language,
        })
