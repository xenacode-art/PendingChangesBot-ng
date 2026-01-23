from __future__ import annotations

from unittest.mock import MagicMock, patch

import pymysql
import pytest
from django.test import TestCase
from review_statistics.wiki_replica_connection import (
    WikiReplicaConnection,
    get_wiki_replica_connection,
)
from reviews.models import Wiki


class WikiReplicaConnectionTests(TestCase):
    """Tests for WikiReplicaConnection class."""

    def setUp(self):
        """Set up test fixtures."""
        self.wiki = Wiki.objects.create(
            name="Finnish Wikipedia",
            code="fi",
            family="wikipedia",
            api_endpoint="https://fi.wikipedia.org/w/api.php",
        )
        self.connection_manager = WikiReplicaConnection(self.wiki)

    def test_get_database_name_wikipedia(self):
        """Test database name construction for Wikipedia."""
        result = self.connection_manager.get_database_name()
        self.assertEqual(result, "fiwiki_p")

    def test_get_database_name_wiktionary(self):
        """Test database name construction for Wiktionary."""
        wiktionary = Wiki.objects.create(
            name="English Wiktionary",
            code="en",
            family="wiktionary",
            api_endpoint="https://en.wiktionary.org/w/api.php",
        )
        connection_manager = WikiReplicaConnection(wiktionary)
        result = connection_manager.get_database_name()
        self.assertEqual(result, "enwiktionary_p")

    def test_get_host_wikipedia(self):
        """Test hostname construction for Wikipedia."""
        result = self.connection_manager.get_host()
        self.assertEqual(result, "fiwiki.analytics.db.svc.wikimedia.cloud")

    def test_get_host_wiktionary(self):
        """Test hostname construction for Wiktionary."""
        wiktionary = Wiki.objects.create(
            name="English Wiktionary",
            code="en",
            family="wiktionary",
            api_endpoint="https://en.wiktionary.org/w/api.php",
        )
        connection_manager = WikiReplicaConnection(wiktionary)
        result = connection_manager.get_host()
        self.assertEqual(result, "enwiktionary.analytics.db.svc.wikimedia.cloud")

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_get_connection_success(self, mock_connect):
        """Test successful connection creation."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with self.connection_manager.get_connection() as conn:
            self.assertEqual(conn, mock_conn)

        # Verify connection was closed
        mock_conn.close.assert_called_once()

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_get_connection_uses_correct_params(self, mock_connect):
        """Test connection uses correct parameters."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with self.connection_manager.get_connection():
            pass

        # Verify pymysql.connect was called with correct params
        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args[1]
        self.assertEqual(call_kwargs["host"], "fiwiki.analytics.db.svc.wikimedia.cloud")
        self.assertEqual(call_kwargs["database"], "fiwiki_p")
        self.assertEqual(call_kwargs["charset"], "utf8mb4")
        self.assertEqual(call_kwargs["cursorclass"], pymysql.cursors.DictCursor)

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_get_connection_closes_on_exception(self, mock_connect):
        """Test connection is closed even when exception occurs."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with pytest.raises(ValueError):
            with self.connection_manager.get_connection():
                raise ValueError("Test error")

        # Connection should still be closed
        mock_conn.close.assert_called_once()

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_get_connection_handles_connect_error(self, mock_connect):
        """Test connection handles pymysql connection errors."""
        mock_connect.side_effect = pymysql.Error("Connection failed")

        with pytest.raises(pymysql.Error):
            with self.connection_manager.get_connection():
                pass

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_execute_query_success(self, mock_connect):
        """Test successful query execution."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "Test"},
            {"id": 2, "name": "Test2"},
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.connection_manager.execute_query("SELECT * FROM test")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], 1)
        mock_cursor.execute.assert_called_once_with("SELECT * FROM test")
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_execute_query_handles_error(self, mock_connect):
        """Test query execution handles errors."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = pymysql.Error("Query failed")
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        with pytest.raises(pymysql.Error):
            self.connection_manager.execute_query("SELECT * FROM test")

        # Cursor and connection should still be closed
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_execute_query_with_params_success(self, mock_connect):
        """Test parameterized query execution."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "Test"}]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.connection_manager.execute_query_with_params(
            "SELECT * FROM test WHERE id = %s", (1,)
        )

        self.assertEqual(len(result), 1)
        mock_cursor.execute.assert_called_once_with("SELECT * FROM test WHERE id = %s", (1,))
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("review_statistics.wiki_replica_connection.pymysql.connect")
    def test_execute_query_with_params_dict(self, mock_connect):
        """Test parameterized query with dict params."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"id": 1, "name": "Test"}]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = self.connection_manager.execute_query_with_params(
            "SELECT * FROM test WHERE id = %(id)s", {"id": 1}
        )

        self.assertEqual(len(result), 1)
        mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM test WHERE id = %(id)s", {"id": 1}
        )

    def test_factory_function(self):
        """Test get_wiki_replica_connection factory function."""
        connection_manager = get_wiki_replica_connection(self.wiki)

        self.assertIsInstance(connection_manager, WikiReplicaConnection)
        self.assertEqual(connection_manager.wiki, self.wiki)
        self.assertEqual(connection_manager.get_database_name(), "fiwiki_p")
        self.assertEqual(connection_manager.get_host(), "fiwiki.analytics.db.svc.wikimedia.cloud")

    def test_credentials_file_path(self):
        """Test credentials file path is expanded."""
        self.assertIn("replica.my.cnf", self.connection_manager.credentials_file)
