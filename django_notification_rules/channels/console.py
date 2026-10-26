import logging
import sys

from django.utils.translation import gettext_lazy as _

from .base import BaseChannel

logger = logging.getLogger("django_notification_rules.console")


class ConsoleChannel(BaseChannel):
    """Writes each notification out instead of sending it, for development: to `STREAM` (`stdout`, the default,
    or `stderr`), or to the log (`log`: the logger `django_notification_rules.console`, at INFO)."""

    label = _("Console (development)")

    def format(self, delivery) -> str:
        recipient = delivery.recipient.get_username() if delivery.recipient_id else "-"
        lines = [f"[{self.code}] {delivery.event.code} → {recipient} ({delivery.language or '-'})"]
        lines += [part for part in (delivery.subject, delivery.body, delivery.link) if part]
        return "\n".join(lines)

    def send(self, delivery) -> None:
        text = self.format(delivery)
        stream = self.options.get("STREAM", "stdout")
        if stream == "log":
            logger.info(text)
            return
        out = sys.stderr if stream == "stderr" else sys.stdout
        out.write(text + "\n\n")
        out.flush()
