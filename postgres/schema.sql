
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
	duration DOUBLE PRECISION
);

CREATE TYPE thumbnail_mode as ENUM (
	-- Do not set a thumbnail
	'NONE',
	-- Set the thumbnail to a video frame
	'BARE',
	-- Set the thumbnail to a video frame rendered with a thumbnail template
	'TEMPLATE',
	-- Set the thumbnail to an uploaded image
	'CUSTOM'
);

-- Represents an area in an image as (left, top, bottom, right)
-- or equivalently as (x1, y1, x2, y2) where x is the top-left corner and y is the bottom-right.
CREATE DOMAIN box_coords AS INTEGER[] CHECK (cardinality(VALUE) = 4 OR VALUE IS NULL);

-- The end time for an event can be unset, "--" or a timestamp.
-- If dashed is true, value should be the same as start time (which may be NULL if start time is unset).
-- Otherwise value is the value (which may be NULL if end time is unset).
-- dashed should be non-NULL.
CREATE TYPE end_time AS (
	dashed BOOLEAN,
	value TIMESTAMP
);

-- Each row on the sheet is an event.
CREATE TABLE events (
	-- id is generated and attached to rows in the sheet to uniquely identify them
	-- even in the face of added, deleted or moved rows.
	id TEXT PRIMARY KEY,

	-- The following are "sheet inputs", taken from the sheet row.
	-- Many of them are "NOT NULL DEFAULT ''", as in a spreadsheet there is no distinction
	-- between "unset" and an empty string.

	-- The name of the worksheet that the row is on. This is used to tag videos,
	-- and for reverse sync.
	sheet_name TEXT NOT NULL,
	-- The start and end times written on the sheet, or NULL if no valid timestamp.
	-- End time additionally stores whether it was originally written as "--" (same as timestamp) or explicitly.
	-- Used to set editor time span, and displayed on the public sheet.
	-- The start time also determines what "day" the event lies on, for video tagging and other purposes.
	event_start TIMESTAMP,
	event_end end_time DEFAULT ROW(false, NULL) CHECK (
		-- dashed bool should be non-null
		(event_end).dashed IS NOT NULL
		-- if dashed is true, value should equal event_start
		AND ((event_end).dashed != TRUE OR (event_end).value IS NOT DISTINCT FROM event_start)
	),
	-- The kind of event. By convention selected from a small list of categories,
	-- but stored as an arbitrary string because there's little to no benefit to using an enum here,
	-- it just makes our job harder when adding a new category.
	-- Used to tag videos, and for display on the public sheet.
	category TEXT NOT NULL DEFAULT '',
	-- Event description. Provides the default description for editors, and displayed on the public sheet.
	description TEXT NOT NULL DEFAULT '',
	-- A column detailing challenge submitter, auction winner, or other "associated" data like quiz answers.
	-- This shouldn't be relied on in any processing but should be displayed on the public sheet.
	submitter_winner TEXT NOT NULL DEFAULT '',
	-- Whether or not the event was featured on the poster.
	-- Used for building the postermap and also displayed on the public sheet.
	poster_moment BOOLEAN NOT NULL DEFAULT FALSE,
	-- Any additional media or other URLs associated with the event.
	-- May not be an image. Displayed on the public sheet.
	image_links TEXT[] NOT NULL DEFAULT '{}', -- default empty array
	-- Private notes on this event, used eg. to leave messages or special instructions.
	-- Displayed to the editor during editing.
	notes TEXT NOT NULL DEFAULT '',
	-- Custom tags to annotate this event's video with. Provides the default tags that the editor can then adjust.
	-- Also used to determine which playlists a video should be in, and by extension the default video thumbnail.
	-- This list includes some extra tags in addition to what is on the sheet, like sheet name and category.
	tags TEXT[] NOT NULL DEFAULT '{}', -- default empty array

	-- The following are "edit inputs", set by the editor when submitting an edit or draft.
	-- They are initially NULL, but most must be non-NULL once the video is in an edited state.
	-- When loading the editor, if these were previously set, they are restored.
	-- Otherwise defaults are loaded.

	-- If false, any missing segments encountered while cutting will cause the cut to fail.
	-- Setting this to true should be done to indicate that holes are expected in this range.
	-- It is the user's responsibility to ensure that all allowed cutters have all segments that they can get,
	-- since there is no guarentee that the cutter with the least missing segments will get the cut job.
	allow_holes BOOLEAN NOT NULL DEFAULT FALSE,
	-- List of uploaders which are allowed to cut this entry, or NULL to indicate no restriction.
	-- This is useful if you are allowing holes and the amount of missing data differs between nodes
	-- (this would only happen if replication is also failing), or testing with a specific node.
	uploader_whitelist TEXT[],
	-- The upload location to upload the cut video to. This is used by the cutter,
	-- and must match one of the cutter's configured upload locations. If it does not, the cutter will not claim the event.
	upload_location TEXT CHECK (state = 'UNEDITED' OR upload_location IS NOT NULL),
	-- Whether the uploaded video should be public or not, if the upload location supports that distinction.
	-- For youtube, non-public videos are "unlisted".
	-- Non-public videos will not be added to playlists.
	public BOOLEAN NOT NULL DEFAULT TRUE,

	-- A non-zero number of start and end times, describing the ranges of video to cut.
	-- They will be cut back-to-back in the given order, with the transitions between as per `video_transitions`.
	video_ranges video_range[] CHECK (state IN ('UNEDITED', 'DONE') OR video_ranges IS NOT NULL),
	-- Defines how to transition between each range defined in `video_ranges`,
	-- and must be exactly the length of `video_ranges` - 1.
	-- Each index in `video_transitions` defines the transition between the range with the same index in `video_ranges` and the next one.
	-- Transitions either specify a transition type as understood by ffmpeg's "xfade" filter and a duration,
	-- or can be NULL to indicate a hard cut.
	video_transitions video_transition[] CHECK (state IN ('UNEDITED', 'DONE') OR video_transitions IS NOT NULL),
	CHECK (
		(video_ranges IS NULL AND video_transitions IS NULL)
		OR CARDINALITY(video_ranges) = CARDINALITY(video_transitions) + 1
	),
	-- The title of the video
	video_title TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_title IS NOT NULL),
	-- The video description. Defaults to the sheet description.
	video_description TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_description IS NOT NULL),
	-- Tags to set on the video. Defaults to the sheet tags, plus a preset list.
	video_tags TEXT[] CHECK (state IN ('UNEDITED', 'DONE') OR video_tags IS NOT NULL),
	-- The twitch channel to cut the video from.
	video_channel TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_channel IS NOT NULL),
	-- The stream quality to cut the video from. You almost always want "source", but might need
	-- something else for testing.
	video_quality TEXT NOT NULL DEFAULT 'source',

	-- The thumbnail mode, which determines which other thumbnail columns will be used.
	-- Unused columns are NOT enforced to be NULL, so that if you switch modes then switch
	-- back the old settings aren't lost.
	thumbnail_mode thumbnail_mode NOT NULL DEFAULT 'TEMPLATE',
	-- For BARE and TEMPLATE thumbnails, the video timestamp to take the source frame from.
	thumbnail_time TIMESTAMP CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode in ('NONE', 'CUSTOM')
		OR thumbnail_time IS NOT NULL
	),
	-- For TEMPLATE thumbnails, the name of the template to use.
	thumbnail_template TEXT CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode != 'TEMPLATE'
		OR thumbnail_template IS NOT NULL
	),
	-- For TEMPLATE thumbnails, the bounding box in the source frame to grab from.
	thumbnail_crop box_coords CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode != 'TEMPLATE'
		OR thumbnail_crop IS NOT NULL
	),
	-- For TEMPLATE thumbnails, the bounding box in the template to paste into.
	thumbnail_location box_coords CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode != 'TEMPLATE'
		OR thumbnail_location IS NOT NULL
	),
	-- For CUSTOM thumbnails, the thumbnail image to use.
	-- For BARE and TEMPLATE thumbnails, a saved copy of the generated image, or NULL to indicate it needs to be regenerated.
	-- This has two important effects:
	--   We don't need to re-render (and worry about reproducibility) every time the video is modified to check if it changed
	--   Changes in a template don't immediately apply retroactively to existing thumbnails
	thumbnail_image BYTEA CHECK (
		state = 'UNEDITED'
		OR thumbnail_mode != 'CUSTOM'
		OR thumbnail_image IS NOT NULL
	),
	-- SHA256 hash of the most recently uploaded thumbnail image.
	-- Used to know if we need to update the thumbnail.
	thumbnail_last_written BYTEA CHECK (
		state != 'DONE'
		OR thumbnail_mode = 'NONE'
		OR thumbnail_last_written IS NOT NULL
	),

	-- The remaining fields are used for housekeeping, tracking state, and providing outputs to the sheet.

	-- The state field governs the steps a row takes to be uploaded. See docs/DATABASE.md for details.
	state event_state NOT NULL DEFAULT 'UNEDITED',
	-- The name of the cutter node performing the cut and upload.
	-- Set when transitioning from `EDITED` to `CLAIMED` and cleared on a retryable error.
	-- Left uncleared on non-retryable errors to provide information. Cleared on a re-edit if set.
	uploader TEXT CHECK (state IN ('UNEDITED', 'EDITED', 'DONE', 'MODIFIED') OR uploader IS NOT NULL),
	-- A human-readable error message, set if a non-retryable error occurs.
	-- Its presence indicates operator intervention is required. Cleared on a re-edit if set.
	error TEXT,
	-- An id that can be used to refer to the video to check if transcoding is complete.
	-- For youtube, the video_link can be generated from this, but we don't rely on that.
	video_id TEXT,
	-- A link to the uploaded video. Set when state is `TRANSCODING` or `DONE`.
	video_link TEXT CHECK ((NOT (state IN ('DONE', 'MODIFIED'))) OR video_link IS NOT NULL),
	-- Email address of the last editor; corresponds to an entry in the roles table.
	editor TEXT,
	-- Time the last edit or draft or was submitted, only used for diagnostics.
	edit_time TIMESTAMP CHECK (state = 'UNEDITED' OR editor IS NOT NULL),
	-- Time when video state is set to DONE, only used for diagnostics.
	upload_time TIMESTAMP CHECK ((NOT (state IN ('DONE', 'MODIFIED'))) OR upload_time IS NOT NULL),
	-- Time when video state was last set to MODIFIED, or NULL if it has never been.
	-- Only used for diagnostics.
	last_modified TIMESTAMP CHECK (state != 'MODIFIED' OR last_modified IS NOT NULL)
);

