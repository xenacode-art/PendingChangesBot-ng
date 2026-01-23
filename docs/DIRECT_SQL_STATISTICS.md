# Direct SQL Statistics Implementation

This document describes the direct SQL implementation for loading statistics from wiki replica databases, replacing the previous Pywikibot SupersetQuery approach.

## Overview

The direct SQL implementation was created to address connection pool exhaustion issues when querying wiki replica databases. Following Zache's recommendation, this approach opens database connections only when needed and closes them immediately after use.

## Supported Wikis

**Important:** Not all Wikimedia projects have the FlaggedRevs extension enabled. This statistics implementation only works with wikis that have FlaggedRevs tables in their replica databases.

### Confirmed Working Wikis

These Wikipedias have been tested and confirmed to have FlaggedRevs enabled:

- ✅ **Finnish Wikipedia (fi)** - 169 FlaggedRevs statistics records
- ✅ **German Wikipedia (de)** - 172 FlaggedRevs statistics records

### Wikis Known to Support FlaggedRevs

Based on MediaWiki documentation, these Wikipedias should also work (not yet tested):

- **Polish Wikipedia (pl)**
- **Russian Wikipedia (ru)**
- **Czech Wikipedia (cs)**

### Wikis WITHOUT FlaggedRevs

These Wikipedias do **not** have FlaggedRevs enabled and will return "Table doesn't exist" errors:

- ❌ **English Wikipedia (en)** - No FlaggedRevs
- ❌ **Swedish Wikipedia (sv)** - No FlaggedRevs

### How to Check if a Wiki Has FlaggedRevs

Before attempting to load statistics for a new wiki:

1. Check the [FlaggedRevs configuration page](https://www.mediawiki.org/wiki/Extension:FlaggedRevs#Configured_wikis)
2. Or try loading a small dataset and check for errors:
   ```bash
   TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql --wiki <code>
   ```
3. If you see `Table 'xxxwiki_p.flaggedrevs_statistics' doesn't exist`, the wiki doesn't have FlaggedRevs

## Architecture

### Components

1. **WikiReplicaConnection** (`review_statistics/wiki_replica_connection.py`)
   - Manages connections to wiki-specific replica databases
   - Uses context manager pattern for automatic cleanup
   - Connects to hosts like `fiwiki.analytics.db.svc.wikimedia.cloud`

2. **DirectSQLStatisticsClient** (`review_statistics/direct_sql_services.py`)
   - Provides high-level methods for fetching statistics
   - Executes SQL queries against replica databases
   - Returns structured data for Django models

3. **Management Commands**
   - `load_flaggedrevs_statistics_direct_sql` - Load monthly aggregates
   - `load_review_statistics_direct_sql` - Load individual review records

### Database Naming Convention

Wiki replica databases follow this naming pattern:
- **Database name**: `{wiki_code}{family}_p` (e.g., `fiwiki_p`)
- **Hostname**: `{wiki_code}{family}.analytics.db.svc.wikimedia.cloud` (e.g., `fiwiki.analytics.db.svc.wikimedia.cloud`)

For Wikipedia projects, `family` is converted to `wiki`:
- Finnish Wikipedia: `fi` + `wiki` = `fiwiki_p`
- English Wiktionary: `en` + `wiktionary` = `enwiktionary_p`

## Usage

### Loading FlaggedRevs Statistics

Monthly aggregates from the `flaggedrevs_statistics` table:

```bash
# Load statistics for Finnish Wikipedia
TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql --wiki fi

# Load with specific date range
TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql \
  --wiki fi \
  --start-date 2020-01-01 \
  --end-date 2024-12-31

# Full refresh (delete and reload)
TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql \
  --wiki fi \
  --full-refresh

# Change resolution to daily or yearly
TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql \
  --wiki fi \
  --resolution daily
```

**Auto-continuation:** If no date parameters are provided, the command automatically continues from the last loaded month.

### Loading Individual Review Records

Detailed review records from the `logging` table:

```bash
# Load 10,000 records
TOOLFORGE_DEPLOYMENT=true python manage.py load_review_statistics_direct_sql \
  --wiki fi \
  --limit 10000

# Load 50,000 records
TOOLFORGE_DEPLOYMENT=true python manage.py load_review_statistics_direct_sql \
  --wiki fi \
  --limit 50000

# Clear existing data and reload
TOOLFORGE_DEPLOYMENT=true python manage.py load_review_statistics_direct_sql \
  --wiki fi \
  --limit 10000 \
  --clear
```

**Incremental loading:** The command tracks `max_log_id` and automatically continues from where it left off.

## Data Models

### FlaggedRevsStatistics
Monthly aggregate statistics:
- `total_pages_ns0` - Total articles in main namespace
- `synced_pages_ns0` - Articles reviewed to current revision
- `reviewed_pages_ns0` - Articles with at least one reviewed revision
- `pending_lag_average` - Average time articles wait for review
- `pending_changes` - Calculated as reviewedPages - syncedPages

### ReviewActivity
Monthly reviewer activity:
- `number_of_reviewers` - Unique reviewers
- `number_of_reviews` - Total reviews
- `number_of_pages` - Pages reviewed
- `reviews_per_reviewer` - Average reviews per reviewer

### ReviewStatisticsCache
Individual review records:
- `reviewer_name` - Who performed the review
- `reviewed_user_name` - Whose edit was reviewed
- `page_title` - Article name
- `reviewed_timestamp` - When review occurred
- `pending_timestamp` - When edit was made
- `review_delay_days` - Days between edit and review

## SQL Queries

### FlaggedRevs Statistics Query

Aggregates data from the `flaggedrevs_statistics` table:

```sql
SELECT
    FLOOR(d/100) as yearmonth,
    AVG(totalPages_ns0) AS totalPages_ns0_avg,
    AVG(syncedPages_ns0) AS syncedPages_ns0_avg,
    AVG(reviewedPages_ns0) AS reviewedPages_ns0_avg,
    AVG(pendingLag_average) AS pendingLag_average_avg
FROM (
  SELECT
    total_ns0.d,
    totalPages_ns0,
    syncedPages_ns0,
    reviewedPages_ns0,
    pendingLag_average
  FROM
  (
    SELECT
      floor(frs_timestamp/1000000) as d,
      AVG(frs_stat_val) AS totalPages_ns0
    FROM flaggedrevs_statistics
    WHERE frs_stat_key = "totalPages-NS:0"
    GROUP BY d
  ) AS total_ns0
  LEFT JOIN ...
) as t
GROUP BY yearmonth
ORDER BY yearmonth
```

### Review Activity Query

Queries the `flaggedrevs` table for reviewer activity:

```sql
SELECT
    FLOOR(d/100) as yearmonth,
    AVG(number_of_reviewers) AS number_of_reviewers_avg,
    AVG(number_of_reviews) AS number_of_reviews_avg,
    AVG(number_of_pages) AS number_of_pages_avg
FROM (
  SELECT
      FLOOR(fr_timestamp/1000000) AS d,
      COUNT(DISTINCT(fr_user)) AS number_of_reviewers,
      SUM(1) AS number_of_reviews,
      COUNT(DISTINCT(fr_page_id)) AS number_of_pages
  FROM flaggedrevs
  WHERE fr_flags NOT LIKE "%auto%"
        AND fr_timestamp >= {start_date}
  GROUP BY d
) as t
GROUP BY yearmonth
ORDER BY yearmonth
```

### Review Statistics from Logging

Fetches individual review records with delay calculations:

```sql
SELECT
    l.log_id,
    l.log_page AS page_id,
    l.log_title AS page_title,
    l.log_user_name AS reviewer_name,
    a2.actor_name AS reviewed_user_name,
    l.reviewed_revision_id,
    r.rev_id AS pending_revision_id,
    l.log_timestamp AS reviewed_timestamp,
    r.rev_timestamp AS pending_timestamp,
    TIMESTAMPDIFF(DAY, r.rev_timestamp, l.log_timestamp) AS review_delay_days
FROM (
    SELECT
        log_id,
        log_page,
        log_title,
        log_timestamp,
        a1.actor_name AS log_user_name,
        CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(log_params, 'i:0;i:', -1), ';', 1) AS UNSIGNED) AS reviewed_revision_id,
        CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(log_params, 'i:1;i:', -1), ';', 1) AS UNSIGNED) AS extracted_id
    FROM logging AS lg
    JOIN actor_logging AS a1 ON lg.log_actor = a1.actor_id
    WHERE lg.log_namespace = 0
      AND lg.log_type = 'review'
      AND lg.log_action IN ('approve', 'approve2')
    ORDER BY lg.log_id ASC
    LIMIT {limit}
) AS l
INNER JOIN flaggedrevs AS fr ON fr.fr_rev_id = l.reviewed_revision_id
JOIN revision AS r ON r.rev_page = l.log_page
  AND r.rev_id = (
    SELECT r2.rev_id FROM revision AS r2
    WHERE r2.rev_page = l.log_page AND r2.rev_id > l.extracted_id
    ORDER BY r2.rev_id ASC LIMIT 1
  )
JOIN actor_revision AS a2 ON a2.actor_id = r.rev_actor
ORDER BY l.log_id ASC
```

## Connection Management

### Context Manager Pattern

Connections are managed using Python's context manager protocol:

```python
with connection_manager.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
# Connection automatically closed here
```

### Credentials

Connections use the `~/replica.my.cnf` file for authentication, which should already exist on Toolforge.

### Error Handling

The implementation includes comprehensive error handling:
- DNS resolution errors (invalid hostname)
- Connection timeouts
- Query execution failures
- Data parsing errors

## API Integration

### Statistics Refresh Endpoint

The `/api/wikis/<pk>/statistics/refresh/` endpoint uses direct SQL:

```python
@csrf_exempt
@require_http_methods(["POST"])
def api_statistics_refresh(request: HttpRequest, pk: int) -> JsonResponse:
    """Incrementally refresh review statistics using direct SQL."""
    # Get metadata for incremental loading
    metadata, _ = ReviewStatisticsMetadata.objects.get_or_create(wiki=wiki)

    # Fetch new records (limit to 10k per refresh)
    sql_client = get_direct_sql_client(wiki)
    payload = sql_client.fetch_review_statistics_from_logging(
        limit=10000,
        min_log_id=metadata.max_log_id,
    )

    # Process and save records
    # Update metadata
    # Return JSON response
```

## Troubleshooting

### DNS Resolution Errors

**Error:** `Name or service not known`

**Cause:** Incorrect hostname construction

**Solution:** Ensure hostname includes family:
- ❌ Wrong: `fi.analytics.db.svc.wikimedia.cloud`
- ✅ Correct: `fiwiki.analytics.db.svc.wikimedia.cloud`

### Database Access Denied

**Error:** `Access denied for user 's57224'@'%' to database 's57230__pendingchangesbot'`

**Cause:** Incorrect database name in settings

**Solution:** Verify database name matches your Toolforge tool account:
```python
TOOLSDB_NAME = os.environ.get("TOOLSDB_NAME", "s57224__pendingchangesbot")
```


### Table Doesn't Exist

**Error:** `Table 'xxxwiki_p.flaggedrevs_statistics' doesn't exist` or `Table 'xxxwiki_p.flaggedrevs' doesn't exist`

**Cause:** The wiki you're trying to load doesn't have the FlaggedRevs extension enabled

**Solution:**
1. Check the [Supported Wikis](#supported-wikis) section at the top of this document
2. Only use wikis that are confirmed to have FlaggedRevs (fi, de, pl, ru, cs)
3. Avoid wikis like English (en) and Swedish (sv) Wikipedia which don't have FlaggedRevs

**Example:**
```bash
# ✅ This works - Finnish has FlaggedRevs
TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql --wiki fi

# ❌ This fails - Swedish doesn't have FlaggedRevs  
TOOLFORGE_DEPLOYMENT=true python manage.py load_flaggedrevs_statistics_direct_sql --wiki sv
```

### No Data Returned

**Possible causes:**
1. No data exists in the specified date range
2. Wiki replica database is empty (test wiki)
3. SQL query filters are too restrictive

**Debug steps:**
1. Check logs: `tail -100 ~/uwsgi.log`
2. Verify connection: Test with simple query
3. Check date filters in management command

## Performance Considerations

### Connection Pooling

Direct SQL avoids connection pool exhaustion by:
- Opening connections only when needed
- Closing immediately after use
- Not maintaining persistent connections

### Query Optimization

Queries are optimized for:
- Indexed column filtering (`log_id`, `fr_timestamp`)
- Limited result sets (LIMIT clause)
- Efficient JOINs on primary keys

### Incremental Loading

Both commands support incremental loading:
- FlaggedRevs: Auto-continues from last month
- Reviews: Uses `max_log_id` for pagination

This allows loading large datasets in manageable chunks.

## Migration from Pywikibot

If migrating from the old Pywikibot approach:

1. **Stop using** `StatisticsClient` from `reviews.services.wiki_client`
2. **Start using** `get_direct_sql_client()` from `review_statistics.direct_sql_services`
3. **Replace** `client.fetch_review_statistics()` with management commands
4. **Update** refresh endpoints to use direct SQL methods

**Benefits:**
- No connection pool exhaustion
- Faster query execution
- Better error handling
- No Pywikibot authentication required

## Future Enhancements

Potential improvements:
- [ ] Add support for more wikis beyond Wikipedia
- [ ] Implement parallel loading for multiple wikis
- [ ] Add data validation and quality checks
- [ ] Create admin interface for managing loads
- [ ] Add monitoring and alerting for failed loads
- [ ] Support for custom date ranges in API

## References

- [Wikimedia Cloud Services](https://wikitech.wikimedia.org/wiki/Help:Cloud_Services)
- [Wiki Replicas](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Database#User_databases)
- [FlaggedRevs Extension](https://www.mediawiki.org/wiki/Extension:FlaggedRevs)
- [Toolforge Documentation](https://wikitech.wikimedia.org/wiki/Help:Toolforge)
