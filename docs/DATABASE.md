
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

### Audit Logging

We are using [a third party audit trigger](https://wiki.postgresql.org/wiki/Audit_trigger_91plus)
to log all changes to the `events` table. The main intent here is to investigate issues and revert mistakes,
not to be a security system.

Data is logged to the `audit.logged_actions` table.

To get all updates for a particular event id, use a query like:
```sql
SELECT action_tstamp_clk, row_data, changed_fields
FROM audit.logged_actions
WHERE row_data->'id' = 'YOUR EVENT ID'
```

### Replication and failover

#### Failover procedure

In these notes, we refer to the original leader node as `old` and the new leader (former follower) as `new`.
We refer to a generic node (either `old`, `new`, or a third node) as `node`.
Commands will show which node they should run on via a prompt prefix, ie.

```bash
new$ echo "This should be run on the new leader"
```

1. On all nodes, switch the database configuration from the old hostname to the new hostname

```diff
   db_args:: {
     user: "vst",
     password: "dbfh2019",
-    host: "old.videostrike.team",
+    host: "new.videostrike.team",
     port: 5432,
     dbname: "wubloader",
   },
```

**Note**: On the `new` node, the new host must be the string `postgres`, not the external hostname.

```bash
node$ ./generate-docker-compose
node$ docker-compose up -d
```

**Warning**: From this point on, any write operations will fail. This is expected and will not cause lasting damage.
It may result in some uploads failing with an error that must be manually cleared later.

2. If possible, gracefully shut down the old database:

```bash
old$ docker-compose stop postgres
```

This is for safety to double-check that nothing is still talking to the old leader.

3. Promote the new leader

```bash
$ docker-compose exec postgres psql -U postgres -c 'select pg_promote()'
```

Write operations should now work again. You can now retry any uploads that failed due to the database not being writable.

4. Fix up the new leader config to prevent accidents

```diff
   db_buscribe_user:: "buscribe",
   db_buscribe_password:: "transcription",
-  db_standby:: true,
+  db_standby:: false,
 
```

4. Once possible, re-setup old leader as a replica

```diff
   db_buscribe_user:: "buscribe",
   db_buscribe_password:: "transcription",
-  db_standby:: false,
+  db_standby:: true,
 
```

Note the `$.database_path` value and use it below:

```bash
old$ sudo rm -rf DATABASE_PATH
old$ ./generate-docker-compose
old$ docker-compose up -d
```
