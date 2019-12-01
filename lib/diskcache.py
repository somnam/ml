import os
import sqlite3
import inspect
from json import dumps, loads
from hashlib import sha1
from functools import wraps
from multiprocessing.dummy import Lock

HOUR = 60
DAY = 24 * HOUR
WEEK = 7 * DAY
MONTH = 30 * WEEK
YEAR = 365 * MONTH


def diskcache(argument=None, *args, **kwargs):
    # Allow decorating methods as @diskcache or @diskcache(args)
    return (diskcache_decorator(argument, *args, **kwargs)
            if callable(argument)
            else lambda function: diskcache_decorator(function, argument, *args, **kwargs))


def diskcache_decorator(function, invalidate_time=None, db_name='./var/diskcache.db'):
    connector = SQLiteConnector(db_name, inspect.getfile(function))

    @wraps(function)
    def diskcache_wrapper(*args, **kwargs):
        # Expire cache if expiration time is reached.
        if invalidate_time:
            connector.invalidate_cache(function.__name__, invalidate_time)
        # Return cached value if present.
        result, hit = connector.get_cache(function.__name__, *args, **kwargs)
        if hit:
            return result

        # Call wrapped method with orginal arguments.
        result = function(*args, **kwargs)

        # Cache call result for given args and kwargs.
        connector.set_cache(result, function.__name__, *args, **kwargs)

        return result
    return diskcache_wrapper


class SQLiteConnector:
    def __init__(self, db_name, file_name):
        self.connection = sqlite3.connect(db_name, check_same_thread=False)
        # Index result rows as dictionaries.
        self.connection.row_factory = sqlite3.Row

        self.cursor = self.connection.cursor()
        self.table = self.get_table(file_name)
        self.lock = Lock()

        self.create_cache_table()

    def create_cache_table(self):
        queries = (
            """CREATE TABLE IF NOT EXISTS {0} (
               function TEXT,
               fingerprint TEXT UNIQUE,
               result BLOB,
               timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""".format(self.table),
            "CREATE INDEX IF NOT EXISTS function_index ON {0} (function)".format(self.table),
        )
        with self.lock:
            with self.connection:
                for query in queries:
                    self.cursor.execute(query)

    def invalidate_cache(self, function_name, invalidate_time):
        # Translate dates difference to minutes.
        query = """DELETE FROM {0} WHERE
                   function = ? AND
                   CAST((JULIANDAY() - JULIANDAY(timestamp)) * 1440 AS INTEGER) >= {1}
                   """.format(self.table, invalidate_time)
        with self.lock:
            with self.connection:
                self.cursor.execute(query, (function_name,))

    def get_cache(self, function_name, *args, **kwargs):
        # Calculate fingerprint for current function and arguments.
        fingerprint = self.get_fingerprint(function_name, *args, **kwargs)

        # Check if fingerprint exists in cache.
        query = """SELECT function, fingerprint, result
                   FROM {0}
                   WHERE fingerprint = ?""".format(self.table)
        with self.lock:
            with self.connection:
                self.cursor.execute(query, (fingerprint,))
                row = self.cursor.fetchone()
        # Decode result value as json, revert to raw value if it fails.
        hit = (True if row else False)
        try:
            result = loads(row['result']) if hit and row['result'] else None
        except (TypeError, UnicodeDecodeError):
            result = row['result']

        return result, hit

    def set_cache(self, result, function_name, *args, **kwargs):
        # Calculate fingerprint for current function and arguments.
        fingerprint = self.get_fingerprint(function_name, *args, **kwargs)
        # Encode result value as json, revert to raw value if it fails.
        try:
            result_value = dumps(result) if result else None
        except TypeError:
            result_value = result

        # Insert result into cache.
        query = """INSERT OR IGNORE INTO {0}(function, fingerprint, result)
                   VALUES (?, ?, ?)""".format(self.table)
        with self.lock:
            with self.connection:
                self.cursor.execute(query,
                                    (function_name, fingerprint, result_value))

    @staticmethod
    def get_table(file_name):
        # Extract file name when full file path is given.
        file_name = os.path.basename(file_name)
        # Keep only alphanumeric characters for table name.
        return ''.join(char for char in file_name.replace('.py', '')
                       if char.isalnum())

    @staticmethod
    def get_fingerprint(function_name, *args, **kwargs):
        return sha1(dumps((function_name, args, kwargs)).encode()).hexdigest()
