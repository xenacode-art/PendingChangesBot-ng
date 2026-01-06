from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase
from reviews.models import Wiki

from review_statistics.direct_sql_services import (
    DirectSQLStatisticsClient,
    get_direct_sql_client,
)


class DirectSQLStatisticsClientTests(TestCase):
    """Tests for DirectSQLStatisticsClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.wiki = Wiki.objects.create(
            name="Finnish Wikipedia",
            code="fi",
            family="wikipedia",
            api_endpoint="https://fi.wikipedia.org/w/api.php",
        )

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_init(self, mock_get_connection):
        """Test client initialization."""
        mock_connection_manager = MagicMock()
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)

        self.assertEqual(client.wiki, self.wiki)
        self.assertEqual(client.connection_manager, mock_connection_manager)
        mock_get_connection.assert_called_once_with(self.wiki)

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_flaggedrevs_statistics_monthly(self, mock_get_connection):
        """Test fetching FlaggedRevs statistics with monthly resolution."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = [
            {
                "yearmonth": 202401.0,
                "totalPages_ns0_avg": 100000,
                "syncedPages_ns0_avg": 95000,
                "reviewedPages_ns0_avg": 96000,
                "pendingLag_average_avg": 150.5,
            }
        ]
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        result = client.fetch_flaggedrevs_statistics(
            start_date_filter=20240101, resolution="monthly"
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["totalPages_ns0_avg"], 100000)
        mock_connection_manager.execute_query.assert_called_once()

        # Verify SQL query contains correct resolution grouping
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("FLOOR(d/100)", call_args)  # Monthly grouping

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_flaggedrevs_statistics_yearly(self, mock_get_connection):
        """Test fetching FlaggedRevs statistics with yearly resolution."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = []
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        client.fetch_flaggedrevs_statistics(start_date_filter=20240101, resolution="yearly")

        # Verify SQL query contains yearly grouping
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("FLOOR(d/10000)", call_args)  # Yearly grouping

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_flaggedrevs_statistics_daily(self, mock_get_connection):
        """Test fetching FlaggedRevs statistics with daily resolution."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = []
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        client.fetch_flaggedrevs_statistics(start_date_filter=20240101, resolution="daily")

        # Verify SQL query contains daily grouping
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("d as yearmonth", call_args)  # Daily grouping

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_flaggedrevs_statistics_with_date_range(self, mock_get_connection):
        """Test fetching statistics with date range filter."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = []
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        client.fetch_flaggedrevs_statistics(
            start_date_filter=20240101, end_date_filter=20241231, resolution="monthly"
        )

        # Verify SQL query contains both date filters
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("WHERE total_ns0.d >= 20240101", call_args)
        self.assertIn("AND total_ns0.d <= 20241231", call_args)

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_review_activity_monthly(self, mock_get_connection):
        """Test fetching review activity with monthly resolution."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = [
            {
                "yearmonth": 202401.0,
                "number_of_reviewers_avg": 25,
                "number_of_reviews_avg": 300,
                "number_of_pages_avg": 250,
            }
        ]
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        result = client.fetch_review_activity(
            start_date_filter="20240101000000", resolution="monthly"
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number_of_reviewers_avg"], 25)
        mock_connection_manager.execute_query.assert_called_once()

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_review_activity_with_end_date(self, mock_get_connection):
        """Test fetching review activity with end date filter."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = []
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        client.fetch_review_activity(
            start_date_filter="20240101000000",
            end_date_filter="20241231235959",
            resolution="monthly",
        )

        # Verify SQL query contains end date filter
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("AND fr_timestamp <= 20241231235959", call_args)

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_review_statistics_from_logging(self, mock_get_connection):
        """Test fetching review statistics from logging table."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = [
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
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        result = client.fetch_review_statistics_from_logging(limit=1000)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["log_id"], 12345)
        self.assertEqual(result[0]["reviewer_name"], b"TestReviewer")
        mock_connection_manager.execute_query.assert_called_once()

        # Verify SQL contains correct filters
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("log_namespace = 0", call_args)
        self.assertIn("log_type = 'review'", call_args)
        self.assertIn("LIMIT 1000", call_args)

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_review_statistics_with_min_timestamp(self, mock_get_connection):
        """Test fetching review statistics with minimum timestamp."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = []
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        client.fetch_review_statistics_from_logging(
            limit=1000, min_timestamp="20240101000000"
        )

        # Verify SQL contains timestamp filter
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("log_timestamp > BINARY('20240101000000')", call_args)

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_review_statistics_with_min_log_id(self, mock_get_connection):
        """Test fetching review statistics with minimum log_id."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.return_value = []
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)
        client.fetch_review_statistics_from_logging(limit=1000, min_log_id=5000)

        # Verify SQL contains log_id filter
        call_args = mock_connection_manager.execute_query.call_args[0][0]
        self.assertIn("log_id > 5000", call_args)

    @patch("review_statistics.direct_sql_services.get_wiki_replica_connection")
    def test_fetch_review_statistics_handles_exception(self, mock_get_connection):
        """Test review statistics handles query exceptions."""
        mock_connection_manager = MagicMock()
        mock_connection_manager.execute_query.side_effect = Exception("Query failed")
        mock_get_connection.return_value = mock_connection_manager

        client = DirectSQLStatisticsClient(self.wiki)

        with self.assertRaises(Exception):
            client.fetch_review_statistics_from_logging(limit=1000)

    def test_factory_function(self):
        """Test get_direct_sql_client factory function."""
        with patch("review_statistics.direct_sql_services.get_wiki_replica_connection"):
            client = get_direct_sql_client(self.wiki)

            self.assertIsInstance(client, DirectSQLStatisticsClient)
            self.assertEqual(client.wiki, self.wiki)
