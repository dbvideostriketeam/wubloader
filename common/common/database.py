
"""
Code shared between components that touch the database.
Note that this code requires psycopg2 and psycogreen, but the common module
as a whole does not to avoid needing to install them for components that don't need it.
"""

from contextlib import contextmanager

import psycopg2
import psycopg2.extensions
import psycopg2.extras
from psycogreen.gevent import patch_psycopg


# Schema is applied on startup and should be idemponent,
# and include any migrations potentially needed.
SCHEMA = """

-- Create type if it doesn't already exist
DO $$ BEGIN
	CREATE TYPE event_state as ENUM (
		'UNEDITED',
		'EDITED',
		'CLAIMED',
		'FINALIZING',
		'TRANSCODING',
		'DONE'
	);
EXCEPTION WHEN duplicate_object THEN
	NULL;
END $$;

CREATE TABLE IF NOT EXISTS events (
	id UUID PRIMARY KEY,
	event_start TIMESTAMP,
	event_end TIMESTAMP,
	category TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	submitter_winner TEXT NOT NULL DEFAULT '',
	poster_moment BOOLEAN NOT NULL DEFAULT FALSE,
	image_links TEXT[] NOT NULL DEFAULT '{}', -- default empty array
	notes TEXT NOT NULL DEFAULT '',
	allow_holes BOOLEAN NOT NULL DEFAULT FALSE,
	uploader_whitelist TEXT[],
	upload_location TEXT CHECK (state = 'UNEDITED' OR upload_location IS NOT NULL),
	video_start TIMESTAMP CHECK (state IN ('UNEDITED', 'DONE') OR video_start IS NOT NULL),
	video_end TIMESTAMP CHECK (state IN ('UNEDITED', 'DONE') OR video_end IS NOT NULL),
	video_title TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_title IS NOT NULL),
	video_description TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_description IS NOT NULL),
	video_channel TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_channel IS NOT NULL),
	video_quality TEXT NOT NULL DEFAULT 'source',
	state event_state NOT NULL DEFAULT 'UNEDITED',
	uploader TEXT CHECK (state IN ('UNEDITED', 'EDITED', 'DONE') OR uploader IS NOT NULL),
	error TEXT,
	video_id TEXT,
	video_link TEXT CHECK (state != 'DONE' OR video_link IS NOT NULL)
);

-- Index on state, since that's almost always what we're querying on besides id
CREATE INDEX IF NOT EXISTS event_state ON events (state);

"""


class DBManager(object):
	"""Patches psycopg2 before any connections are created, and applies the schema.
	Stores connect info for easy creation of new connections, and sets some defaults before
	returning them.

	It has the ability to serve as a primitive connection pool, as getting a new conn will
	return existing conns it knows about first, but this mainly just exists to re-use
	the initial conn used to apply the schema, and you should use a real conn pool for
	any non-trivial use.

	Returned conns are set to seralizable isolation level, autocommit, and use NamedTupleCursor cursors.
	"""
	def __init__(self, **connect_kwargs):
		patch_psycopg()
		self.conns = []
		self.connect_kwargs = connect_kwargs
		conn = self.get_conn()
		with transaction(conn):
			query(conn, SCHEMA)
		self.put_conn(conn)

	def put_conn(self, conn):
		self.conns.append(conn)

	def get_conn(self):
		if self.conns:
			return self.conns.pop(0)
		conn = psycopg2.connect(cursor_factory=psycopg2.extras.NamedTupleCursor, **self.connect_kwargs)
		# We use serializable because it means less issues to think about,
		# we don't care about the performance concerns and everything we do is easily retryable.
		# This shouldn't matter in practice anyway since everything we're doing is either read-only
		# searches or targetted single-row updates.
		conn.isolation_level = psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
		conn.autocommit = True
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
