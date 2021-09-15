DROP TABLE buscribe_transcriptions;

CREATE TABLE buscribe_transcriptions
(
    id                 BIGSERIAL PRIMARY KEY,
    start_time         timestamp without time zone NOT NULL,
    end_time           timestamp without time zone NOT NULL,
    transcription_line text                     NOT NULL,
    line_speaker       float[128],
    transcription_json jsonb                    NOT NULL
);