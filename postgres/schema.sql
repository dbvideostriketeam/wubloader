
CREATE TYPE event_state as ENUM (
	'UNEDITED',
	'EDITED',
	'CLAIMED',
	'FINALIZING',
	'TRANSCODING',
	'DONE',
	'MODIFIED'
);

CREATE TYPE video_range as (
	start TIMESTAMP,
	"end" TIMESTAMP
);

CREATE TYPE video_transition as (
	type TEXT,
	duration INTERVAL
);

CREATE TYPE thumbnail_mode as ENUM (
	'NONE',
	'BARE',
	'TEMPLATE',
	'CUSTOM'
);

CREATE TABLE events (
	id TEXT PRIMARY KEY,

	sheet_name TEXT NOT NULL,
	event_start TIMESTAMP,
	event_end TIMESTAMP,
	category TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	submitter_winner TEXT NOT NULL DEFAULT '',
	poster_moment BOOLEAN NOT NULL DEFAULT FALSE,
	image_links TEXT[] NOT NULL DEFAULT '{}', -- default empty array
	notes TEXT NOT NULL DEFAULT '',
	tags TEXT[] NOT NULL DEFAULT '{}', -- default empty array

	allow_holes BOOLEAN NOT NULL DEFAULT FALSE,
	uploader_whitelist TEXT[],
	upload_location TEXT CHECK (state = 'UNEDITED' OR upload_location IS NOT NULL),
	public BOOLEAN NOT NULL DEFAULT TRUE,
	video_ranges video_range[] CHECK (state IN ('UNEDITED', 'DONE') OR video_ranges IS NOT NULL),
	video_transitions video_transition[] CHECK (state IN ('UNEDITED', 'DONE') OR video_transitions IS NOT NULL),
	CHECK (
		(video_ranges IS NULL AND video_transitions IS NULL)
		OR CARDINALITY(video_ranges) = CARDINALITY(video_transitions) + 1
	),
	video_title TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_title IS NOT NULL),
	video_description TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_description IS NOT NULL),
	video_tags TEXT[] CHECK (state IN ('UNEDITED', 'DONE') OR video_tags IS NOT NULL),
	video_channel TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_channel IS NOT NULL),
	video_quality TEXT NOT NULL DEFAULT 'source',

	thumbnail_mode thumbnail_mode NOT NULL DEFAULT 'TEMPLATE',
	thumbnail_time TIMESTAMP CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode in ('NONE', 'CUSTOM')
		OR thumbnail_time IS NOT NULL
	),
	thumbnail_template TEXT CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode != 'TEMPLATE'
		OR thumbnail_template IS NOT NULL
	),
	thumbnail_image BYTEA CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode != 'CUSTOM'
		OR thumbnail_image IS NOT NULL
	),
	thumbnail_last_written BYTEA CHECK (
		state != 'DONE'
		OR thumbnail_mode = 'NONE'
		OR thumbnail_last_written IS NOT NULL
	),
	
	state event_state NOT NULL DEFAULT 'UNEDITED',
	uploader TEXT CHECK (state IN ('UNEDITED', 'EDITED', 'DONE') OR uploader IS NOT NULL),
	error TEXT,
	video_id TEXT,
	video_link TEXT CHECK ((NOT (state IN ('DONE', 'MODIFIED'))) OR video_link IS NOT NULL),
	editor TEXT,
	edit_time TIMESTAMP CHECK (state = 'UNEDITED' OR editor IS NOT NULL),
	upload_time TIMESTAMP CHECK ((NOT (state IN ('DONE', 'MODIFIED'))) OR upload_time IS NOT NULL),
	last_modified TIMESTAMP CHECK (state != 'MODIFIED' OR last_modified IS NOT NULL)
);

-- Index on state, since that's almost always what we're querying on besides id
CREATE INDEX event_state ON events (state);

CREATE TABLE nodes (
	name TEXT PRIMARY KEY,
	url TEXT NOT NULL,
	backfill_from BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE editors (
	email TEXT PRIMARY KEY,
	name TEXT NOT NULL
);

-- A slight misnomer, this is all rows of the tags sheet.
-- It includes tags that have been promoted to actual playlists, and ones that have not.
-- Playlists are communicated to playlist manager via this table.
CREATE TABLE playlists (
	id TEXT PRIMARY KEY,
	-- These are sheet inputs, and aren't used directly by anything (except reverse sync)
	name TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	-- When tags is NULL, it indicates tags have not been set and so the playlist should
	-- match nothing. Conversely, when tags is empty, it indicates the playlist should match everything.
	tags TEXT[],
	playlist_id TEXT,
	show_in_description BOOLEAN NOT NULL DEFAULT FALSE,
	-- These event ids are references into the events table, but they aren't foreign keys
	-- because we don't want invalid input to cause integrity errors.
	-- It's totally safe for these to point to non-existent events, it just does nothing.
	first_event_id TEXT,
	last_event_id TEXT
);

-- This table records time series data gleaned from the bus cam (right now, just the odometer).
-- Each record indicates a timestamp and value, as well as the channel/segment file it was sourced from.
-- Note the values are nullable and NULL indicates the value was indeterminate at that time.
-- The "error" column records a free-form human readable message about why a value could not
-- be determined.
-- The odometer column is in miles. The game shows the odometer to the 1/10th mile precision.
-- The clock is in minutes since 00:00, in 12h time.
-- The time of day is one of "day", "dusk", "night", or "dawn"
-- The segment may be NULL, which indicates a manually-inserted value.
-- The primary key serves two purposes:
--   It provides an index on channel, followed by a range index on timestamp
--   It provides a unique constraint on the same segment and timestamp
-- Note that multiple manual records may exist for the same channel and timestamp
-- as all NULL values are considered distinct, so the unique constraint does not hold.
CREATE TABLE bus_data (
	channel TEXT NOT NULL,
	timestamp TIMESTAMP NOT NULL,
	segment TEXT,
	error TEXT,
	odometer DOUBLE PRECISION,
	clock INTEGER,
	timeofday TEXT,
	PRIMARY KEY (channel, timestamp, segment)
);
