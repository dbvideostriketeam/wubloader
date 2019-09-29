Information on how accounts and permissions are handled within Wubloader.

### Google Authentication

Google OAuth is used to authenticate users and return a user token. The Token is then passed alongside calls that need authentication 
and is validated server-side against a Google API. The API returns the authenticated user's email address (along with other basic 
profile information).

The email address is then used to look up the user in the database to check their permissions.

### Wubloader Authorization

The current plan is to only authenticate/authorize users on datebase updates coming from Thrimbletrimmer; and since most use cases will 
only have a single update event every few minutes, we can authenticate only as need - rather than authenticating on page load and storing session IDs.

Currently the only exposed actions that require authentication are Editor-based ones, so we aren't assigning roles or having granular permissions.

Actions available via Thrimshim are:
* Unauthenticated Actions
  * `get_row`: Return a single row from the database by ID. Unauthenticated.
  * `get_all_rows`: Return the entire events table (or specific subsets of it), for building dashboards. Unauthenticated
* Authenticated Actions
  * `update_row`: Updates row in the Events table.
  * `manual_link`: Override the `video_link` field in the Events Table, in case of a manual upload.
  * `reset_row`: Clear `state` and `video_link` columns and reset `state` to 'UNEDITED' in Events table.

### Admin Access
Node admins will connect directly to the database via third party tools (such as pgAdmin) for tasks such as adding members or manually overwriting the Events table.

### Database Schema

#### Members Table

columns     | type                | description
------------| --------------------| -----------
`email`     | `TEXT NOT NULL`     | The email account used for the member's Google sign in. (Primary Key)
`name`      | `TEXT NOT NULL`     | The public username of the user (for administration purposes)
