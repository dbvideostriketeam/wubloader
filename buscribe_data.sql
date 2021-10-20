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
    name text NOT NULL UNIQUE
);

CREATE TABLE buscribe_verifiers
(
--     id    SERIAL PRIMARY KEY,
    email TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

-- For testing
INSERT INTO buscribe_verifiers(email, name)
VALUES ('placeholder@example.com', 'Place Holder');

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
