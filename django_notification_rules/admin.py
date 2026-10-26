"""The admin: the rules with their recipients, channels and templates (the condition built from the event type's
fields), and its tools: preview a rule's texts, send a test to oneself, the overview of the event types and their
rules, load and export the rules as YAML, check the configuration; the events and what was sent for each (sending
again what failed); the inbox. Staff with the models' permissions use it, the operators too."""

import json

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from . import catalogue, channels, dispatch, events, recipients, templating
from .models import Delivery, Event, InboxMessage, NotificationRule, RuleChannel, RuleRecipient, RuleTemplate
from .yaml_io import RulesDocumentError, dump_yaml, export_rules, load_rules, parse_yaml


def _with_current(options: list[tuple[str, str]], current: str | None) -> list[tuple[str, str]]:
    """`options`, and the stored value when the code or the settings no longer have it (shown, not lost)."""
    if current and current not in {code for code, _label in options}:
        return [*options, (current, f"{current} ({_('unknown')})")]
    return options


class ConditionWidget(forms.Textarea):
    """The condition's JSON, with a builder over the chosen event type's fields (`condition.js`)."""

    template_name = "admin/django_notification_rules/condition_widget.html"

    class Media:
        js = ["django_notification_rules/condition.js"]
        css = {"all": ["django_notification_rules/admin.css"]}

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["schemas"] = json.dumps({entry["code"]: entry for entry in catalogue.catalogue()["events"]})
        return context


class NotificationRuleForm(forms.ModelForm):
    class Meta:
        model = NotificationRule
        fields = ["name", "event_code", "description", "enabled", "condition"]
        widgets = {"condition": ConditionWidget(attrs={"rows": 4, "cols": 80})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event_code"] = forms.ChoiceField(
            label=_("event"), choices=_with_current(events.choices(), self.instance.event_code)
        )


class RecipientForm(forms.ModelForm):
    class Meta:
        model = RuleRecipient
        fields = ["kind", "user", "group", "value"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["value"].widget = forms.TextInput(attrs={"list": "nr-resolvers", "size": 30})
        self.fields["value"].help_text = _("Resolvers: %(codes)s") % {"codes": ", ".join(recipients.REGISTRY) or "-"}


class RecipientInline(admin.TabularInline):
    model = RuleRecipient
    form = RecipientForm
    extra = 0
    raw_id_fields = ["user"]


class ChannelForm(forms.ModelForm):
    class Meta:
        model = RuleChannel
        fields = ["channel", "enabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["channel"] = forms.ChoiceField(
            label=_("channel"), choices=_with_current(channels.choices(), self.instance.channel)
        )


class ChannelInline(admin.TabularInline):
    model = RuleChannel
    form = ChannelForm
    extra = 0


class TemplateForm(forms.ModelForm):
    class Meta:
        model = RuleTemplate
        fields = ["channel", "language", "subject", "body", "link"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "cols": 50})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["channel"] = forms.ChoiceField(
            label=_("channel"),
            choices=_with_current([("*", _("any channel")), *channels.choices()], self.instance.channel),
        )
        self.fields["language"] = forms.ChoiceField(
            label=_("language"),
            required=False,
            choices=_with_current([("", _("any language")), *settings.LANGUAGES], self.instance.language),
        )


class TemplateInline(admin.StackedInline):
    model = RuleTemplate
    form = TemplateForm
    extra = 0


