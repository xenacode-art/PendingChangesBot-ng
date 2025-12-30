"""
Direct SQL connection management for wiki replica databases.

This module implements Zache's recommended approach for connecting to wiki replicas:
- Open connections using DNS names when needed (for refreshing data)
- Close connections immediately after use to avoid exhausting connection pools
- Each wiki database is on a specific server accessible via DNS (e.g., fiwiki.analytics.db.svc.wikimedia.cloud)

This approach avoids the problem of running out of connections when dealing with hundreds of wiki databases.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pymysql

if TYPE_CHECKING:
    from reviews.models import Wiki

logger = logging.getLogger(__name__)


class WikiReplicaConnection:
    """Manages direct SQL connections to wiki replica databases."""

    def __init__(self, wiki: Wiki):
        """
        Initialize connection manager for a specific wiki.

        Args:
            wiki: The Wiki model instance
        """
        self.wiki = wiki
        self.credentials_file = os.path.expanduser("~/replica.my.cnf")

    def get_database_name(self) -> str:
        """
        Get the replica database name for this wiki.

        Returns:
            Database name with _p suffix (e.g., 'fiwiki_p')
        """
        # Construct database name: code + family_short + _p
        # e.g., "fi" + "wiki" (from "wikipedia") + "_p" = "fiwiki_p"
        family_short = "wiki" if self.wiki.family == "wikipedia" else self.wiki.family
        return f"{self.wiki.code}{family_short}_p"

    def get_host(self) -> str:
        """
        Get the database host DNS name for this wiki's replica.

        Returns:
            Host DNS name (e.g., 'fiwiki.analytics.db.svc.wikimedia.cloud')
        """
        # Construct hostname: code + family_short + .analytics.db.svc.wikimedia.cloud
        # e.g., "fi" + "wiki" = "fiwiki.analytics.db.svc.wikimedia.cloud"
        family_short = "wiki" if self.wiki.family == "wikipedia" else self.wiki.family
        return f"{self.wiki.code}{family_short}.analytics.db.svc.wikimedia.cloud"

    @contextmanager
    def get_connection(self):
        """
        Context manager that creates a connection and ensures it's closed.

        This implements Zache's recommendation: open connection when needed,
        close it immediately after use.

        Usage:
            with connection_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                results = cursor.fetchall()

        Yields:
            PyMySQL connection object
        """
        connection = None
        try:
            logger.info(
                "Opening connection to %s (database: %s)",
                self.get_host(),
                self.get_database_name(),
            )

            connection = pymysql.connect(
                host=self.get_host(),
                database=self.get_database_name(),
                read_default_file=self.credentials_file,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,  # Return results as dictionaries
            )

            yield connection

        except pymysql.Error as e:
            logger.error(
                "Failed to connect to %s: %s",
                self.get_host(),
                str(e),
            )
            raise

        finally:
            if connection:
                connection.close()
                logger.info(
                    "Closed connection to %s",
                    self.get_host(),
                )

    def execute_query(self, sql: str) -> list[dict[str, Any]]:
        """
        Execute a SQL query and return results.

        This method opens a connection, executes the query, fetches all results,
        and closes the connection. Perfect for Zache's recommended pattern.

        Args:
            sql: SQL query string

        Returns:
            List of dictionaries containing query results

        Raises:
            pymysql.Error: If query execution fails
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                results = cursor.fetchall()
                logger.info(
                    "Query executed successfully on %s, returned %d rows",
                    self.wiki.code,
                    len(results),
                )
                return results
            finally:
                cursor.close()

    def execute_query_with_params(
        self, sql: str, params: tuple | dict
    ) -> list[dict[str, Any]]:
        """
        Execute a parameterized SQL query and return results.

        Uses parameterized queries to prevent SQL injection.

        Args:
            sql: SQL query string with placeholders
            params: Parameters for the query (tuple or dict)

        Returns:
            List of dictionaries containing query results

        Raises:
            pymysql.Error: If query execution fails
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params)
                results = cursor.fetchall()
                logger.info(
                    "Parameterized query executed successfully on %s, returned %d rows",
                    self.wiki.code,
                    len(results),
                )
                return results
            finally:
                cursor.close()


def get_wiki_replica_connection(wiki: Wiki) -> WikiReplicaConnection:
    """
    Factory function to create a WikiReplicaConnection instance.

    Args:
        wiki: The Wiki model instance

    Returns:
        WikiReplicaConnection instance for the specified wiki
    """
    return WikiReplicaConnection(wiki)
