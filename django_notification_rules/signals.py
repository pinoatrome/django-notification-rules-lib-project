"""Drop the cached rules when a rule, its recipients, channels or templates change (once the transaction commits:
until then the other processes still see the old rules, as the database does)."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from . import cache
from .models import NotificationRule, RuleChannel, RuleRecipient, RuleTemplate


def _forget_later(*codes: str) -> None:
    codes = tuple(code for code in codes if code)
    transaction.on_commit(lambda: cache.forget(*codes))


@receiver(pre_save, sender=NotificationRule, dispatch_uid="django_notification_rules.rule_code_before")
def remember_old_code(sender, instance, **kwargs):
    """A rule moved to another event type: its old type's rules change too."""
    instance._old_event_code = (
        sender.objects.filter(pk=instance.pk).values_list("event_code", flat=True).first() if instance.pk else None
    )


@receiver(post_save, sender=NotificationRule, dispatch_uid="django_notification_rules.rule_saved")
@receiver(post_delete, sender=NotificationRule, dispatch_uid="django_notification_rules.rule_deleted")
def rule_changed(sender, instance, **kwargs):
    _forget_later(instance.event_code, getattr(instance, "_old_event_code", None) or "")


@receiver(post_save, sender=RuleRecipient, dispatch_uid="django_notification_rules.recipient_saved")
@receiver(post_delete, sender=RuleRecipient, dispatch_uid="django_notification_rules.recipient_deleted")
@receiver(post_save, sender=RuleChannel, dispatch_uid="django_notification_rules.channel_saved")
@receiver(post_delete, sender=RuleChannel, dispatch_uid="django_notification_rules.channel_deleted")
@receiver(post_save, sender=RuleTemplate, dispatch_uid="django_notification_rules.template_saved")
@receiver(post_delete, sender=RuleTemplate, dispatch_uid="django_notification_rules.template_deleted")
def part_changed(sender, instance, **kwargs):
    rule = NotificationRule.objects.filter(pk=instance.rule_id).values_list("event_code", flat=True).first()
    _forget_later(rule or "")
