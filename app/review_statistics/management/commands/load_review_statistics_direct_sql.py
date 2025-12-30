from __future__ import annotations

import logging
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from reviews.models.wiki import Wiki

from review_statistics.direct_sql_services import get_direct_sql_client
from review_statistics.models import ReviewStatisticsCache, ReviewStatisticsMetadata

logger = logging.getLogger(__name__)

"""
USAGE:
    python manage.py load_review_statistics_direct_sql --wiki fi  # Load 10,000 records
    python manage.py load_review_statistics_direct_sql --wiki fi --limit 50000  # Load 50k records
    python manage.py load_review_statistics_direct_sql --wiki fi --clear  # Clear and reload

This loads individual review records from the logging table for detailed statistics.
"""


class Command(BaseCommand):
    help = "Load individual review statistics using direct SQL access to wiki replicas"

    def add_arguments(self, parser):
        parser.add_argument(
            "--wiki",
            type=str,
            required=True,
            help="Wiki code to load statistics for (e.g., fi)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=10000,
            help="Maximum number of records to fetch (default: 10000)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing statistics data before loading",
        )

    def handle(self, *args, **options):
        wiki_code = options["wiki"]
        limit = options["limit"]
        clear = options["clear"]

        try:
            wiki = Wiki.objects.get(code=wiki_code)
        except Wiki.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Wiki with code '{wiki_code}' not found."))
            return

        self.stdout.write(f"Loading review statistics for {wiki.code} (limit: {limit})...")

        if clear:
            self.stdout.write("Clearing existing statistics data...")
            ReviewStatisticsCache.objects.filter(wiki=wiki).delete()
            metadata, _ = ReviewStatisticsMetadata.objects.get_or_create(wiki=wiki)
            metadata.max_log_id = None
            metadata.total_records = 0
            metadata.oldest_review_timestamp = None
            metadata.newest_review_timestamp = None
            metadata.save()
            self.stdout.write(self.style.SUCCESS("Statistics data cleared."))

        try:
            # Get metadata for incremental loading
            metadata, created = ReviewStatisticsMetadata.objects.get_or_create(wiki=wiki)
            min_log_id = metadata.max_log_id if not clear else None

            # Create direct SQL client
            sql_client = get_direct_sql_client(wiki)

            # Fetch data using direct SQL
            self.stdout.write(f"  Querying review statistics from logging table...")
            if min_log_id:
                self.stdout.write(f"  Continuing from log_id: {min_log_id}")

            payload = sql_client.fetch_review_statistics_from_logging(
                limit=limit,
                min_log_id=min_log_id,
            )

            self.stdout.write(f"  Retrieved {len(payload)} records")

            if not payload:
                self.stdout.write(self.style.SUCCESS("No new records to load."))
                return

            saved_count = 0
            skipped_count = 0
            max_log_id = min_log_id or 0
            skip_reasons = {}

            with transaction.atomic():
                for i, entry in enumerate(payload):
                    try:
                        log_id = entry.get("log_id")
                        if log_id:
                            max_log_id = max(max_log_id, log_id)

                        # Debug first record
                        if i == 0:
                            self.stdout.write(f"  First record sample: {entry}")

                        # Parse timestamps
                        reviewed_timestamp_str = entry.get("reviewed_timestamp")
                        pending_timestamp_str = entry.get("pending_timestamp")

                        if not reviewed_timestamp_str or not pending_timestamp_str:
                            reason = "missing_timestamps"
                            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                            skipped_count += 1
                            continue

                        reviewed_timestamp = self._parse_timestamp(reviewed_timestamp_str)
                        pending_timestamp = self._parse_timestamp(pending_timestamp_str)

                        if not reviewed_timestamp or not pending_timestamp:
                            reason = "invalid_timestamp_format"
                            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                            skipped_count += 1
                            if i < 5:  # Show first few errors
                                self.stdout.write(
                                    f"  Timestamp parse error: reviewed={reviewed_timestamp_str}, pending={pending_timestamp_str}"
                                )
                            continue

                        # Create or update record
                        ReviewStatisticsCache.objects.update_or_create(
                            wiki=wiki,
                            reviewed_revision_id=entry.get("reviewed_revision_id"),
                            defaults={
                                "reviewer_name": entry.get("reviewer_name", ""),
                                "reviewed_user_name": entry.get("reviewed_user_name", ""),
                                "page_title": entry.get("page_title", ""),
                                "page_id": entry.get("page_id", 0),
                                "pending_revision_id": entry.get("pending_revision_id", 0),
                                "reviewed_timestamp": reviewed_timestamp,
                                "pending_timestamp": pending_timestamp,
                                "review_delay_days": entry.get("review_delay_days", 0),
                            },
                        )
                        saved_count += 1

                    except Exception as e:
                        reason = f"exception: {type(e).__name__}"
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        if i < 5:  # Show first few exceptions
                            logger.warning(f"Failed to process entry: {e}")
                        skipped_count += 1
                        continue

                # Update metadata
                metadata.max_log_id = max_log_id
                metadata.total_records = ReviewStatisticsCache.objects.filter(wiki=wiki).count()
                metadata.last_data_loaded_at = timezone.now()

                # Update oldest/newest timestamps
                oldest = ReviewStatisticsCache.objects.filter(wiki=wiki).order_by("reviewed_timestamp").first()
                newest = ReviewStatisticsCache.objects.filter(wiki=wiki).order_by("-reviewed_timestamp").first()
                if oldest:
                    metadata.oldest_review_timestamp = oldest.reviewed_timestamp
                if newest:
                    metadata.newest_review_timestamp = newest.reviewed_timestamp

                metadata.save()

            # Show skip reasons
            if skip_reasons:
                self.stdout.write("  Skip reasons:")
                for reason, count in skip_reasons.items():
                    self.stdout.write(f"    - {reason}: {count}")

            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Saved {saved_count} records (skipped {skipped_count})\n"
                    f"  Total records in database: {metadata.total_records}\n"
                    f"  Max log_id: {metadata.max_log_id}\n"
                    f"  Oldest review: {metadata.oldest_review_timestamp}\n"
                    f"  Newest review: {metadata.newest_review_timestamp}"
                )
            )

            if saved_count >= limit:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n  ⚠ Reached limit of {limit} records. Run again to load more."
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to load statistics: {e}"))
            logger.exception(f"Failed to load statistics for {wiki.code}")
            raise

    def _parse_timestamp(self, timestamp_value) -> datetime | None:
        """Parse MediaWiki timestamp format (YYYYMMDDHHMMSS)."""
        if timestamp_value is None:
            return None
        try:
            # Handle both string and integer formats
            if isinstance(timestamp_value, bytes):
                timestamp_str = timestamp_value.decode('utf-8')
            else:
                timestamp_str = str(timestamp_value)

            # Remove any whitespace
            timestamp_str = timestamp_str.strip()

            if len(timestamp_str) == 14:
                return datetime.strptime(timestamp_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            else:
                logger.warning(f"Invalid timestamp length ({len(timestamp_str)}): {timestamp_str}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid timestamp format: {timestamp_value} - {e}")
        return None
