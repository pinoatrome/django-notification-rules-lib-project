"""The rules as stored (set up in the admin, or loaded from YAML), the events the code emitted and what was sent for
each, and the in-app inbox."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from . import conditions, events, recipients


class NotificationRule(models.Model):
    """When an event of type `event_code` happens and meets `condition`, notify the recipients through the
    channels, with the templates (the event type's own where the rule gives none)."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    event_code = models.CharField(_("event"), max_length=100, db_index=True)
    description = models.TextField(_("description"), blank=True, default="")
    enabled = models.BooleanField(_("enabled"), default=True)
    condition = models.JSONField(
        _("condition"),
        default=dict,
        blank=True,
        help_text=_("On the event's payload: all/any of {field, op, value}. Empty: every event."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event_code", "name"]
        verbose_name = _("notification rule")
        verbose_name_plural = _("notification rules")

    def __str__(self):
        return self.name

    def clean(self):
        try:
            event_type = events.get(self.event_code)
        except events.UnknownEvent:
            raise ValidationError({"event_code": _("No event type has this code.")}) from None
        try:
            conditions.validate(self.condition, event_type)
        except conditions.ConditionError as exc:
            raise ValidationError({"condition": exc.errors}) from None


class RuleRecipient(models.Model):
    """One of a rule's recipients: a user, a group, the holders of a permission, or a resolver's users."""

    class Kind(models.TextChoices):
        USER = "user", _("user")
        GROUP = "group", _("group")
        PERMISSION = "permission", _("holders of a permission")
        RESOLVER = "resolver", _("found from the event")

    rule = models.ForeignKey(NotificationRule, on_delete=models.CASCADE, related_name="recipients")
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("user"),
    )
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name=_("group")
    )
    value = models.CharField(
        _("permission or resolver"),
        max_length=150,
        blank=True,
        default="",
        help_text=_("app_label.codename for a permission; a resolver's code."),
    )

    class Meta:
        verbose_name = _("recipient")
        verbose_name_plural = _("recipients")

    def __str__(self):
        return recipients.describe(self.spec())

    def spec(self) -> dict:
        return {"kind": self.kind, "user_id": self.user_id, "group_id": self.group_id, "value": self.value}

    def clean(self):
        needs = {"user": "user", "group": "group", "permission": "value", "resolver": "value"}.get(self.kind)
        if needs == "user" and not self.user_id:
            raise ValidationError({"user": _("Choose the user.")})
        if needs == "group" and not self.group_id:
            raise ValidationError({"group": _("Choose the group.")})
        if self.kind == "permission" and self.value.count(".") != 1:
            raise ValidationError({"value": _("A permission is written app_label.codename.")})
        if self.kind == "resolver" and self.value not in recipients.REGISTRY:
            raise ValidationError({"value": _("No resolver has this code.")})


class RuleChannel(models.Model):
    """A channel a rule sends through (one of those `NOTIFICATION_RULES["CHANNELS"]` sets up)."""

    rule = models.ForeignKey(NotificationRule, on_delete=models.CASCADE, related_name="channels")
    channel = models.CharField(_("channel"), max_length=50)
    enabled = models.BooleanField(_("enabled"), default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["rule", "channel"], name="nr_rule_channel_once")]
        verbose_name = _("channel")
        verbose_name_plural = _("channels")

    def __str__(self):
        return self.channel


class RuleTemplate(models.Model):
    """A rule's text for a channel in a language (empty: any language), in Django's template language over the
    event's payload and the recipient. The subject is a title (a mail's subject, an inbox item's title), the link
    where the notification leads (a URL or a path)."""

    rule = models.ForeignKey(NotificationRule, on_delete=models.CASCADE, related_name="templates")
    channel = models.CharField(_("channel"), max_length=50, default="*", help_text=_("* for any channel."))
    language = models.CharField(
        _("language"),
        max_length=10,
        blank=True,
        default="",
        help_text=_("A language code (en, it, pt-br); empty for any language."),
    )
    subject = models.CharField(_("subject"), max_length=255, blank=True, default="")
    body = models.TextField(_("body"), blank=True, default="")
    link = models.CharField(_("link"), max_length=500, blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["rule", "channel", "language"], name="nr_template_once")]
        verbose_name = _("template")
        verbose_name_plural = _("templates")

    def __str__(self):
        return f"{self.channel} {self.language or '*'}"

    def clean(self):
        from .templating import TemplateError, check

        errors = {}
        for name in ("subject", "body", "link"):
            try:
                check(getattr(self, name))
            except TemplateError as exc:
                errors[name] = str(exc)
        if errors:
            raise ValidationError(errors)


class Event(models.Model):
    """An event the code emitted: its type, its payload (as stored), who caused it, and when its rules acted."""

    code = models.CharField(_("event"), max_length=100, db_index=True)
    payload = models.JSONField(_("payload"), default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("actor"),
    )
    created_at = models.DateTimeField(_("created"), auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(_("processed"), null=True, blank=True)
    error = models.TextField(_("error"), blank=True, default="")

    class Meta:
        ordering = ["-id"]
        verbose_name = _("event")
        verbose_name_plural = _("events")

    def __str__(self):
        return f"{self.code} #{self.pk}"

    @property
    def data(self) -> dict:
        """The payload with its values as Python (decimals, dates), by the event type's fields; as stored when the
        code no longer declares the type."""
        try:
            return events.get(self.code).parse(self.payload)
        except events.UnknownEvent:
            return dict(self.payload)


class Delivery(models.Model):
    """One notification of an event, by a rule, through a channel, to a recipient: what was written and how
    sending it went."""

    class Status(models.TextChoices):
        PENDING = "pending", _("pending")
        SENT = "sent", _("sent")
        FAILED = "failed", _("failed")
        SKIPPED = "skipped", _("skipped")

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="deliveries")
    rule = models.ForeignKey(
        NotificationRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries"
    )
    channel = models.CharField(_("channel"), max_length=50)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("recipient"),
    )
    language = models.CharField(_("language"), max_length=10, blank=True, default="")
    subject = models.CharField(_("subject"), max_length=255, blank=True, default="")
    body = models.TextField(_("body"), blank=True, default="")
    link = models.CharField(_("link"), max_length=500, blank=True, default="")
    status = models.CharField(_("status"), max_length=8, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(_("attempts"), default=0)
    error = models.TextField(_("error"), blank=True, default="")
    created_at = models.DateTimeField(_("created"), auto_now_add=True)
    sent_at = models.DateTimeField(_("sent"), null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "channel"], name="nr_delivery_status_idx")]
        verbose_name = _("delivery")
        verbose_name_plural = _("deliveries")

    def __str__(self):
        return f"{self.event.code} → {self.recipient} ({self.channel}, {self.status})"


class InboxMessage(models.Model):
    """A notification in a user's in-app inbox (the `inbox` channel)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inbox_messages", verbose_name=_("user")
    )
    delivery = models.OneToOneField(
        Delivery, on_delete=models.SET_NULL, null=True, blank=True, related_name="inbox_message"
    )
    event_code = models.CharField(_("event"), max_length=100)
    subject = models.CharField(_("subject"), max_length=255, blank=True, default="")
    body = models.TextField(_("body"), blank=True, default="")
    link = models.CharField(_("link"), max_length=500, blank=True, default="")
    created_at = models.DateTimeField(_("created"), auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(_("read"), null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["user", "read_at"], name="nr_inbox_unread_idx")]
        verbose_name = _("inbox message")
        verbose_name_plural = _("inbox messages")

    def __str__(self):
        return self.subject or self.body[:50]

    @property
    def read(self) -> bool:
        return self.read_at is not None
