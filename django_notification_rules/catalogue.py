"""What a rule can be made of, as plain data: the event types (their fields and operators, their default texts and a
sample payload), the resolvers, and the channels set up. The admin's condition builder and the API read it."""

from . import channels, conditions, events, recipients


def event_entry(event_type: events.EventType) -> dict:
    try:
        sample = event_type.sample_payload()
    except events.PayloadError:
        sample = {}
    return {
        "code": event_type.code,
        "description": str(event_type.description),
        **conditions.schema(event_type),
        "templates": {
            channel: {key: str(value) for key, value in texts.items()}
            for channel, texts in event_type.templates.items()
        },
        "sample": sample,
    }


def catalogue() -> dict:
    return {
        "events": [event_entry(kind) for _code, kind in sorted(events.REGISTRY.items())],
        "resolvers": [
            {"code": code, "description": str(r.description)} for code, r in sorted(recipients.REGISTRY.items())
        ],
        "recipient_kinds": list(recipients.KINDS),
        "channels": [{"code": code, "label": label} for code, label in channels.choices()],
    }
