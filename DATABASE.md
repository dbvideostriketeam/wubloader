
Info on the database schema and interactions with services

### The event table

One *event* is analogous to one entry in the main VST spreadsheet.

It acts as both the canonical record of the sheet,
and as state for the event as it is processed by the cutting system.

In general, columns are either:

* Taken directly from the sheet as input (*sheet inputs*)

* Set by the editor as input (*edit inputs*)

* Set by the cutter in the process of cutting to record *state* and *outputs*.

#### The state machine

The most important column is `state`. This is an enum of several possible values
which encode the overall position this event is at along the process of editing and cutting a video.

The possible states are:

* `UNEDITED`: An event which is not ready to be processed. This is the initial state of all events,
but it can also result from an event which has been edited, but then processing was aborted due
to an error or cancelled by an operator. In these cases the `error` column will be populated
with an error message.

* `EDITED`: An event for which edit inputs have been submitted and cutting is ready to proceed.
Only `UNEDITED` rows will become `EDITED` - rows which have already been edited but not yet
uploaded should instead be cancelled so they return to `UNEDITED` before attempting to re-edit them.

* `CLAIMED`: An event which is in the process of being cut and uploaded. `CLAIMED` events will
have a populated `uploader` column which indicates the cutter which is doing the cutting.

* `FINALIZING`: An event whose upload has finished, but we are currently in the process of
finalizing the upload to make it official. If a cutter dies and leaves an event in this state,
it is indeterminate whether the upload actually occurred - in this unlikely scenario, an operator
should manually inspect things and decide on further action.

* `TRANSCODING`: An event which has been succesfully uploaded, but is not yet ready for public consumption.
The upload is no longer cancellable. If further re-edits need to be applied,
an operator should manually delete or unlist the video then set the state back to `UNEDITED`.
In youtube terms, this covers the period after upload while transcoding is happening and the video
is not yet able to be played (or only at reduced resolution).

* `DONE`: An event whose video is ready for public consumption. As with `TRANSCODING`, if changes need
to be made, an operator should manually delete or unlist the video then set the state back
to `UNEDITED`.

The following transitions are possible:

* `UNEDITED -> EDITED`: When a video is edited and edit inputs are submitted

* `EDITED -> CLAIMED`: When a video is claimed by a cutter and it begins cutting it.

* `EDITED -> UNEDITED`: When an operator cancels an edited video before any cutter claims it.

* `CLAIMED -> EDITED`: When the cutting process is interrupted, eg. because the cutter crashed,
or a recoverable error occurred, but there is nothing wrong with the event
and it can be immediately retried.

* `CLAIMED -> UNEDITED`: When an operator cancels a claimed video before cutting is complete.

* `CLAIMED -> UNEDITED`: When the cutting process failed with an unknown error,
and operator intervention is required. `error` will be populated.

* `CLAIMED -> FINALIZING`: When the cutting process is finished, immediately before the cutter
finalizes the upload.

* `FINALIZING -> EDITED`: When the finalization failed due to a recoverable reason,
we are certain the upload didn't actually go through, and the cut can be immediately retried

* `FINALIZING -> UNEDITED`: When the finalization failed with an unknown error,
we are certain the upload didn't actually go through, and operator intervention is required.

* `FINALIZING -> TRANSCODING`: When the cutter has successfully finalized the upload,
but the upload location requires further processing before the video is done.

* `FINALIZING -> DONE`: When the cutter has successfully finalized the upload,
and the upload location requires no further processing.

* `TRANSCODING -> DONE`: When any cutter detects that the upload location is finished
transcoding the video, and it is ready for public consumption.

This is summarised in the below graph:

```
                                            retry
                                   ┌───────────────────────────────────────────────┐
                                   │                                               │
                       cancel      │                                               │
            ┌──────────────────────┼───────────────────┐                           │
            ∨                      ∨                   │                           │
          ┌──────────┐  edit     ┌────────┐  claim   ┌─────────┐  pre-finalize   ┌────────────┐  post-finalize   ┌─────────────┐  when ready   ┌──────┐
          │          │ ────────> │        │ ───────> │         │ ──────────────> │            │ ───────────────> │ TRANSCODING │ ────────────> │ DONE │
          │          │           │        │          │         │                 │            │                  └─────────────┘               └──────┘
          │          │  cancel   │        │  retry   │         │                 │            │                   post-finalize                  ∧
          │ UNEDITED │ <──────── │ EDITED │ <─────── │ CLAIMED │                 │ FINALIZING │ ─────────────────────────────────────────────────┘
          │          │           │        │          │         │                 │            │
          │          │           │        │          │         │                 │            │
  ┌─────> │          │           │        │  ┌────── │         │                 │            │
  │       └──────────┘           └────────┘  │       └─────────┘                 └────────────┘
  │         ∧          error                 │                                     │
  │ error   └────────────────────────────────┘                                     │
  │                                                                                │
  │                                                                                │
  └────────────────────────────────────────────────────────────────────────────────┘
```

