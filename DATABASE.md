
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
to `UNEDITED`, or modify the video if possible (see `MODIFIED`).

* `MODIFIED`: An event that was previously successfully uploaded, which has had some of its edit inputs
modified. Cutters will see this state and attempt to edit the video to match the new edit inputs,
though the possible edits depend on the upload backend. This only includes edits to metadata fields
like title, and should not require re-cutting the video. Once updated, the cutter returns the video to `DONE`.

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

* `DONE -> MODIFIED`: When an operator modifies an uploaded video

* `MODIFIED -> DONE`: When a cutter successfully updates a modified video, or when
an operator cancels the modification (leaving the video in an indeterminate state,
which the operator is responsible for verifying).

This is summarised in the below graph:

```
                                            retry                                                                                          ┌──────────┐
                                   ┌───────────────────────────────────────────────┐                                                       │ MODIFIED │
                                   │                                               │                                                       └──────────┘
                       cancel      │                                               │                                                            ∧   │
            ┌──────────────────────┼───────────────────┐                           │                                                     modify │   │ updated
            ∨                      ∨                   │                           │                                                            │   ∨
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

#### Thumbnails

The state around thumbnails is a little complicated.

The `thumbnail_mode` is set by the editor and has the following options:
* `NONE`: Video should not have a thumbnail uploaded.
  This will not delete an existing thumbnail if present.
* `BARE`: Video thumbnail is a still frame taken from the stream at `thumbnail_time`.
  `thumbnail_time` must not be NULL. `thumbnail_template` must be NULL.
* `TEMPLATE`: Video thumbnail takes a still frame from the stream at `thumbnail_time` and
  combines it with a template image with name `thumbnail_template`. Both these columns must
  not be NULL.
* `CUSTOM`: Video thumbnail is a custom image stored in `thumbnail_image`, which must not be NULL.

In the cases of `BARE` and `TEMPLATE`, `thumbnail_image` is used to store the generated image.
This generation happens when the video is uploaded.
However, if the `thumbnail_image` column is later set to NULL and state set to `MODIFIED`,
the image will be re-generated before the video is modified.

Unused columns for the current mode are allowed to be non-NULL, this allows for changing
the mode then changing it back, without losing the old saved settings.

All the above columns are modifiable, within the constraints outlined above.
The mode column's default is currently `TEMPLATE`, but this is just a UX choice.

Finally, the `thumbnail_last_written` column holds a SHA256 hash of the image data most recently
uploaded. This allows us to detect if it has changed when modifying a video.
We could query the current thumbnail from youtube's API, but this may be re-encoded or scaled
and not have exactly the same content.

#### Full schema

The details below assume postgres, but nothing is signifigantly different in any SQL DB,
except the use of arrays which would need to be split out into another table, but even that is
a straightforward change.

Note that most of the sheet input string types are `NOT NULL DEFAULT ''`, as when taking sheet inputs,
there is no meaningful distinction between "unset" and "set to empty string".
However, for other sheet inputs, a NULL is used to indicate unset / an unparsable value.

Edit input values are initially NULL, but must not be NULL once the state is no longer `UNEDITED`.

columns                    | type                                 | role        | description
-------------------------- | ----------------------------------   | :---------: | -----------
`id`                       | `UUID PRIMARY KEY`                   | sheet input | Generated and attached to rows in the sheet to uniquely identify them even in the face of added, deleted or moved rows.
`sheet_name`               | `TEXT NOT NULL`                      | sheet input | The name of the worksheet that the row is on. This is used to tag videos, and can be used to narrow down the range to look for an id in for more efficient lookup (though we never do that right now).
`event_start`, `event_end` | `TIMESTAMP`                          | sheet input | Start and end time of the event. Parsed from the sheet into timestamps or NULL. Used to set the editor time span, and displayed on the public sheet. The start time also determines what "day" the event lies on, for video tagging and other purposes.
`category`                 | `TEXT NOT NULL DEFAULT ''`           | sheet input | The kind of event. By convention selected from a small list of categories, but stored as an arbitrary string because there's little to no benefit to using an enum here, it just makes our job harder when adding a new category. Used to tag videos, and for display on the public sheet.
`description`              | `TEXT NOT NULL DEFAULT ''`           | sheet input | Event description. Provides the default title and description for editors, and displayed on the public sheet.
`submitter_winner`         | `TEXT NOT NULL DEFAULT ''`           | sheet input | A column detailing challenge submitter, auction winner, or other "associated person" data. This shouldn't be relied on in any processing but should be displayed on the public sheet.
`poster_moment`            | `BOOLEAN NOT NULL DEFAULT FALSE`     | sheet input | Whether or not the event was featured on the poster. Used for building the postermap and also displayed on the public sheet.
`image_links`              | `TEXT[] NOT NULL`                    | sheet input | Any additional gif or image links associated with the event. Displayed on the public sheet.
`notes`                    | `TEXT NOT NULL DEFAULT ''`           | sheet input | Private notes on this event, used eg. to leave messages or special instructions. Displayed to the editor during editing, but otherwise unused.
`tags`                     | `TEXT[] NOT NULL`                    | sheet input | Custom tags to annotate this event's video with. Provides the default tags that the editor can then adjust.
`allow_holes`              | `BOOLEAN NOT NULL DEFAULT FALSE`     | edit input  | If false, any missing segments encountered while cutting will cause the cut to fail. Setting this to true should be done by an operator to indicate that holes are expected in this range. It is also the operator's responsibility to ensure that all allowed cutters have all segments that they can get, since there is no guarentee that only the cutter with the least missing segments will get the cut job.
`uploader_whitelist`       | `TEXT[]`                             | edit input  | List of uploaders which are allowed to cut this entry, or NULL to indicate no restriction. This is useful if you are allowing holes and the amount of missing data differs between nodes (this shouldn't happen - this would mean replication is also failing), or if an operator is investigating a problem with a specific node.
`upload_location`          | `TEXT`                               | edit input  | The upload location to upload the cut video to. This is used by the cutter, and must match one of the cutter's configured upload locations. If it does not, the cutter will not claim the event.
`public`                   | `BOOLEAN NOT NULL DEFAULT TRUE`      | edit input  | Whether the uploaded video should be public or not, if the upload location supports that distinction. For example, on youtube, non-public videos are "unlisted". It also controls whether the video will be added to playlists, only public videos are added to playlists.
`video_ranges`             | `{start TIMESTAMP, end TIMESTAMP}[]` | edit input  | A non-zero number of start and end times, describing the ranges of video to cut. They will be cut back-to-back in the given order, with the transitions between as per `video_transitions`. If already set, used as the default range settings when editing.
`video_transitions`        | `{type TEXT, duration INTERVAL}[]`   | edit input  | Defines how to transition between each range defined in `video_ranges`, and must be exactly the length of `video_ranges` minus 1. Each index in `video_transitions` defines the transition between the range with the same index in `video_ranges` and the next one. Transitions either specify a transition type as understood by `ffmpeg`'s `xfade` filter and a duration (amount of overlap), or can be NULL to indicate a hard cut.
`video_crop`               | `{x, y, w, h INTEGER}`               | edit input  | If given, defines how the video should be cropped when editing.
`video_title`              | `TEXT`                               | edit input  | The title of the video. If already set, used as the default title when editing instead of `description`.
`video_description`        | `TEXT`                               | edit input  | The description field of the video. If already set, used as the default description when editing instead of `description`.
`video_tags`               | `TEXT[]`                             | edit input  | Custom tags to annotate the video with. If already set, used as the default when editing instead of `tags`.
`video_channel`            | `TEXT`                               | edit input  | The twitch channel to cut the video from. If already set, used as the default channel selection when editing, instead of a pre-configured editor default. While this will almost always be the default value, it's a useful thing to be able to change should the need arise.
`video_quality`            | `TEXT NOT NULL DEFAULT 'source'      | edit input  | The stream quality to cut the video from. Used as the default quality selection when editing. While this will almost always be the default value, it's a useful thing to be able to change should the need arise.
`thumbnail_mode`           | `ENUM NOT NULL DEFAULT 'TEMPLATE'    | edit input  | The thumbnail mode. See "Thumbnails" above.
`thumbnail_time`           | `TIMESTAMP`                          | edit input  | The video time to grab a frame from for the thumbnail in BARE and TEMPLATE modes.
`thumbnail_template`       | `TEXT`                               | edit input  | The template name to use for the thumbnail in TEMPLATE mode.
`thumbnail_image`          | `BYTEA`                              | edit input  | In CUSTOM mode, the thumbnail image. In BARE and TEMPLATE modes, the generated thumbnail image, or NULL to indicate it should be generated when next needed.
`state`                    | `ENUM NOT NULL DEFAULT 'UNEDITED'`   | state       | See "The state machine" above.
`uploader`                 | `TEXT`                               | state       | The name of the cutter node performing the cut and upload. Set when transitioning from `EDITED` to `CLAIMED` and cleared on a retryable error. Left uncleared on non-retryable errors to provide information to the operator. Cleared on a re-edit if set.
`error`                    | `TEXT`                               | state       | A human-readable error message, set if a non-retryable error occurs. Its presence indicates operator intervention is required. Cleared on a re-edit if set.
`video_id`                 | `TEXT`                               | state       | An id that can be used to refer to the video to check if transcoding is complete. Often the video_link can be generated from this, but not nessecarily.
`video_link`               | `TEXT`                               | output      | A link to the uploaded video. Only set when state is `TRANSCODING` or `DONE`.
`editor`                   | `TEXT`                               | state       | Email address of the last editor; corresponds to an entry in the `editors` table. Only set when state is not `UNEDITED`.
`edit_time`                | `TIMESTAMP`                          | state       | Time of the last edit. Only set when state is not `UNEDITED`.
`upload_time`              | `TIMESTAMP`                          | state       | Time when video state is set to `DONE`. Only set when state is `DONE`.
`last_modified`            | `TIMESTAMP`                          | state       | Time when video state was last set to `MODIFIED`, or NULL if it has never been. Only used for diagnostics.
`thumbnail_last_written`   | `BYTEA`                              | state       | The SHA256 hash, in binary form, of the most recently uploaded thumbnail image.