-- Index on state, since that's almost always what we're querying on besides id
CREATE INDEX event_state ON events (state);

-- Enable audit logging for this table.
-- This is mainly a just-in-case thing so we can work out when something was changed,
-- and change it back if needed. More about accidents than security.
SELECT audit.audit_table('events');

-- What nodes are available to replicate from
CREATE TABLE nodes (
	-- Unique name, so nodes know not to replicate from themselves
	name TEXT PRIMARY KEY,
	-- Base URL for restreamer
	url TEXT NOT NULL,
	-- Only backfill from this node when this is true
	backfill_from BOOLEAN NOT NULL DEFAULT TRUE
);

-- Table containing user emails and which permissions they should have.
CREATE TABLE roles (
	-- email should always be lowercase since that's how the auth function compares it
	email TEXT PRIMARY KEY CHECK (email = lower(email)),
	-- Name is just used for human readability
	name TEXT NOT NULL,
	-- Editors are allowed to submit edits to videos
	editor BOOLEAN NOT NULL DEFAULT FALSE,
	-- Artists are allowed to manage thumbnails
	artist BOOLEAN NOT NULL DEFAULT FALSE
);

-- A slight misnomer, this is all rows of the tags sheet.
-- It includes tags that have been promoted to actual playlists, and ones that have not.
-- Playlists are communicated to playlist manager via this table.
CREATE TABLE playlists (
	id TEXT PRIMARY KEY,
	-- These are sheet inputs, and aren't used directly by anything (except reverse sync)
	name TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	-- A list of tags, all of which a video must have to be included in this playlist.
	-- When tags is NULL, it indicates tags have not been set and so the playlist should
	-- match nothing. Conversely, when tags is empty, it indicates the playlist should match everything.
	tags TEXT[],
	-- Youtube playlist ID, if there is one.
	playlist_id TEXT UNIQUE,
	-- If true, videos in this playlist will point to the playlist in their description.
	show_in_description BOOLEAN NOT NULL DEFAULT FALSE,
	-- These event ids are references into the events table, but they aren't foreign keys
	-- because we don't want invalid input to cause integrity errors.
	-- It's totally safe for these to point to non-existent events, it just does nothing.
	-- If they are valid, it changes the sort order of the playlist to put these videos first or last.
	first_event_id TEXT,
	last_event_id TEXT,
	-- name of the thumbnail template to be applied by default to videos in this playlist.
	default_template TEXT
);

