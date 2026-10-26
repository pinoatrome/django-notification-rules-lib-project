class ChannelError(Exception):
    """A notification the channel couldn't send (or a channel that isn't set up): the delivery fails with it."""


class BaseChannel:
    """A way to send notifications. A backend implements `send(delivery)`: the `Delivery` holds the event, the
    recipient (None for a channel that isn't `per_recipient`), and the texts already rendered (`subject`, `body`,
    `link`, `language`). It returns when sent, and raises (`ChannelError`, or anything else) when it couldn't send:
    the delivery then fails with the error.

    `per_recipient`: whether the channel writes to each recipient (an inbox, an e-mail), or once per event to a
    destination of its own (a chat room, a webhook), the rule's recipients aside. `options` are the other keys of
    the channel's entry in `NOTIFICATION_RULES["CHANNELS"]`."""

    label = ""
    per_recipient = True

    def __init__(self, code: str, **options):
        self.code = code
        self.options = options

    def send(self, delivery) -> None:
        raise NotImplementedError
