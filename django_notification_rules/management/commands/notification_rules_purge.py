from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...models import Event, InboxMessage


class Command(BaseCommand):
    help = "Delete the events (with their deliveries) and the inbox messages older than --days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, required=True, help="Keep what's younger than this many days.")

    def handle(self, *args, **options):
        if options["days"] < 1:
            raise CommandError("--days must be 1 or more")
        cutoff = timezone.now() - timedelta(days=options["days"])
        messages, _ = InboxMessage.objects.filter(created_at__lt=cutoff).delete()
        events = Event.objects.filter(created_at__lt=cutoff)
        count = events.count()
        events.delete()
        self.stdout.write(f"Deleted {count} events and {messages} inbox messages older than {options['days']} days.")
