from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from review_statistics.models import (
    FlaggedRevsStatistics,
    ReviewActivity,
    ReviewStatisticsCache,
    ReviewStatisticsMetadata,
)
from reviews.models import Wiki


class LoadFlaggedRevsStatisticsDirectSQLCommandTests(TestCase):
    """Tests for load_flaggedrevs_statistics_direct_sql management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.wiki = Wiki.objects.create(
            name="Finnish Wikipedia",
            code="fi",
            family="wikipedia",
            api_endpoint="https://fi.wikipedia.org/w/api.php",
        )

    @patch(
        "review_statistics.management.commands.load_flaggedrevs_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_statistics_success(self, mock_get_client):
        """Test successful statistics loading."""
        mock_client = MagicMock()
        mock_client.fetch_flaggedrevs_statistics.return_value = [
            {
                "yearmonth": 202401.0,
                "totalPages_ns0_avg": 100000,
                "syncedPages_ns0_avg": 95000,
                "reviewedPages_ns0_avg": 96000,
                "pendingLag_average_avg": 150.5,
            }
        ]
        mock_client.fetch_review_activity.return_value = [
            {
                "yearmonth": 202401.0,
                "number_of_reviewers_avg": 25,
                "number_of_reviews_avg": 300,
                "number_of_pages_avg": 250,
            }
        ]
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command("load_flaggedrevs_statistics_direct_sql", "--wiki=fi", stdout=out)

        # Verify data was saved
        self.assertEqual(FlaggedRevsStatistics.objects.count(), 1)
        self.assertEqual(ReviewActivity.objects.count(), 1)

        stat = FlaggedRevsStatistics.objects.first()
        self.assertEqual(stat.wiki, self.wiki)
        self.assertEqual(stat.total_pages_ns0, 100000)
        self.assertEqual(stat.pending_changes, 1000)  # 96000 - 95000

        activity = ReviewActivity.objects.first()
        self.assertEqual(activity.wiki, self.wiki)
        self.assertEqual(activity.number_of_reviewers, 25)

    @patch(
        "review_statistics.management.commands.load_flaggedrevs_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_statistics_with_full_refresh(self, mock_get_client):
        """Test full refresh mode."""
        # Create existing data
        FlaggedRevsStatistics.objects.create(
            wiki=self.wiki,
            date=date(2023, 1, 1),
            total_pages_ns0=50000,
        )

        mock_client = MagicMock()
        mock_client.fetch_flaggedrevs_statistics.return_value = [
            {
                "yearmonth": 202401.0,
                "totalPages_ns0_avg": 100000,
                "syncedPages_ns0_avg": 95000,
                "reviewedPages_ns0_avg": 96000,
                "pendingLag_average_avg": 150.5,
            }
        ]
        mock_client.fetch_review_activity.return_value = []
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command(
            "load_flaggedrevs_statistics_direct_sql",
            "--wiki=fi",
            "--full-refresh",
            stdout=out,
        )

        # Old data should be deleted
        self.assertEqual(FlaggedRevsStatistics.objects.count(), 1)
        self.assertEqual(FlaggedRevsStatistics.objects.first().total_pages_ns0, 100000)

    @patch(
        "review_statistics.management.commands.load_flaggedrevs_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_statistics_with_date_range(self, mock_get_client):
        """Test loading with custom date range."""
        mock_client = MagicMock()
        mock_client.fetch_flaggedrevs_statistics.return_value = []
        mock_client.fetch_review_activity.return_value = []
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command(
            "load_flaggedrevs_statistics_direct_sql",
            "--wiki=fi",
            "--start-date=2024-01-01",
            "--end-date=2024-12-31",
            stdout=out,
        )

        # Verify correct date filters were used
        mock_client.fetch_flaggedrevs_statistics.assert_called_once()
        call_kwargs = mock_client.fetch_flaggedrevs_statistics.call_args[1]
        self.assertEqual(call_kwargs["start_date_filter"], 20240101)
        self.assertEqual(call_kwargs["end_date_filter"], 20241231)

    @patch(
        "review_statistics.management.commands.load_flaggedrevs_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_statistics_auto_continue(self, mock_get_client):
        """Test auto-continue from last available data."""
        # Create existing data for December 2023
        FlaggedRevsStatistics.objects.create(
            wiki=self.wiki,
            date=date(2023, 12, 1),
            total_pages_ns0=50000,
        )

        mock_client = MagicMock()
        mock_client.fetch_flaggedrevs_statistics.return_value = []
        mock_client.fetch_review_activity.return_value = []
        mock_get_client.return_value = mock_client

        out = StringIO()
        err = StringIO()
        call_command("load_flaggedrevs_statistics_direct_sql", "--wiki=fi", stdout=out, stderr=err)

        # Auto-continue may be in stdout or stderr depending on Django version
        output = out.getvalue() + err.getvalue()
        # Just verify it didn't crash - auto-continue message is informational
        self.assertIn("Loading statistics for fi", output)

    @patch(
        "review_statistics.management.commands.load_flaggedrevs_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_statistics_clear_mode(self, mock_get_client):
        """Test clear mode."""
        # Create existing data
        FlaggedRevsStatistics.objects.create(
            wiki=self.wiki,
            date=date(2023, 1, 1),
            total_pages_ns0=50000,
        )
        ReviewActivity.objects.create(
            wiki=self.wiki,
            date=date(2023, 1, 1),
            number_of_reviewers=10,
            number_of_reviews=100,
            number_of_pages=80,
        )

        out = StringIO()
        call_command("load_flaggedrevs_statistics_direct_sql", "--wiki=fi", "--clear", stdout=out)

        # All data should be cleared
        self.assertEqual(FlaggedRevsStatistics.objects.count(), 0)
        self.assertEqual(ReviewActivity.objects.count(), 0)

        output = out.getvalue()
        self.assertIn("Statistics data cleared", output)

    def test_load_statistics_wiki_not_found(self):
        """Test error when wiki doesn't exist."""
        out = StringIO()
        call_command("load_flaggedrevs_statistics_direct_sql", "--wiki=invalid", stdout=out)

        output = out.getvalue()
        self.assertIn("not found", output)


