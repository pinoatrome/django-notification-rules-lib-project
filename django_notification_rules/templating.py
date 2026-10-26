"""A notification's texts: the rule's templates (else the event type's own) rendered for a recipient, in their
language.

The templates are Django's template language, in an engine of their own: Django's built-in tags and filters only,
no `{% load %}` of any library, no `{% include %}`, `{% extends %}` or `{% debug %}`, nothing escaped (the texts
are plain text; a channel that writes HTML escapes them). The context is the event's payload, its values parsed
(decimals, dates: `{{ amount|floatformat:2 }}`, `{{ when|date:"j M" }}`), plus `event` (`code`, `description`,
`created_at`) and `recipient` (`username`, `first_name`, `last_name`, `full_name`, `email`) — never the user object.

A rule's template for a channel and a language is looked for in this order: that channel in the recipient's
language, then in its base language (`pt` for `pt-br`), then in any language; then the same for `*` (any channel).
Without one, the event type's default texts for the channel, translated (gettext) in the recipient's language.
"""

from dataclasses import dataclass

from django.conf import settings
from django.template import Context, Engine, TemplateDoesNotExist, TemplateSyntaxError
from django.template.defaulttags import DebugNode
from django.utils import translation

from . import conf, events

class _Engine(Engine):
    # Django's built-in tags and filters, without its loader tags (include, extends, block).
    default_builtins = ["django.template.defaulttags", "django.template.defaultfilters"]


# No libraries and no loaders: what a template written in the admin may use.
ENGINE = _Engine(loaders=[], libraries={}, autoescape=False, debug=False)


class TemplateError(ValueError):
    """A template that can't be compiled or rendered."""


@dataclass(frozen=True)
class Text:
    subject: str
    body: str
    link: str
    language: str


def compile_template(source: str):
    """`source` compiled. Raises `TemplateError` for a syntax error, an unknown tag or filter, or `{% debug %}`
    (it would write out the whole context)."""
    try:
        template = ENGINE.from_string(source or "")
    except (TemplateSyntaxError, TemplateDoesNotExist) as exc:
        raise TemplateError(str(exc)) from exc
    if template.nodelist.get_nodes_by_type(DebugNode):
        raise TemplateError("{% debug %} isn't allowed")
    return template


def check(source: str) -> None:
    """Raise `TemplateError` when `source` doesn't compile."""
    compile_template(source)


def render(source: str, context: dict) -> str:
    return compile_template(source).render(Context(context, autoescape=False)).strip()


def recipient_context(user) -> dict:
    if user is None:
        return {}
    first, last = getattr(user, "first_name", ""), getattr(user, "last_name", "")
    return {"username": user.get_username(), "first_name": first, "last_name": last,
            "full_name": f"{first} {last}".strip() or user.get_username(), "email": getattr(user, "email", "")}


def context(event, user) -> dict:
    try:
        description = str(events.get(event.code).description)
    except events.UnknownEvent:
        description = ""
    return {**event.data, "event": {"code": event.code, "description": description, "created_at": event.created_at},
            "recipient": recipient_context(user)}


def pick(templates: list[dict], channel: str, language: str) -> dict | None:
    """The rule's template for `channel` in `language` (see the module), or None."""
    language = (language or "").lower()
    base = language.split("-")[0]
    index = {(t["channel"], t["language"].lower()): t for t in templates}
    for wanted in (channel, "*"):
        for lang in dict.fromkeys((language, base, "")):
            if (wanted, lang) in index:
                return index[(wanted, lang)]
    return None


def source_for(templates: list[dict], channel: str, language: str, event_code: str) -> dict:
    """The texts to render: the rule's, else the event type's default ones (translated in the active language),
    else the event type's description as the subject."""
    found = pick(templates, channel, language)
    if found is not None:
        return found
    try:
        event_type = events.get(event_code)
    except events.UnknownEvent:
        return {"subject": event_code, "body": "", "link": ""}
    default = event_type.template(channel)
    if default:
        return {key: str(default.get(key, "")) for key in ("subject", "body", "link")}
    return {"subject": str(event_type.description or event_code), "body": "", "link": ""}


def text_for(templates: list[dict], channel: str, event, user, language: str | None = None) -> Text:
    """`event`'s notification for `user` through `channel`, in their language (or `language`). Raises
    `TemplateError`."""
    language = language or (conf.user_language(user) if user is not None else settings.LANGUAGE_CODE)
    with translation.override(language):
        source = source_for(templates, channel, language, event.code)
        values = context(event, user)
        return Text(render(source.get("subject", ""), values), render(source.get("body", ""), values),
                    render(source.get("link", ""), values), language)
