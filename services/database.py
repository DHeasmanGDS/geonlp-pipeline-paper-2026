################################################################################
# Filename: database.py
#
# Purpose: 
# This script contains functions for handling database interactions, 
# including inserting, updating, and retrieving data.
#
# Author: Drew Heasman, P.Geo
# Last Updated: 10-02-2025
#
# Organization: University of Saskatchewan
################################################################################

################################################################################
# Future Improvements
################################################################################

# - Optimize database inserts using batch transactions for better performance.
# - Implement indexing on frequently queried columns (e.g., `word_1`, `word_2`).
# - Add an option to store logs in the database for better tracking.
# - Use a connection pool to optimize database queries under heavy loads.
# - Convert long SQL queries to ORM-based queries using SQLAlchemy models.
# - Create a .env file for database variables
# - Deploy this on a cloud

################################################################################
# Libraries
################################################################################

# Standard Libraries
import csv
import io
import os
import logging
from functools import lru_cache

import pandas as pd
from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker

################################################################################
# Global Variables
################################################################################

# Snapshot constants (pinned for reproducibility — see services/mining_config.py).
# Re-exported here for legacy callers that imported TOTAL_TOKENS_PER_DOCUMENT
# from this module. New code should import from services.mining_config directly.
from services.mining_config import (
    SNAPSHOT_TOKENS_PER_DOCUMENT as TOTAL_TOKENS_PER_DOCUMENT,
    SNAPSHOT_TOTAL_DOCS,
    SNAPSHOT_MAX_ACQUIRED,
)

# ✅ Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

################################################################################
# Retreive and connect to a database
################################################################################

def get_database_engine():
    """
    Load PostgreSQL credentials from environment (.env file) and 
    return a SQLAlchemy engine to connect to cloud PostgreSQL.

    Supports both local and cloud database connections.
    """

    # Load from environment variables
    DB_HOST = os.getenv("DB_HOST")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_NAME = os.getenv("DB_NAME")
    DB_PORT = os.getenv("DB_PORT", "5432")

    # Safety check
    if not all([DB_HOST, DB_USER, DB_PASSWORD, DB_NAME]):
        raise ValueError("❌ Missing database credentials. Check your .env file!")

    # Build the full URL
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # Create SQLAlchemy engine
    return create_engine(DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)


def get_corpus_summary(engine) -> dict:
    """Cheap-to-compute summary metrics for the home and request-term
    pages. All four queries hit small or already-aggregated state — no
    full scans of the partitioned `term_cooccurrence` table.

    Returns a dict with:
      mined_terms        int   — count of `processed_terms`
      total_snippets     int   — SUM(term_counts.count)
      pending_requests   int   — term_requests where status='pending'
      failed_requests    int   — term_requests where status='failed'
      largest_terms      list  — top 5 (word, count) by snippet count
      recently_mined     list  — top 5 (term, processed_at) by completion time

    Falls back gracefully on databases that haven't run the
    0001_term_requests_status migration yet (the queue counts will
    return 0 in that case).
    """
    out: dict = {
        "mined_terms": 0,
        "total_snippets": 0,
        "pending_requests": 0,
        "failed_requests": 0,
        "largest_terms": [],
        "recently_mined": [],
        # Snapshot params pinned in services/mining_config.py — exposed
        # here so the home page can display the right doc-count and
        # snapshot date without hardcoding values that drift on rebuild.
        "snapshot_max_acquired": SNAPSHOT_MAX_ACQUIRED,
        "snapshot_total_docs":   SNAPSHOT_TOTAL_DOCS,
        "snapshot_tokens_per_doc": TOTAL_TOKENS_PER_DOCUMENT,
    }

    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM processed_terms"
            )).fetchone()
            out["mined_terms"] = int(row[0] or 0) if row else 0

            row = conn.execute(text(
                "SELECT COALESCE(SUM(count), 0) FROM term_counts"
            )).fetchone()
            out["total_snippets"] = int(row[0] or 0) if row else 0

            out["largest_terms"] = [
                {"word": r.word, "count": int(r.count or 0)}
                for r in conn.execute(text(
                    "SELECT word, count FROM term_counts "
                    "WHERE count IS NOT NULL "
                    "ORDER BY count DESC LIMIT 5"
                ))
            ]
    except Exception:
        # Connection or schema problem — leave the safe defaults above.
        return out

    # The next two depend on the migration. Wrap in their own try.
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM term_requests WHERE status='pending'"
            )).fetchone()
            out["pending_requests"] = int(row[0] or 0) if row else 0

            row = conn.execute(text(
                "SELECT COUNT(*) FROM term_requests WHERE status='failed'"
            )).fetchone()
            out["failed_requests"] = int(row[0] or 0) if row else 0

            out["recently_mined"] = [
                {"term": r.term, "processed_at": r.processed_at}
                for r in conn.execute(text(
                    "SELECT term, processed_at FROM term_requests "
                    "WHERE status='done' AND processed_at IS NOT NULL "
                    "ORDER BY processed_at DESC LIMIT 5"
                ))
            ]
    except Exception:
        # Pre-migration schema. Counts stay 0; recently_mined stays [].
        pass

    return out