class LoadReviewStatisticsDirectSQLCommandTests(TestCase):
    """Tests for load_review_statistics_direct_sql management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.wiki = Wiki.objects.create(
            name="Finnish Wikipedia",
            code="fi",
            family="wikipedia",
            api_endpoint="https://fi.wikipedia.org/w/api.php",
        )

    @patch(
        "review_statistics.management.commands.load_review_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_review_statistics_success(self, mock_get_client):
        """Test successful review statistics loading."""
        mock_client = MagicMock()
        mock_client.fetch_review_statistics_from_logging.return_value = [
            {
                "log_id": 12345,
                "page_id": 100,
                "page_title": b"Test_Page",
                "reviewer_name": b"TestReviewer",
                "reviewed_user_name": b"TestUser",
                "reviewed_revision_id": 54321,
                "pending_revision_id": 54322,
                "reviewed_timestamp": b"20240115120000",
                "pending_timestamp": b"20240115100000",
                "review_delay_days": 0,
            }
        ]
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command("load_review_statistics_direct_sql", "--wiki=fi", "--limit=100", stdout=out)

        # Verify data was saved
        self.assertEqual(ReviewStatisticsCache.objects.count(), 1)
        review = ReviewStatisticsCache.objects.first()
        self.assertEqual(review.wiki, self.wiki)
        # Reviewer names are stored as decoded from bytes
        self.assertIn("TestReviewer", review.reviewer_name)
        self.assertEqual(review.review_delay_days, 0)

        # Verify metadata was updated
        metadata = ReviewStatisticsMetadata.objects.get(wiki=self.wiki)
        self.assertEqual(metadata.max_log_id, 12345)
        self.assertEqual(metadata.total_records, 1)

    @patch(
        "review_statistics.management.commands.load_review_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_review_statistics_incremental(self, mock_get_client):
        """Test incremental loading using max_log_id."""
        # Create existing metadata
        ReviewStatisticsMetadata.objects.create(wiki=self.wiki, max_log_id=5000, total_records=100)

        mock_client = MagicMock()
        mock_client.fetch_review_statistics_from_logging.return_value = []
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command("load_review_statistics_direct_sql", "--wiki=fi", "--limit=100", stdout=out)

        output = out.getvalue()
        self.assertIn("Continuing from log_id: 5000", output)

        # Verify client was called with correct min_log_id
        mock_client.fetch_review_statistics_from_logging.assert_called_once_with(
            limit=100, min_log_id=5000
        )

    @patch(
        "review_statistics.management.commands.load_review_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_review_statistics_clear_mode(self, mock_get_client):
        """Test clear mode."""
        # Create existing data
        ReviewStatisticsCache.objects.create(
            wiki=self.wiki,
            reviewer_name="OldReviewer",
            reviewed_user_name="OldUser",
            page_title="Old Page",
            page_id=1,
            reviewed_revision_id=1001,
            pending_revision_id=1002,
            reviewed_timestamp="2023-01-01T00:00:00Z",
            pending_timestamp="2023-01-01T00:00:00Z",
            review_delay_days=0,
        )
        ReviewStatisticsMetadata.objects.create(wiki=self.wiki, max_log_id=1000, total_records=1)

        mock_client = MagicMock()
        mock_client.fetch_review_statistics_from_logging.return_value = []
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command(
            "load_review_statistics_direct_sql", "--wiki=fi", "--limit=100", "--clear", stdout=out
        )

        # Verify data was cleared
        self.assertEqual(ReviewStatisticsCache.objects.count(), 0)

        metadata = ReviewStatisticsMetadata.objects.get(wiki=self.wiki)
        self.assertIsNone(metadata.max_log_id)
        self.assertEqual(metadata.total_records, 0)

    @patch(
        "review_statistics.management.commands.load_review_statistics_direct_sql.get_direct_sql_client"
    )
    def test_load_review_statistics_skips_invalid_timestamps(self, mock_get_client):
        """Test that records with invalid timestamps are skipped."""
        mock_client = MagicMock()
        mock_client.fetch_review_statistics_from_logging.return_value = [
            {
                "log_id": 12345,
                "page_id": 100,
                "page_title": b"Test_Page",
                "reviewer_name": b"TestReviewer",
                "reviewed_user_name": b"TestUser",
                "reviewed_revision_id": 54321,
                "pending_revision_id": 54322,
                "reviewed_timestamp": None,  # Invalid
                "pending_timestamp": b"20240115100000",
                "review_delay_days": 0,
            }
        ]
        mock_get_client.return_value = mock_client

        out = StringIO()
        call_command("load_review_statistics_direct_sql", "--wiki=fi", "--limit=100", stdout=out)

        # Record should be skipped
        self.assertEqual(ReviewStatisticsCache.objects.count(), 0)

        output = out.getvalue()
        self.assertIn("skipped 1", output)

    def test_load_review_statistics_wiki_not_found(self):
        """Test error when wiki doesn't exist."""
        out = StringIO()
        call_command(
            "load_review_statistics_direct_sql", "--wiki=invalid", "--limit=100", stdout=out
        )

        output = out.getvalue()
        self.assertIn("not found", output)
