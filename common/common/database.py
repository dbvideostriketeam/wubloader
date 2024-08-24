
"""
Code shared between components that touch the database.
Note that this code requires psycopg2 and psycogreen, but the common module
as a whole does not to avoid needing to install them for components that don't need it.
"""

from contextlib import contextmanager

import psycopg2
import psycopg2.sql
import psycopg2.extensions
import psycopg2.extras
from psycogreen.gevent import patch_psycopg


COMPOSITE_TYPES = [
	"video_range",
	"video_transition",
	"end_time",
]
COLUMN_CASTS = {
	"video_ranges": "video_range[]",
	"video_transitions": "video_transition[]",
}

def get_column_placeholder(column):
	"""Get a placeholder (like "%(COLUMN)s") to use in constructed SQL queries
	for a given column in the events table. This function is needed because
	some columns have types that require explicit casts to be included."""
	placeholder = psycopg2.sql.Placeholder(column)
	if column in COLUMN_CASTS:
		placeholder = psycopg2.sql.SQL("{}::{}").format(
			placeholder, psycopg2.sql.SQL(COLUMN_CASTS[column])
		)
	return placeholder


class DBManager(object):
	"""Patches psycopg2 before any connections are created. Stores connect info 
	for easy creation of new connections, and sets some defaults before
	returning them.

	It has the ability to serve as a primitive connection pool, as getting a
	new conn will return existing conns it knows about first, but you
	should use a real conn pool for any non-trivial use.

	Returned conns are set to seralizable isolation level, autocommit, and use
	NamedTupleCursor cursors."""
	def __init__(self, connect_timeout=30, **connect_kwargs):
		patch_psycopg()
		self.conns = []
		self.connect_timeout = connect_timeout
		self.connect_kwargs = connect_kwargs

	def put_conn(self, conn):
		self.conns.append(conn)

	def get_conn(self):
		if self.conns:
			return self.conns.pop(0)
		conn = psycopg2.connect(cursor_factory=psycopg2.extras.NamedTupleCursor,
			connect_timeout=self.connect_timeout, **self.connect_kwargs)
		# We use serializable because it means less issues to think about,
		# we don't care about the performance concerns and everything we do is easily retryable.
		# This shouldn't matter in practice anyway since everything we're doing is either read-only
		# searches or targetted single-row updates.
		conn.isolation_level = psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
		conn.autocommit = True
		for composite in COMPOSITE_TYPES:
			psycopg2.extras.register_composite(composite, conn)
		return conn


@contextmanager
def transaction(conn):
	"""Helper context manager that runs the code block as a single database transaction
	instead of in autocommit mode. The only difference between this and "with conn" is
	that we explicitly disable then re-enable autocommit."""
	old_autocommit = conn.autocommit
	conn.autocommit = False
	try:
		with conn:
			yield
	finally:
		conn.autocommit = old_autocommit


def query(conn, query, *args, **kwargs):
	"""Helper that takes a conn, creates a cursor and executes query against it,
	then returns the cursor.
	Variables may be given as positional or keyword args (but not both), corresponding
	to %s vs %(key)s placeholder forms."""
	if args and kwargs:
		raise TypeError("Cannot give both args and kwargs")
	cur = conn.cursor()
	cur.execute(query, args or kwargs or None)
	return cur