class PreviewForm(forms.Form):
    channel = forms.ChoiceField(label=_("channel"))
    language = forms.ChoiceField(label=_("language"))
    payload = forms.CharField(
        label=_("payload"),
        widget=forms.Textarea(attrs={"rows": 6, "cols": 80}),
        help_text=_("JSON, as the code emits it; the event type's sample at first."),
    )

    def __init__(self, *args, rule=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rule = rule
        self.fields["channel"].choices = [(c.channel, c.channel) for c in rule.channels.all()] or [("*", "*")]
        self.fields["language"].choices = list(settings.LANGUAGES)

    def clean_payload(self):
        try:
            payload = json.loads(self.cleaned_data["payload"])
            return events.get(self.rule.event_code).dump(payload)
        except (ValueError, events.UnknownEvent) as exc:
            raise forms.ValidationError(str(exc)) from exc


class LoadForm(forms.Form):
    document = forms.CharField(label=_("YAML"), required=False, widget=forms.Textarea(attrs={"rows": 20, "cols": 100}))
    file = forms.FileField(label=_("or a file"), required=False)
    keep = forms.BooleanField(label=_("keep the rules the document doesn't name"), required=False)


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    form = NotificationRuleForm
    inlines = [RecipientInline, ChannelInline, TemplateInline]
    list_display = ["name", "event_code", "enabled", "channel_list", "recipient_count", "updated_at"]
    list_filter = ["enabled", "event_code"]
    search_fields = ["name", "event_code", "description"]
    change_list_template = "admin/django_notification_rules/notificationrule/change_list.html"
    change_form_template = "admin/django_notification_rules/notificationrule/change_form.html"

    @admin.display(description=_("channels"))
    def channel_list(self, rule):
        return ", ".join(c.channel + ("" if c.enabled else " (off)") for c in rule.channels.all())

    @admin.display(description=_("recipients"))
    def recipient_count(self, rule):
        return rule.recipients.count()

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("channels")

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = {**(extra_context or {}), "resolver_codes": sorted(recipients.REGISTRY)}
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        view = self.admin_site.admin_view
        name = f"{self.model._meta.app_label}_{self.model._meta.model_name}"
        return [
            path("overview/", view(self.overview), name=f"{name}_overview"),
            path("load/", view(self.load), name=f"{name}_load"),
            path("export/", view(self.export), name=f"{name}_export"),
            path("check/", view(self.check_configuration), name=f"{name}_check"),
            path("<int:pk>/preview/", view(self.preview), name=f"{name}_preview"),
            *super().get_urls(),
        ]

    def _context(self, request, title, **extra):
        return {**self.admin_site.each_context(request), "opts": self.model._meta, "title": title, **extra}

    def overview(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        rules = NotificationRule.objects.prefetch_related("channels", "recipients__user", "recipients__group")
        by_event = {}
        for rule in rules:
            by_event.setdefault(rule.event_code, []).append(rule)
        rows = [
            {
                "code": code,
                "description": kind.description,
                "fields": list(kind.fields),
                "rules": by_event.pop(code, []),
            }
            for code, kind in sorted(events.REGISTRY.items())
        ]
        rows += [
            {"code": code, "description": _("not declared by the code"), "fields": [], "rules": rules, "unknown": True}
            for code, rules in sorted(by_event.items())
        ]
        return TemplateResponse(
            request,
            "admin/django_notification_rules/overview.html",
            self._context(
                request,
                _("Events and their rules"),
                rows=rows,
                channels=channels.codes(),
                resolvers=sorted(recipients.REGISTRY.items()),
            ),
        )

    def preview(self, request, pk):
        rule = get_object_or_404(NotificationRule, pk=pk)
        if not self.has_view_permission(request, rule):
            raise PermissionDenied
        try:
            sample = events.get(rule.event_code).sample_payload()
        except (events.UnknownEvent, events.PayloadError):
            sample = {}
        initial = {
            "payload": json.dumps(sample, indent=2),
            "language": request.LANGUAGE_CODE if hasattr(request, "LANGUAGE_CODE") else settings.LANGUAGE_CODE,
        }
        form = PreviewForm(request.POST or None, rule=rule, initial=initial)
        text = error = sent = None
        if request.method == "POST" and form.is_valid():
            channel, language, payload = (form.cleaned_data[key] for key in ("channel", "language", "payload"))
            templates = [
                {"channel": t.channel, "language": t.language, "subject": t.subject, "body": t.body, "link": t.link}
                for t in rule.templates.all()
            ]
            try:
                event = Event(code=rule.event_code, payload=payload, actor=request.user, created_at=timezone.now())
                text = templating.text_for(templates, channel, event, request.user, language=language)
            except templating.TemplateError as exc:
                error = str(exc)
            if text and "send" in request.POST:
                if not self.has_change_permission(request, rule):
                    raise PermissionDenied
                sent = self._test_send(request, rule, channel, payload, text)
        return TemplateResponse(
            request,
            "admin/django_notification_rules/preview.html",
            self._context(
                request,
                _("Preview: %(rule)s") % {"rule": rule.name},
                rule=rule,
                form=form,
                text=text,
                error=error,
                sent=sent,
                original=rule,
            ),
        )

    def _test_send(self, request, rule, channel, payload, text):
        """Send the previewed texts to the signed-in user through `channel`: a real event and delivery, recorded."""
        event = Event.objects.create(
            code=rule.event_code, payload=payload, actor=request.user, processed_at=timezone.now(), error="test send"
        )
        delivery = Delivery.objects.create(
            event=event,
            rule=rule,
            channel=channel,
            recipient=request.user,
            language=text.language,
            subject=text.subject[:255],
            body=text.body,
            link=text.link[:500],
        )
        dispatch.send(delivery)
        return delivery

    def load(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        form = LoadForm(request.POST or None, request.FILES or None)
        errors = []
        if request.method == "POST" and form.is_valid():
            upload = form.cleaned_data["file"]
            text = upload.read().decode("utf-8") if upload else form.cleaned_data["document"]
            try:
                result = load_rules(parse_yaml(text), keep=form.cleaned_data["keep"])
            except RulesDocumentError as exc:
                errors = exc.errors
            else:
                self.message_user(
                    request,
                    _("Stored %(stored)d rules, deleted %(deleted)d.")
                    % {"stored": len(result["stored"]), "deleted": len(result["deleted"])},
                    messages.SUCCESS,
                )
                return redirect(reverse(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"))
        return TemplateResponse(
            request,
            "admin/django_notification_rules/load.html",
            self._context(request, _("Load rules from YAML"), form=form, errors=errors),
        )

    def export(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        response = HttpResponse(dump_yaml(export_rules()), content_type="application/yaml; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="notification-rules.yaml"'
        return response

    def check_configuration(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        from django.core import checks

        found = [
            message
            for message in checks.run_checks(databases=["default"])
            if message.id and message.id.startswith("django_notification_rules.")
        ]
        return TemplateResponse(
            request,
            "admin/django_notification_rules/check.html",
            self._context(request, _("Check the configuration"), found=found),
        )


class DeliveryInline(admin.TabularInline):
    model = Delivery
    extra = 0
    can_delete = False
    fields = ["channel", "recipient", "status", "attempts", "subject", "error", "sent_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["id", "code", "actor", "created_at", "processed_at", "delivery_count", "error"]
    list_filter = ["code"]
    search_fields = ["code"]
    readonly_fields = ["code", "payload", "actor", "created_at", "processed_at", "error"]
    inlines = [DeliveryInline]
    date_hierarchy = "created_at"

    @admin.display(description=_("deliveries"))
    def delivery_count(self, event):
        return event.deliveries.count()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ["id", "created_at", "event_link", "rule", "channel", "recipient", "status", "attempts", "error"]
    list_filter = ["status", "channel"]
    search_fields = ["event__code", "recipient__username", "subject"]
    readonly_fields = [
        "event",
        "rule",
        "channel",
        "recipient",
        "language",
        "subject",
        "body",
        "link",
        "status",
        "attempts",
        "error",
        "created_at",
        "sent_at",
    ]
    list_select_related = ["event", "rule", "recipient"]
    actions = ["send_again"]

    @admin.display(description=_("event"))
    def event_link(self, delivery):
        url = reverse("admin:django_notification_rules_event_change", args=[delivery.event_id])
        return format_html('<a href="{}">{}</a>', url, delivery.event)

    @admin.action(description=_("Send again the failed and pending ones"), permissions=["change"])
    def send_again(self, request, queryset):
        resent = [dispatch.send(d) for d in queryset.filter(status__in=["failed", "pending"])]
        sent = sum(1 for d in resent if d.status == "sent")
        self.message_user(request, _("Sent %(sent)d of %(tried)d.") % {"sent": sent, "tried": len(resent)})

    def has_add_permission(self, request):
        return False


@admin.register(InboxMessage)
class InboxMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "event_code", "subject", "created_at", "read_at"]
    list_filter = ["event_code", ("read_at", admin.EmptyFieldListFilter)]
    search_fields = ["user__username", "subject", "body"]
    readonly_fields = ["user", "delivery", "event_code", "subject", "body", "link", "created_at", "read_at"]
    list_select_related = ["user"]

    def has_add_permission(self, request):
        return False
