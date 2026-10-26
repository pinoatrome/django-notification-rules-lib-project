# django-notification-rules

Rule-driven notifications for Django. The code emits **events**; **rules** stored in the database, set up in the
admin (or loaded from YAML), decide who hears of each event, through which **channels**, with which texts.

- Events are declared in code, with the fields of their payload: what a rule's condition can test and its templates
  can show.
- A rule: an event type, a condition on the payload, recipients (users, groups, the holders of a permission, or users
  a resolver finds from the event), channels, and texts per channel and language.
- Channels are pluggable and none is required: the in-app inbox, a console channel for development, a memory one for
  tests, and your own.
- Every notification is recorded (`Delivery`): what was written, to whom, through which channel, sent or failed (and
  why); the admin sends again what failed.

Status: alpha (0.1). E-mail, SMS, webhook, push and chat channels, a Celery runner with retries and user preferences
are planned for 0.2.

## Install

```bash
pip install django-notification-rules            # the core
pip install "django-notification-rules[drf]"     # + the REST API (inbox, catalogue)
pip install "django-notification-rules[yaml]"    # + YAML load and export
```

```python
INSTALLED_APPS = [..., "django_notification_rules"]
```

Then `python manage.py migrate`.

## Declare events

In any installed app, an `events.py` (discovered as the admin discovers `admin.py`):

```python
from django.utils.translation import gettext_lazy as _
from django_notification_rules.events import Field, event


@event(
    "orders.placed",
    fields={
        "number": Field("str", _("Order number")),
        "amount": Field("decimal", _("Amount")),
        "customer": Field("str", _("Customer"), required=False),
    },
    templates={"*": {"subject": _("Order placed"), "body": _("Order {{ number }}: {{ amount }}")}},
)
def order_placed():
    """A customer placed an order."""
    return {"number": "A-1", "amount": "12.50", "customer": "ann"}  # a sample, for the admin's preview
```

Field types: `str`, `int`, `decimal`, `bool`, `date`, `datetime`, with optional `choices`. `templates` are the
default texts (by channel, `*` for any), used when a rule has none of its own; mark them for translation. The
docstring is the event type's description. The names `event` and `recipient` are kept for the templates.

Emit it where it happens:

```python
from django_notification_rules.events import emit

emit("orders.placed", number=order.number, amount=order.total, customer=order.user.username, actor=request.user)
```

`emit` checks the payload at once (`PayloadError`, `UnknownEvent`) and, once the transaction commits, records the
`Event` and has its rules act on it. An existing signal can feed an event type instead:

```python
from django_notification_rules.events import connect_signal

connect_signal(order_placed_signal, "orders.placed", lambda sender, order, **kw: {"number": order.number, ...})
```

## Declare resolvers

Recipients found from the event, in any app's `recipients.py`:

```python
from django.contrib.auth import get_user_model
from django_notification_rules.recipients import recipients


@recipients("customer")
def customer(event):
    """The order's customer."""
    return get_user_model().objects.filter(username=event.data["customer"])
```

`event.data` is the payload parsed (decimals, dates), `event.payload` as stored, `event.actor` who caused it. Built
in: `actor` and `superusers`. Inactive users are never notified.

## Set up rules

In the admin, **Notification rules**:

- the **event** and its **condition**: a builder over the event's fields (all or any of `field op value`; the JSON
  underneath can be edited, and nested `all`/`any` groups are allowed);
- **recipients**: a user, a group, the holders of a permission (`app_label.codename`), or a resolver;
- **channels**: among those set up;
- **templates**: per channel (`*` for any) and language (empty for any), a subject, a body and a link, in Django's
  template language over the payload, plus `event` (`code`, `description`, `created_at`) and `recipient`
  (`username`, `first_name`, `last_name`, `full_name`, `email`). Only Django's built-in tags and filters: no
  `{% load %}`, `{% include %}`, `{% extends %}` or `{% debug %}`. Nothing is escaped: a channel that writes HTML
  escapes the texts itself.

A template is chosen for the recipient's language (`USER_LANGUAGE`), then its base language, then any language,
first for the channel, then for `*`; without one, the event type's default texts, translated.

