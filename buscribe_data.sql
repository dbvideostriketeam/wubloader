BEGIN TRANSACTION;

DROP TABLE IF EXISTS buscribe_verified_lines;
DROP TABLE IF EXISTS buscribe_line_speakers;
DROP TABLE IF EXISTS buscribe_speakers;
DROP TABLE IF EXISTS buscribe_verifiers;
DROP TABLE IF EXISTS buscribe_transcriptions;

ROLLBACK;

BEGIN TRANSACTION;

TRUNCATE buscribe_verified_lines RESTART IDENTITY CASCADE;
TRUNCATE buscribe_line_speakers RESTART IDENTITY CASCADE;
TRUNCATE buscribe_speakers RESTART IDENTITY CASCADE;
TRUNCATE buscribe_verifiers RESTART IDENTITY CASCADE;
TRUNCATE buscribe_transcriptions RESTART IDENTITY CASCADE;

ROLLBACK;

CREATE TABLE buscribe_transcriptions
(
    id                 BIGSERIAL PRIMARY KEY,
    start_time         timestamp without time zone NOT NULL,
    end_time           timestamp without time zone NOT NULL,
    transcription_line text                        NOT NULL,
    line_speaker       float[128],
    transcription_json jsonb                       NOT NULL
);

CREATE INDEX buscribe_transcriptions_idx ON buscribe_transcriptions USING
    GIN (to_tsvector('english', transcription_line));

-- This might not actually be needed. Check once there is more data.
CREATE INDEX buscribe_start_time_idx ON buscribe_transcriptions (start_time);
CREATE INDEX buscribe_end_time_idx ON buscribe_transcriptions (end_time);

CREATE TABLE buscribe_speakers
(
    id   BIGSERIAL PRIMARY KEY,
    name text NOT NULL UNIQUE CHECK ( name != '' )
);

CREATE TABLE buscribe_verifiers
(
--     id    SERIAL PRIMARY KEY,
    email TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

-- For testing
INSERT INTO buscribe_verifiers(email, name)
VALUES ('placeholder@example.com', 'Place Holder'),
       ('aguy@example.com', 'Arnold Guyana');

CREATE TABLE buscribe_line_speakers
(
--     id       BIGSERIAL PRIMARY KEY,
    line     BIGINT NOT NULL REFERENCES buscribe_transcriptions,
    speaker  BIGINT NOT NULL REFERENCES buscribe_speakers,
    verifier text   NOT NULL REFERENCES buscribe_verifiers,
    PRIMARY KEY (line, speaker, verifier)
);

CREATE TABLE buscribe_verified_lines
(
--     id            BIGSERIAL PRIMARY KEY,
    line          BIGINT NOT NULL REFERENCES buscribe_transcriptions,
    verified_line TEXT   NOT NULL,
    verifier      text REFERENCES buscribe_verifiers,
    PRIMARY KEY (line, verifier)
);

-- Indexed with C weight (0.2 vs default 0.1)
CREATE INDEX buscribe_verified_lines_idx ON buscribe_verified_lines USING
    GIN (setweight(to_tsvector('english', verified_line), 'C'));

BEGIN;

DROP VIEW buscribe_all_transcriptions;

CREATE VIEW buscribe_all_transcriptions AS
SELECT buscribe_transcriptions.id,
       start_time,
       end_time,
       coalesce(buscribe_verified_lines.verifier, speakers.verifier) AS verifier,
       names,
       verified_line                                                 AS transcription_line,
       setweight(to_tsvector('english', verified_line), 'C')         AS transcription_line_ts
FROM buscribe_transcriptions
         LEFT OUTER JOIN buscribe_verified_lines ON buscribe_transcriptions.id = buscribe_verified_lines.line
         LEFT OUTER JOIN (
    SELECT line, verifier, array_agg(name) AS names
    FROM buscribe_line_speakers
             INNER JOIN buscribe_speakers ON buscribe_line_speakers.speaker = buscribe_speakers.id
    GROUP BY line, verifier
) AS speakers ON buscribe_transcriptions.id = speakers.line AND (
            speakers.verifier = buscribe_verified_lines.verifier OR
            buscribe_verified_lines.verifier IS NULL
    )
WHERE coalesce(buscribe_verified_lines.verifier, speakers.verifier) IS NOT NULL
UNION
SELECT id,
       start_time,
       end_time,
       null                                       AS verifier,
       null                                       AS names,
       transcription_line,
       to_tsvector('english', transcription_line) AS transcription_line_ts
FROM buscribe_transcriptions;

ROLLBACK;