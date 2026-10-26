"""An event's rules acting on it: each enabled rule of its type whose condition the payload meets notifies its
recipients through its channels. Each notification is a `Delivery`, recorded with its texts before it's sent, then
marked sent or failed (with the error); a channel or a template that fails doesn't stop the others."""

import logging

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from . import cache, channels, conditions, events, recipients, templating
from .models import Delivery, Event

logger = logging.getLogger(__name__)


def process(event_id: int) -> list[Delivery]:
    """Have the rules act on the event `event_id`, once: an event processed already is left alone. Returns the
    deliveries made."""
    event = Event.objects.select_related("actor").filter(pk=event_id).first()
    if event is None or event.processed_at is not None:
        return []
    made: list[Delivery] = []
    try:
        event_type = events.get(event.code)
    except events.UnknownEvent as exc:
        event.error = str(exc)
    else:
        for rule in cache.rules_for(event.code):
            try:
                if not conditions.matches(rule["condition"], event_type, event.payload):
                    continue
            except Exception:
                logger.exception("Rule %s: condition failed on event %s", rule["name"], event.pk)
                continue
            made += _notify(rule, event)
    event.processed_at = timezone.now()
    event.save(update_fields=["processed_at", "error"])
    return made


def _notify(rule: dict, event: Event) -> list[Delivery]:
    made, users = [], None
    for code in rule["channels"]:
        try:
            channel = channels.get(code)
        except (channels.ChannelError, ImproperlyConfigured) as exc:
            made.append(Delivery.objects.create(event=event, rule_id=rule["id"], channel=code,
                                                status=Delivery.Status.SKIPPED, error=str(exc)))
            continue
        if channel.per_recipient:
            if users is None:
                users = recipients.resolve(rule["recipients"], event)
            targets = users
        else:
            targets = [None]
        for user in targets:
            made.append(_deliver(rule, event, channel, user))
    return made


def _deliver(rule: dict, event: Event, channel, user) -> Delivery:
    delivery = Delivery(event=event, rule_id=rule["id"], channel=channel.code, recipient=user)
    try:
        text = templating.text_for(rule["templates"], channel.code, event, user)
    except templating.TemplateError as exc:
        delivery.status, delivery.error = Delivery.Status.FAILED, f"Template: {exc}"
        delivery.save()
        return delivery
    delivery.subject, delivery.body, delivery.link, delivery.language = (
        text.subject[:255], text.body, text.link[:500], text.language)
    delivery.save()
    send(delivery, channel)
    return delivery


def send(delivery: Delivery, channel=None) -> Delivery:
    """Send `delivery` through its channel (again, for one that failed), recording the outcome."""
    delivery.attempts += 1
    try:
        (channel or channels.get(delivery.channel)).send(delivery)
    except Exception as exc:  # a channel's failure is the delivery's, never the caller's
        logger.warning("Delivery %s (%s) failed: %s", delivery.pk, delivery.channel, exc)
        delivery.status, delivery.error = Delivery.Status.FAILED, str(exc) or exc.__class__.__name__
    else:
        delivery.status, delivery.error, delivery.sent_at = Delivery.Status.SENT, "", timezone.now()
    delivery.save(update_fields=["attempts", "status", "error", "sent_at"])
    return delivery
