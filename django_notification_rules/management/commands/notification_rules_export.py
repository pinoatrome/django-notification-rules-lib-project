from django.core.management.base import BaseCommand

from ...yaml_io import dump_yaml, export_rules


class Command(BaseCommand):
    help = "Write the notification rules as a YAML document."

    def add_arguments(self, parser):
        parser.add_argument("-o", "--output", help="The file to write; the standard output when missing.")

    def handle(self, *args, **options):
        text = dump_yaml(export_rules())
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as target:
                target.write(text)
        else:
            self.stdout.write(text, ending="")
