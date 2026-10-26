import sys

from django.core.management.base import BaseCommand, CommandError

from ...yaml_io import RulesDocumentError, load_rules, parse_yaml


class Command(BaseCommand):
    help = "Store the notification rules of a YAML document (the others deleted, unless --keep)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="The YAML document; - for the standard input.")
        parser.add_argument("--keep", action="store_true", help="Keep the rules the document doesn't name.")

    def handle(self, *args, **options):
        if options["file"] == "-":
            text = sys.stdin.read()
        else:
            with open(options["file"], encoding="utf-8") as source:
                text = source.read()
        try:
            result = load_rules(parse_yaml(text), keep=options["keep"])
        except RulesDocumentError as exc:
            raise CommandError("\n".join(exc.errors)) from exc
        self.stdout.write(f"Stored {len(result['stored'])} rules, deleted {len(result['deleted'])}.")
        for name in result["deleted"]:
            self.stdout.write(f"  deleted: {name}")
