from __future__ import annotations

from django.core.management.base import BaseCommand
from reviews.models import Wiki, WikiConfiguration


class Command(BaseCommand):
    help = "Add a new wiki to the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--code",
            type=str,
            required=True,
            help="Wiki code (e.g., 'fi', 'sv', 'en')",
        )
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Wiki name (e.g., 'Finnish Wikipedia')",
        )
        parser.add_argument(
            "--family",
            type=str,
            default="wikipedia",
            help="Wiki family (default: 'wikipedia')",
        )

    def handle(self, *args, **options):
        code = options["code"]
        name = options["name"]
        family = options["family"]

        # Construct API endpoint
        api_endpoint = f"https://{code}.{family}.org/w/api.php"

        # Create or get wiki
        wiki, created = Wiki.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "family": family,
                "api_endpoint": api_endpoint,
                "script_path": "/w",
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"✓ Created wiki: {name} ({code})"))
            self.stdout.write(f"  API endpoint: {api_endpoint}")

            # Create default configuration
            WikiConfiguration.objects.create(wiki=wiki)
            self.stdout.write("  Created default configuration")
        else:
            self.stdout.write(self.style.WARNING(f"Wiki '{code}' already exists"))
