"""Who a rule notifies. A rule's recipients are any of:

- `user`: one user;
- `group`: the users of a group;
- `permission`: the holders of a permission (`app_label.codename`, `User.objects.with_perm`, superusers included);
- `resolver`: the users a resolver finds from the event, by its code.

A resolver is a function `(event) -> users` (any iterable of users, a queryset too) that an app declares in its
`recipients.py` (discovered as `events.py` is):

    @recipients("account_holders")
    def account_holders(event):
        "The holders of the event's account (its `dean`)."
        return User.objects.filter(accounts__account__dean=event.data["dean"])

`event` is the `Event`: its `code`, `payload` (as stored), `data` (parsed: decimals, dates) and `actor`. Built in:
`actor` (who caused the event) and `superusers`. Inactive users are never notified.

The registry holds what the code declares, the same in every process: it isn't shared state.
"""

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.module_loading import autodiscover_modules

from . import conf

logger = logging.getLogger(__name__)

KINDS = ("user", "group", "permission", "resolver")


@dataclass(frozen=True)
class Resolver:
    code: str
    func: Callable
    description: str = ""

    @property
    def fqn(self) -> str:
        return f"{self.func.__module__}.{self.func.__qualname__}"


REGISTRY: dict[str, Resolver] = {}


def recipients(code: str | None = None, *, description: str = ""):
    """Declare a resolver: the decorated function `(event) -> users`. Its code defaults to the function's name, its
    description to its docstring's first paragraph."""

    def register(func):
        text = description or (inspect.getdoc(func) or "").split("\n\n")[0].replace("\n", " ")
        REGISTRY[code or func.__name__] = Resolver(code or func.__name__, func, text)
        return func

    return register


def discover():
    """Import each installed app's `recipients` module (the `@recipients` declarations)."""
    autodiscover_modules("recipients")


def choices() -> list[tuple[str, str]]:
    return [(code, f"{code} — {r.description}" if r.description else code) for code, r in sorted(REGISTRY.items())]


@recipients("actor")
def actor(event):
    """Who caused the event (the `actor` given to `emit`)."""
    return [event.actor] if event.actor_id else []


@recipients("superusers")
def superusers(event):
    """The superusers."""
    return get_user_model().objects.filter(is_superuser=True)


def _users_of(spec: dict, event) -> list:
    User = get_user_model()
    kind = spec["kind"]
    if kind == "user":
        return list(User.objects.filter(pk=spec.get("user_id")))
    if kind == "group":
        return list(User.objects.filter(groups__pk=spec.get("group_id")))
    if kind == "permission":
        backend = conf.get("PERMISSION_BACKEND")
        return list(
            User.objects.with_perm(spec["value"], backend=backend) if backend else User.objects.with_perm(spec["value"])
        )
    if kind == "resolver":
        resolver = REGISTRY.get(spec["value"])
        if resolver is None:
            logger.warning("Event %s: no resolver %r (a rule names it)", event.code, spec["value"])
            return []
        return list(resolver.func(event) or [])
    raise ValueError(f"Unknown recipient kind {kind!r}")


def resolve(specs: list[dict], event) -> list:
    """The active users `specs` (a rule's recipients, as `cache.rules_for` gives them) name for `event`, each once,
    in order. A resolver that fails is logged and finds no one."""
    found, seen = [], set()
    for spec in specs:
        try:
            users = _users_of(spec, event)
        except Exception:
            logger.exception("Event %s: recipients %s not found", event.code, spec)
            continue
        for user in users:
            if user is None or user.pk in seen or not getattr(user, "is_active", True):
                continue
            seen.add(user.pk)
            found.append(user)
    return found


def describe(spec: dict) -> str:
    """A recipient as the admin and the exports show it."""
    if spec["kind"] == "user":
        user = get_user_model().objects.filter(pk=spec.get("user_id")).first()
        return f"user {user.get_username() if user else spec.get('user_id')}"
    if spec["kind"] == "group":
        group = Group.objects.filter(pk=spec.get("group_id")).first()
        return f"group {group.name if group else spec.get('group_id')}"
    return f"{spec['kind']} {spec.get('value', '')}"