-- This table records time series data gleaned from the bus cam (right now, just the odometer and clock).
-- Each record indicates a timestamp and value, as well as the channel/segment file it was sourced from.
-- Note the values are nullable and NULL indicates the value was indeterminate at that time.
-- The "error" column records a free-form human readable message about why a value could not
-- be determined.
-- The odometer column is in miles. The game shows the odometer to the 1/80th mile precision.
-- The clock is in minutes since 00:00, in 12h time. Note this means the valid range is 60 (`01:00`) to 779 (`12:59`).
-- The time of day is one of "day", "dusk", "night", "dawn" or "score"
-- The segment may be NULL, which indicates a manually-inserted value.
-- The primary key serves two purposes:
--   It provides an index on channel, followed by a range index on timestamp
--   It provides a unique constraint on the same segment and timestamp
-- Note that multiple manual records may exist for the same channel and timestamp
-- as all NULL values are considered distinct, so the unique constraint does not hold.
-- Two versions of the odometer and clock are stored. raw_odometer and raw_clock are the OCR results; odometer and clock are the results of post processing to identify and correct poorly recognised characters. 
CREATE TABLE bus_data (
	channel TEXT NOT NULL,
	timestamp TIMESTAMP NOT NULL,
	segment TEXT,
	error TEXT,
	raw_odometer DOUBLE PRECISION,
	raw_clock INTEGER,
	odometer DOUBLE PRECISION,
	clock INTEGER,
	timeofday TEXT,
	PRIMARY KEY (channel, timestamp, segment)
);