The tools: **Preview and test send** (a rule's texts rendered for you, from the event's sample payload or one you
write, and sent to you through a channel), **Overview** (each event type and its rules), **Check configuration**,
**Export YAML** and **Load YAML** (superusers). **Events** shows each event with its deliveries; **Deliveries**
sends again what failed; **Inbox messages** lists the in-app inbox.

The admin is for staff with the models' permissions: give the operators `view_`, `add_` and `change_notificationrule`
(and the recipients', channels' and templates' permissions) to let them set rules up.

### YAML

```yaml
rules:
  - name: Big orders to the sales team
    event: orders.placed
    condition: {field: amount, op: gte, value: "1000"}
    recipients: [{group: SALES}, {permission: shop.view_order}, {resolver: customer}, {user: ann}]
    channels: [inbox]
    templates:
      - {channel: "*", language: "", subject: "Order {{ number }}", body: "{{ amount }}", link: "/orders/{{ number }}"}
```

```bash
python manage.py notification_rules_load rules.yaml [--keep]   # without --keep, the rules not named are deleted
python manage.py notification_rules_export [-o rules.yaml]
```

## Channels

```python
NOTIFICATION_RULES = {
    "CHANNELS": {
        "inbox": {"BACKEND": "django_notification_rules.channels.inbox.InboxChannel"},
        "console": {"BACKEND": "django_notification_rules.channels.console.ConsoleChannel", "STREAM": "stdout"},
    },
}
```

| backend | what it does |
|---|---|
| `channels.inbox.InboxChannel` | an `InboxMessage` for the recipient (the default channel) |
| `channels.console.ConsoleChannel` | writes each notification to `STREAM` (`stdout`, `stderr`, or `log`): development |
| `channels.memory.MemoryChannel` | keeps them in `channels.memory.outbox`: tests (`FAIL` to make it fail) |

Your own channel subclasses `channels.base.BaseChannel` and implements `send(delivery)`: the delivery holds the
event, the recipient and the rendered `subject`, `body`, `link` and `language`; raise to fail it. Set
`per_recipient = False` for a channel that writes once per event to a destination of its own (a chat room).

## REST API

With Django REST framework, include the API:

```python
path("api/notifications/", include("django_notification_rules.api.urls"))
```

- `GET inbox/` (`?unread=1`), `GET inbox/{id}/`, `GET inbox/unread-count/`, `POST inbox/{id}/read/`,
  `POST inbox/read-all/`: the signed-in user's own inbox.
- `GET catalogue/`: the event types (fields, operators, default texts, a sample), the resolvers and the channels,
  for users who may view the rules: what an operator UI builds its rule forms from.

## Settings

`NOTIFICATION_RULES`, a dict:

| key | default | |
|---|---|---|
| `CHANNELS` | `{"inbox": ...}` | the channels a rule may use |
| `RUNNER` | `django_notification_rules.runners.run_now` | a function `(event_id)`: where the rules act (a Celery task's `delay` to queue it) |
| `CACHE` | `"default"` | the cache alias holding each event type's rules (shared by every process: not a LocMemCache); `None` reads the database each time |
| `CACHE_TIMEOUT` | `300` | |
| `USER_LANGUAGE` | `None` | a function `(user) -> language code`; `None`: `LANGUAGE_CODE` |
| `PERMISSION_BACKEND` | `None` | the backend `User.objects.with_perm` asks, when the project has several |

## Checks

`python manage.py check` checks the settings (`E001` a channel's backend, `E002` the runner or language function,
`W001`/`W002` the cache); `check --database default` checks the stored rules too (`W101` an event type not declared,
`W102` a channel not set up, `W103` a resolver or a permission that doesn't exist, `E101` a condition or a template
that doesn't work). The admin's **Check configuration** runs them.

## Housekeeping

```bash
python manage.py notification_rules_purge --days 90   # events (with their deliveries) and inbox messages
```

## Supported versions

Python 3.10–3.14, Django 5.2 and 6.1, Django REST framework 3.16+ (optional).

Django 4.2 LTS: use the 0.1.x releases (`pip install "django-notification-rules<0.2"`), maintained on the
`stable/0.1.x` branch with fixes only. From 0.2 the library needs Django 5.2 or later.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test,yaml,drf,dev]"
.venv/bin/pytest                # the tests (tests/settings.py, an in-memory SQLite)
tox                             # every supported Python and Django, lint and coverage (90% at least)
pre-commit install              # ruff on commit, the tests on push
```
