"""Where an event's rules act, once it's recorded (`NOTIFICATION_RULES["RUNNER"]`): a function `(event_id)`.

- `run_now`: in the process that emitted it, right after the commit (the default).

A project with a task queue sets its own, e.g. a Celery task's `delay`:

    @shared_task
    def process_event(event_id):
        dispatch.process(event_id)

    NOTIFICATION_RULES = {"RUNNER": "myproject.tasks.process_event.delay"}
"""

from . import dispatch


def run_now(event_id: int) -> None:
    dispatch.process(event_id)