-- This table stores video thumbnail templates and their associated metadata
-- attribution: any attribution to be auto included in the video description. If empty, do not add an attribution
-- crop: left, upper, right, and lower pixel coordinates to crop the selected frame
-- location: left, top, right, bottom pixel coordinates to position the cropped frame
CREATE TABLE templates (
	name TEXT PRIMARY KEY,
	image BYTEA NOT NULL,
	description TEXT NOT NULL DEFAULT '',
	attribution TEXT NOT NULL DEFAULT '',
	crop box_coords NOT NULL,
	location box_coords NOT NULL
);

SELECT audit.audit_table('templates');

-- Used to farm out encoding jobs to encoder workers.
-- URL fields must match form: "scp://USER:PASS@HOST:PORT/PATH"
-- Hash fields are hex strings containing sha256 hashes.
-- encode_args should be passed verbatim to ffmpeg with the following substitutions:
--   {SRC_FILE}: The path to the source file
--   {DEST_FILE}: The path to the output file
-- Example encode args: '-i' '{SRC_FILE}' '-c' 'copy' '{DEST_FILE}'
-- The job is considered complete once the dest hash is written.
-- Jobs may be claimed by writing a worker name to claimed_by.
-- Timestamp fields are indicative only.
CREATE TABLE encodes (
	src_url TEXT NOT NULL,
	src_hash TEXT NOT NULL,
	encode_args TEXT[] NOT NULL,
	dest_url TEXT PRIMARY KEY,
	dest_hash TEXT,
	claimed_by TEXT,
	claimed_at TIMESTAMP,
	finished_at TIMESTAMP
);