#### Full schema

The details below assume postgres, but nothing is signifigantly different in any SQL DB,
except the use of arrays which would need to be split out into another table, but even that is
a straightforward change.

Note that most of the sheet input string types are `NOT NULL DEFAULT ''`, as when taking sheet inputs,
there is no meaningful distinction between "unset" and "set to empty string".
However, for other sheet inputs, a NULL is used to indicate unset / an unparsable value.

Edit input values are initially NULL, but must not be NULL once the state is no longer `UNEDITED`.

columns                    | type                               | role        | description
-------------------------- | ---------------------------------- | :---------: | -----------
`id`                       | `UUID PRIMARY KEY`                 | sheet input | Generated and attached to rows in the sheet to uniquely identify them even in the face of added, deleted or moved rows.
`event_start`, `event_end` | `TIMESTAMP`                        | sheet input | Start and end time of the event. Parsed from the sheet into timestamps or NULL. Used to set the editor time span, and displayed on the public sheet. The start time also determines what "day" the event lies on, for video tagging and other purposes.
`category`                 | `TEXT NOT NULL DEFAULT ''`         | sheet input | The kind of event. By convention selected from a small list of categories, but stored as an arbitrary string because there's little to no benefit to using an enum here, it just makes our job harder when adding a new category. Used to tag videos, and for display on the public sheet.
`description`              | `TEXT NOT NULL DEFAULT ''`         | sheet input | Event description. Provides the default title and description for editors, and displayed on the public sheet.
`submitter_winner`         | `TEXT NOT NULL DEFAULT ''`         | sheet input | A column detailing challenge submitter, auction winner, or other "associated person" data. This shouldn't be relied on in any processing but should be displayed on the public sheet.
`poster_moment`            | `BOOLEAN NOT NULL DEFAULT FALSE`   | sheet input | Whether or not the event was featured on the poster. Used for building the postermap and also displayed on the public sheet.
`image_links`               | `TEXT[] NOT NULL`                 | sheet input | Any additional gif or image links associated with the event. Displayed on the public sheet.
`notes`                    | `TEXT NOT NULL DEFAULT ''`         | sheet input | Private notes on this event, used eg. to leave messages or special instructions. Displayed to the editor during editing, but otherwise unused.
`allow_holes`              | `BOOLEAN NOT NULL DEFAULT FALSE`   | sheet input | If false, any missing segments encountered while cutting will cause the cut to fail. Setting this to true should be done by an operator to indicate that holes are expected in this range. It is also the operator's responsibility to ensure that all allowed cutters have all segments that they can get, since there is no guarentee that only the cutter with the least missing segments will get the cut job.
`uploader_whitelist`       | `TEXT[]`                           | sheet input | List of uploaders which are allowed to cut this entry, or NULL to indicate no restriction. This is useful if you are allowing holes and the amount of missing data differs between nodes (this shouldn't happen - this would mean replication is also failing), or if an operator is investigating a problem with a specific node.
`upload_location`          | `TEXT NOT NULL DEFAULT ''`         | sheet input | The upload location to upload the cut video to. This is used by the cutter, and must match one of the cutter's configured upload locations. If it does not, the cutter will not claim the event.
`video_start`, `video_end` | `TIMESTAMP`                        | edit input  | Start and end time of the video to cut. If already set, used as the default trim times when editing.
`video_title`              | `TEXT`                             | edit input  | The title of the video. If already set, used as the default title when editing instead of `description`.
`video_description`        | `TEXT`                             | edit input  | The description field of the video. If already set, used as the default description when editing instead of `description`.
`video_channel`            | `TEXT`                             | edit input  | The twitch channel to cut the video from. If already set, used as the default channel selection when editing, instead of a pre-configured editor default. While this will almost always be the default value, it's a useful thing to be able to change should the need arise.
`video_quality`            | `TEXT NOT NULL DEFAULT 'source'    | edit input  | The stream quality to cut the video from. Used as the default quality selection when editing. While this will almost always be the default value, it's a useful thing to be able to change should the need arise.
`state`                    | `ENUM NOT NULL DEFAULT 'UNEDITED'` | state       | See "The state machine" above.
`uploader`                 | `TEXT`                             | state       | The name of the cutter node performing the cut and upload. Set when transitioning from `EDITED` to `CLAIMED` and cleared on a retryable error. Left uncleared on non-retryable errors to provide information to the operator. Cleared on a re-edit if set.
`error`                    | `TEXT`                             | state       | A human-readable error message, set if a non-retryable error occurs. Its presence indicates operator intervention is required. Cleared on a re-edit if set.
`video_id`                 | `TEXT`                             | state       | An id that can be used to refer to the video to check if transcoding is complete. Often the video_link can be generated from this, but not nessecarily.
`video_link`               | `TEXT`                             | output      | A link to the uploaded video. Only set when state is `TRANSCODING` or `DONE`.
