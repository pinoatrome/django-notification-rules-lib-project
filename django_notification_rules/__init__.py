"""Rule-driven notifications for Django: the code emits events, the rules stored in the database (set up in the
admin) decide who hears of each, through which channels, with which text.

- `events`: the event types the code declares (`@event`, in each app's `events.py`), their payload's fields, and
  `emit()`, which records an event once the transaction commits and has the rules act on it.
- `recipients`: who a rule notifies: users, groups, the holders of a permission, or a resolver the code declares
  (`@recipients`, in each app's `recipients.py`) that finds them from the event.
- `conditions`: a rule's condition on the event's payload (`all`/`any` of `{field, op, value}`).
- `models`: `NotificationRule` with its recipients, channels and templates; `Event` and its `Delivery` rows (the
  log of what was sent); `InboxMessage`, the in-app inbox.
- `templating`: a rule's templates rendered for a recipient, in their language, in a sandboxed template engine.
- `channels`: the pluggable ways out (`inbox`, `console`, `memory`, ...), configured in `NOTIFICATION_RULES`.
- `dispatch`: an event's rules evaluated, its deliveries made and sent; `runners`: where that runs.
- `yaml_io`: the rules as a YAML document (load and export); `checks`: the system checks; `admin`; `api` (DRF).

Nothing here knows about a particular project: the event types, the resolvers and the channels are the project's.
"""