def get_pending_queue(engine, limit: int = 25) -> list[dict]:
    """List of pending term_requests rows ordered FIFO. Used by the
    /request-term page to give users visibility into the queue."""
    sql = text(
        "SELECT id, term, requested_at FROM term_requests "
        "WHERE status='pending' ORDER BY requested_at LIMIT :limit"
    )
    try:
        with engine.connect() as conn:
            return [
                {
                    "id": r.id,
                    "term": r.term,
                    "requested_at": r.requested_at,
                }
                for r in conn.execute(sql, {"limit": limit})
            ]
    except Exception:
        return []


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-wide singleton engine, created lazily on first call.

    Use as a FastAPI dependency so handlers receive the shared engine
    without import-time side effects:

        from fastapi import Depends
        from services.database import get_engine

        @router.get("/foo")
        def handler(engine: Engine = Depends(get_engine)):
            with engine.connect() as conn:
                ...

    SQLAlchemy's create_engine is lazy at the network layer (no connection
    until first query), and the engine itself is thread-safe, so a single
    cached instance shared across all requests is the intended pattern.

    Tests can swap the dependency cleanly:

        from app.main import app
        from services.database import get_engine
        app.dependency_overrides[get_engine] = lambda: fake_engine
    """
    return get_database_engine()

################################################################################
# Insert and Update Database Functions
################################################################################

# Main Function for Importing data into SQL database
def process_and_import_data(root_folder, total_documents, engine, skip_processed=True):
    """
    Processes and imports term-specific data from CSV files into a PostgreSQL database.

    This function scans subfolders within the `root_folder`, processes relevant CSV files, 
    and inserts data into the database. If `skip_processed` is enabled, terms already 
    recorded in the `processed_terms` table are skipped.

    The function performs the following:
    - **Checks if a term has already been processed** (if `skip_processed=True`).
    - **Processes term frequency data** and updates the `term_counts` table.
    - **Processes co-occurrence statistics** and inserts them into the `term_cooccurrence` table.
    - **Records the processed term** in the `processed_terms` table.

    Parameters:
    ----------
    root_folder : str
        Path to the directory containing subfolders for each search term.
    
    total_documents : int
        The total number of documents in the dataset, used for probability calculations.

    engine : sqlalchemy.engine.base.Engine
        SQLAlchemy database engine connected to the PostgreSQL database.

    skip_processed : bool, optional
        If True, skips processing for terms already present in the `processed_terms` table 
        (default: True).

    Returns:
    -------
    None
        Processes and imports data without returning any values.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> process_and_import_data("data/terms", total_documents=1000000, engine=engine, skip_processed=True)

    Features:
    ---------
    - **Efficient Processing**: Skips terms that have already been processed, reducing redundant computation.
    - **Bulk Data Import**: Reads CSV files and inserts data into the appropriate database tables.
    - **Transactional Integrity**: Ensures consistency by committing changes only after all processing steps succeed.
    - **Logging Support**: Logs progress and skipped terms for better tracking.

    Notes:
    ------
    - Expects subfolders named after search terms, each containing:
        - `{term}_processed_text.csv` (word counts)
        - `{term}_cooccurrence_stats.csv` (co-occurrence data)
    - The `processed_terms` table must exist in the database with a unique constraint on `term`.
    - If a CSV file does not exist for a term, that term is skipped without error.
    """

    for term_folder in os.listdir(root_folder):
        term_path = os.path.join(root_folder, term_folder)

        if skip_processed:
            with engine.connect() as connection:
                query = text("SELECT term FROM processed_terms WHERE term = :term")
                result = connection.execute(query, {"term": term_folder}).fetchone()
                if result:
                    logging.info(f"Skipping term '{term_folder}' as it has already been processed.")
                    continue
        
        processed_file = os.path.join(term_path, f"{term_folder}_processed_text.csv")
        if os.path.exists(processed_file):
            raw_df = pd.read_csv(processed_file)
            process_and_update_term_counts(raw_df, term_folder, total_documents, engine)

        stats_file = os.path.join(term_path, f"{term_folder}_cooccurrence_stats.csv")
        if os.path.exists(stats_file):
            stats_df = pd.read_csv(stats_file)
            insert_cooccurrence_to_postgres(engine, stats_df)

        with engine.connect() as connection:
            query = text("""
            INSERT INTO processed_terms (term)
            VALUES (:term)
            ON CONFLICT (term) DO NOTHING
            """)
            connection.execute(query, {"term": term_folder})
            connection.commit()

        logging.info(f"Finished processing term: {term_folder}")
        
    try:
        with engine.connect() as connection:
            connection.execute(text("CALL update_all_statistics();"))
            connection.commit()
            print("✅ Successfully executed `update_all_statistics`.")
    except Exception as e:
        print(f"❌ Error executing `update_all_statistics`: {e}")

def process_and_update_term_counts(raw_df, search_term, total_docs, engine):
    """
    Inserts or updates word occurrence statistics in the `term_counts` table.

    This function calculates the occurrence count of a given search term from a DataFrame, 
    estimates its probability relative to the total number of tokens in the dataset, and 
    inserts or updates the values in the `term_counts` table in a PostgreSQL database. 

    If the term already exists in the table, its count and probability are updated.

    Parameters:
    ----------
    raw_df : pandas.DataFrame
        A DataFrame containing raw snippet data with the following expected structure:
        - `_gddid` (str): Unique document identifier.
        - `highlight` (str): Extracted text snippet containing the search term.

    search_term : str
        The search term whose occurrence count needs to be updated.

    total_docs : int
        The total number of documents in the dataset, used for probability calculation.

    engine : sqlalchemy.engine.base.Engine
        SQLAlchemy database engine connected to the PostgreSQL database.

    Returns:
    -------
    None
        Updates the `term_counts` table with the latest count and probability of the search term.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> import pandas as pd
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> df = pd.DataFrame({
    >>>     "_gddid": ["doc1", "doc2", "doc3"],
    >>>     "highlight": ["Granite is common.", "Granite and basalt occur together.", "Rhyolite is felsic."]
    >>> })
    >>> process_and_update_term_counts(df, "granite", 1000000, engine)

    Features:
    ---------
    - **Word Count Calculation**: Computes how many times the search term appears in the dataset.
    - **Probability Calculation**: Normalizes the count against the total number of tokens in the dataset.
    - **Database Update Handling**: Uses `ON CONFLICT (word) DO UPDATE` to prevent duplicate entries 
      while ensuring that the most recent statistics are stored.
    - **Transactional Integrity**: Ensures data consistency by committing changes within a transaction.

    Notes:
    ------
    - The `term_counts` table must exist with a unique constraint on the `word` column.
    - If `raw_df` is empty, the function does nothing.
    - The database must support PostgreSQL’s `ON CONFLICT` syntax.
    """

    # Count rows in the DataFrame
    row_count = len(raw_df)

    # Calculate total tokens and probability.
    # `total_docs` is passed in by the caller for backward compatibility, but
    # the canonical denominator is the pinned snapshot (SNAPSHOT_TOTAL_DOCS).
    # If a caller passes a different total_docs, we honour it for the count
    # calculation but record the actual snapshot constants in the new
    # mining_* columns so the row is self-describing.
    total_tokens = total_docs * TOTAL_TOKENS_PER_DOCUMENT
    probability = row_count / total_tokens

    # Prepare data for insertion. Stamp every row with the snapshot
    # parameters that were active at mining time so future audits can
    # detect mixed-cohort situations with a single GROUP BY.
    word_counts_data = {
        "word": search_term.lower(),
        "count": row_count,
        "probability": probability,
        "mining_max_acquired": SNAPSHOT_MAX_ACQUIRED,
        "mining_total_docs": SNAPSHOT_TOTAL_DOCS,
        "mining_tokens_per_doc": TOTAL_TOKENS_PER_DOCUMENT,
    }

    # Insert or update the data in the term_counts table
    with engine.connect() as connection:
        query = text("""
        INSERT INTO term_counts (
            word, count, probability,
            mining_max_acquired, mining_total_docs, mining_tokens_per_doc
        )
        VALUES (
            :word, :count, :probability,
            :mining_max_acquired, :mining_total_docs, :mining_tokens_per_doc
        )
        ON CONFLICT (word) DO UPDATE SET
            count = EXCLUDED.count,
            probability = EXCLUDED.probability,
            mining_max_acquired = EXCLUDED.mining_max_acquired,
            mining_total_docs = EXCLUDED.mining_total_docs,
            mining_tokens_per_doc = EXCLUDED.mining_tokens_per_doc;
        """)
        connection.execute(query, word_counts_data)
        connection.commit()  # Ensure the transaction is committed

    print(f"Inserted or updated word_counts data for term: {search_term}")


def insert_cooccurrence_to_postgres(engine, stats_df):
    """
    Inserts co-occurrence statistics into the PostgreSQL database, ensuring no duplicate entries.

    This function takes a DataFrame containing word co-occurrence statistics and 
    inserts it into the `term_cooccurrence` table in PostgreSQL. If a word pair 
    already exists, the entry is updated with the new values.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        SQLAlchemy database engine connected to the PostgreSQL database.

    stats_df : pandas.DataFrame
        A DataFrame containing co-occurrence statistics with the following expected columns:
        - `word_1` (str): The primary search term.
        - `word_2` (str): The co-occurring word.
        - `count` (int): The number of times the pair co-occurred.
        - `prob_w1w2` (float): The calculated probability of co-occurrence.

    Returns:
    -------
    None
        Inserts or updates co-occurrence statistics in the database.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> import pandas as pd
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> df = pd.DataFrame({
    >>>     "word_1": ["granite", "granite"],
    >>>     "word_2": ["basalt", "rhyolite"],
    >>>     "count": [120, 95],
    >>>     "prob_w1w2": [0.0012, 0.00095]
    >>> })
    >>> insert_cooccurrence_to_postgres(engine, df)

    Features:
    ---------
    - **Bulk Insert & Update**: Uses `ON CONFLICT (word_1, word_2) DO UPDATE` 
      to prevent duplicate entries while keeping the latest values.
    - **Performance Optimization**: Converts DataFrame into a list of dictionaries 
      for efficient bulk processing.
    - **Transactional Integrity**: Ensures that all inserts/updates are committed 
      successfully.

    Notes:
    ------
    - Ensure that `term_cooccurrence` table exists with unique constraints on (`word_1`, `word_2`).
    - If `stats_df` is empty, this function does nothing.
    - The database must support PostgreSQL's `ON CONFLICT` syntax.

    """
    
    query = text("""
    INSERT INTO term_cooccurrence
        (word_1, word_2, count, prob_w1w2, mining_max_acquired)
    VALUES
        (:word_1, :word_2, :count, :prob_w1w2, :mining_max_acquired)
    ON CONFLICT (word_1, word_2) DO UPDATE SET
        count = EXCLUDED.count,
        prob_w1w2 = EXCLUDED.prob_w1w2,
        mining_max_acquired = EXCLUDED.mining_max_acquired;
    """)

    # If the caller didn't stamp the snapshot date already (older callers),
    # fill it in from the pinned config so this column never goes NULL.
    if "mining_max_acquired" not in stats_df.columns:
        stats_df = stats_df.copy()
        stats_df["mining_max_acquired"] = SNAPSHOT_MAX_ACQUIRED

    data = stats_df.to_dict(orient="records")

    with engine.connect() as connection:
        for row in data:
            connection.execute(query, row)
        connection.commit()


def insert_cooccurrence_via_copy(engine, stats_df):
    """Bulk-insert co-occurrence rows via Postgres COPY FROM STDIN.

    Roughly two orders of magnitude faster than per-row INSERT for large
    DataFrames (a single mined term can produce tens of thousands of pair
    rows). On any failure we fall back to the row-by-row INSERT path so a
    single bad row doesn't lose the whole batch.

    Expects `stats_df` to have columns: word_1, word_2, count, prob_w1w2.
    The target table must have a UNIQUE constraint on (word_1, word_2);
    we COPY into a TEMP table and then INSERT … ON CONFLICT into the real
    table so existing rows are updated rather than rejected.
    """
    if stats_df is None or stats_df.empty:
        return

    cols = ["word_1", "word_2", "count", "prob_w1w2"]
    df = stats_df[cols].dropna(subset=["word_1", "word_2"])
    df = df[df["word_2"].astype(str).str.strip() != ""]
    if df.empty:
        return

    # Stamp every row with the snapshot date so the cohort can be
    # identified later. Column added by the 2026-05-18 schema migration.
    df = df.copy()
    df["mining_max_acquired"] = SNAPSHOT_MAX_ACQUIRED

    buf = io.StringIO()
    df.to_csv(buf, sep=",", header=False, index=False, quoting=csv.QUOTE_ALL)
    buf.seek(0)

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        try:
            # Stage in a temp table, then upsert. Avoids unique-violation
            # failures on (word_1, word_2) when re-mining a term.
            cur.execute("""
                CREATE TEMP TABLE _stage_cooc (
                    word_1 text,
                    word_2 text,
                    count bigint,
                    prob_w1w2 double precision,
                    mining_max_acquired date
                ) ON COMMIT DROP
            """)
            cur.copy_expert(
                "COPY _stage_cooc "
                "(word_1, word_2, count, prob_w1w2, mining_max_acquired) "
                "FROM STDIN WITH CSV",
                buf,
            )
            cur.execute("""
                INSERT INTO term_cooccurrence
                    (word_1, word_2, count, prob_w1w2, mining_max_acquired)
                SELECT word_1, word_2, count, prob_w1w2, mining_max_acquired
                FROM _stage_cooc
                ON CONFLICT (word_1, word_2) DO UPDATE SET
                    count = EXCLUDED.count,
                    prob_w1w2 = EXCLUDED.prob_w1w2,
                    mining_max_acquired = EXCLUDED.mining_max_acquired
            """)
            raw.commit()
        finally:
            cur.close()
    except Exception:
        raw.rollback()
        # Fall back to the safer row-by-row path so we don't lose all data
        # to one malformed row.
        insert_cooccurrence_to_postgres(engine, df)
    finally:
        raw.close()

def remove_term(engine, term):
    """
    Removes a given term from multiple database tables, ensuring data consistency.

    This function deletes all occurrences of the specified term from the `processed_terms`, 
    `term_cooccurrence`, and `term_counts` tables in a PostgreSQL database. It ensures 
    transactional integrity, meaning that if any deletion fails, no partial deletions occur.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        SQLAlchemy database engine connected to the PostgreSQL database.

    term : str
        The term to be removed from the database. The function automatically trims whitespace 
        and converts it to lowercase before executing deletions.

    Returns:
    -------
    None
        Deletes the term from all relevant tables in the database.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> remove_term(engine, "granite")

    Features:
    ---------
    - **Multi-Table Deletion**: Removes the term from:
      - `processed_terms` (where `term` is the primary key)
      - `term_cooccurrence` (where the term appears as `word_1` or `word_2`)
      - `term_counts` (where `word` is the primary key)
    - **Transactional Safety**: Uses a single transaction to ensure atomicity.
    - **Case-Insensitive Processing**: Automatically converts the input term to lowercase.
    - **Graceful Error Handling**: Rolls back changes and prints errors if an issue occurs.
    
    Notes:
    ------
    - Ensure that the `processed_terms`, `term_cooccurrence`, and `term_counts` tables exist.
    - If the term does not exist in any table, the function will execute successfully but make no changes.
    - This function does **not** check for cascading dependencies in other tables.
    - For large databases, indexing `word_1`, `word_2`, and `word` can improve performance.

    """

    term = term.strip().lower()

    queries = [
        text("DELETE FROM processed_terms WHERE term = :term"),
        text("DELETE FROM term_cooccurrence WHERE word_1 = :term OR word_2 = :term"),
        text("DELETE FROM term_counts WHERE word = :term")
    ]

    try:
        # Create session
        Session = sessionmaker(bind=engine)
        session = Session()

        # Execute queries in a transaction
        for query in queries:
            session.execute(query, {"term": term})

        session.commit()
        print(f"✅ Successfully removed '{term}' from the database.")

    except Exception as e:
        session.rollback()
        print(f"❌ Error removing term '{term}': {e}")

    finally:
        session.close()

################################################################################
# Retrieve Data from Database Functions
################################################################################
def get_entropy_from_db(word: str, engine):
    query = "SELECT probability FROM term_counts WHERE word = :word"
    with engine.connect() as connection:
        result = connection.execute(text(query), {"word": word}).fetchone()
        return result[0] if result else None
        
def display_probabilities(word_1, word_2, engine):
    """
    Retrieves and displays co-occurrence probabilities between two words in a Markdown table.

    This function queries the database for co-occurrence probabilities of `word_1` and `word_2`. 
    If data is found, it prints the probability values in a formatted table; otherwise, 
    it notifies the user that no data is available.

    Parameters:
    ----------
    word_1 : str
        The first word for co-occurrence analysis.

    word_2 : str
        The second word for co-occurrence analysis.

    engine : sqlalchemy.engine.base.Engine
        SQLAlchemy database engine connected to the PostgreSQL database.

    Returns:
    -------
    None
        The function prints the results in a human-readable format.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> display_probabilities("granite", "basalt", engine)

    Features:
    ---------
    - **Database Querying**: Fetches probabilities from the database using `get_probabilities_from_db()`.
    - **Formatted Output**: Prints probabilities in a clear, structured format.
    - **Error Handling**: Notifies the user if no data is found.

    Notes:
    ------
    - The function relies on `get_probabilities_from_db()` to fetch data.
    - Expected data structure includes:
        - `p_co_occurrence`: Probability of `word_1` and `word_2` occurring together.
        - `p_word_1`: Probability of `word_1` occurring independently.
        - `p_word_2`: Probability of `word_2` occurring independently.
        - `p_neither`: Probability that neither `word_1` nor `word_2` occurs.
        - `co_occurrence_count`: Count of co-occurrence events.
    - If no data is found, an appropriate message is displayed.
    """
    
    probabilities = get_probabilities_from_db(word_1, word_2, engine)
    
    if probabilities:
        print(f"Co-occurrence probabilities for '{word_1}' and '{word_2}':")
        print(f"- Probability of Co-occurrence: {probabilities['p_co_occurrence']}")
        print(f"- Probability of '{word_1}': {probabilities['p_word_1']}")
        print(f"- Probability of '{word_2}': {probabilities['p_word_2']}")
        print(f"- Probability that Neither Occurs: {probabilities['p_neither']}")
        print(f"- Co-occurrence Count: {probabilities['co_occurrence_count']}")
    else:
        print(f"No data found for '{word_1}' and '{word_2}'")


def get_probabilities_from_db(word_1, word_2, engine):
    """
    Retrieves co-occurrence probabilities for two words from the PostgreSQL database.

    This function queries the `term_cooccurrence` table to obtain the probability 
    of `word_1` and `word_2` appearing together, as well as their independent probabilities.
    If the words exist in the database, the function returns a dictionary of probability values.

    Parameters:
    ----------
    word_1 : str
        The first word for co-occurrence analysis.

    word_2 : str
        The second word for co-occurrence analysis.

    engine : sqlalchemy.engine.base.Engine
        SQLAlchemy database engine connected to the PostgreSQL database.

    Returns:
    -------
    dict or None
        A dictionary containing the following probability metrics:
        - `p_word_1`: Probability of `word_1` occurring independently.
        - `p_word_2`: Probability of `word_2` occurring independently.
        - `co_occurrence_count`: Number of times `word_1` and `word_2` co-occurred.
        - `p_co_occurrence`: Probability of `word_1` and `word_2` occurring together.
        - `p_neither`: Probability that neither `word_1` nor `word_2` occurs.
        
        If no data is found, returns `None`.

    Example Usage:
    --------------
    >>> from sqlalchemy import create_engine
    >>> engine = create_engine("postgresql://user:password@localhost:5432/mydatabase")
    >>> probabilities = get_probabilities_from_db("granite", "basalt", engine)
    >>> print(probabilities)

    Features:
    ---------
    - **Database Querying**: Joins `term_cooccurrence` and `term_counts` tables 
      to retrieve probability values.
    - **Error Handling**: Returns `None` if no data is found.
    - **Tuple to Dictionary Conversion**: Ensures query results are properly formatted.

    Notes:
    ------
    - Assumes the existence of the following PostgreSQL tables:
        - `term_cooccurrence` (columns: `word_1`, `word_2`, `count`, `prob_w1w2`)
        - `term_counts` (columns: `word`, `probability`)
    - Uses `LEFT JOIN` to handle missing probability values gracefully.
    - The `p_neither` probability is calculated as:
      `1 - p_co_occurrence - p_word_1 - p_word_2`, ensuring valid probability distributions.
    """
    
    query = """
    SELECT 
        wc1.probability AS p_word_1,
        wc2.probability AS p_word_2,
        wc.count AS co_occurrence_count,
        wc.prob_w1w2 AS p_co_occurrence,
        1 - COALESCE(wc.prob_w1w2, 0) - COALESCE(wc1.probability, 0) - COALESCE(wc2.probability, 0) AS p_neither,
        wc.word_1,
        wc.word_2
    FROM 
        term_cooccurrence wc
    LEFT JOIN 
        term_counts wc1 ON wc.word_1 = wc1.word
    LEFT JOIN 
        term_counts wc2 ON wc.word_2 = wc2.word
    WHERE 
        (wc.word_1 = :word_1 AND wc.word_2 = :word_2)
        OR
        (wc.word_1 = :word_2 AND wc.word_2 = :word_1)
    LIMIT 1;
    """

    with engine.connect() as connection:
        result = connection.execute(
                                text(query),
                                {"word_1": word_1, "word_2": word_2}
                            ).fetchone()
        print("Raw Result:", result)  # ✅ Check what is returned
    
    if result:
        # Fix: Convert tuple to dictionary manually
        keys = ["p_word_1", "p_word_2", "co_occurrence_count", "p_co_occurrence", "p_neither"]
        result_dict = dict(zip(keys, result))  # Convert tuple to dictionary
        return result_dict

    return None
    
def get_top_mi_words(engine, search_term, top_n=10, output_csv="top_mi_words.csv"):
    """
    Retrieves the top N co-occurring words for a given search term based on mutual information,
    plots Entropy vs. MI and Joint Entropy vs. MI, and saves the results as a CSV.

    Parameters:
    ----------
    engine : sqlalchemy.engine.base.Engine
        The database engine connection.
    search_term : str
        The term for which co-occurrences will be retrieved.
    top_n : int, optional, default=10
        The number of top co-occurring words to retrieve.
    output_csv : str, optional
        Filename to save the results.

    Returns:
    -------
    pd.DataFrame
        A DataFrame containing co-occurrence word pairs, probabilities, word counts,
        entropy, mutual information, and calculated joint entropy.
    """
    import pandas as pd
    import matplotlib.pyplot as plt
    from IPython.display import display, HTML

    def format_scientific(x):
        try:
            return f"{float(x):.2e}"
        except:
            return x

    query = """
    SELECT 
        tc.word_2 AS "Word",
        tc.count AS "Co-occurrence Count",
        tc.prob_w1w2 AS "Probability",
        tc.mutual_information AS "Mutual Information",
        t.count AS "Word Count",
        t.entropy AS "Entropy"
    FROM term_cooccurrence tc
    LEFT JOIN term_counts t ON tc.word_2 = t.word
    WHERE tc.word_1 = %s AND tc.mutual_information IS NOT NULL
    ORDER BY tc.mutual_information DESC
    LIMIT %s;
    """

    with engine.connect() as connection:
        df = pd.read_sql_query(query, connection, params=(search_term, top_n))

    if df.empty:
        print(f"No mutual information data found for '{search_term}'.")
        return df

    # Convert numerical fields to floats
    for col in ["Probability", "Mutual Information", "Entropy"]:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Compute Joint Entropy H(X,Y) ≈ H(Y) - I(X;Y)
    df["Joint Entropy"] = df["Entropy"] - df["Mutual Information"]

    # Save to CSV
    df.to_csv(output_csv, index=False)

    # Plot Entropy vs MI
    plt.figure()
    plt.scatter(df["Mutual Information"], df["Entropy"])
    plt.xlabel("Mutual Information")
    plt.ylabel("Entropy")
    plt.title(f"Entropy vs. MI for '{search_term}'")
    plt.grid(True)
    plt.show()

    # Plot Joint Entropy vs MI
    plt.figure()
    plt.scatter(df["Mutual Information"], df["Joint Entropy"])
    plt.xlabel("Mutual Information")
    plt.ylabel("Joint Entropy (H(Y) - I(X;Y))")
    plt.title(f"Joint Entropy vs. MI for '{search_term}'")
    plt.grid(True)
    plt.show()

    # Display nicely formatted table
    for col in ["Probability", "Mutual Information", "Entropy", "Joint Entropy"]:
        df[col] = df[col].apply(format_scientific)

    html_table = df.to_html(escape=False, index=False)
    display(HTML(html_table))

    return df

