Information on how accounts and permissions are handled within Wubloader.

### Google Authentication

Google OAuth is used to authenticate users and return a user token. The Token is then passed alongside calls that need authentication 
and is validated server-side against a Google API. The API returns the authenticated user's email address (along with other basic 
profile information).

The email address is then used to look up the user in the database to check their permissions.

The current plan is to only authenticate/authorize users on datebase updates coming from Thrimbletrimmer; and since most use cases will 
only have a single update event every few minutes, we can authenticate only as need - rather than authenticating on page load and storing session IDs.

### Wubloader Authorization

Authorized tasks via Thrimshim will be:
* `update_row`: Updates row in the Events table. Compares incoming updates against the `event_column_whitelist` for the role associated with the current user, to limit which fields can be updated by a user/role.
* `manual_link`: Override the `video_link` field in the Events Table, in case of a manual upload.
* `reset_row`: Clear `state` and `video_link` columns and reset `state` to 'UNEDITED' in Events table.

The planned roles are:
* `Admin`: Like editors, but with the ability to modify additional fields the "state" column in case of errors, and will have access to a special dashboard page for doing those edits.
* `Editor`: Normal users, able to submit edits for Wubloader to cut via Thrimbletrimmer.
* `Viewer`: For potential users such as Giffers, who will have their own viewer page in Thrimbletrimmer, and cannot make any updates to the system.

Each user can only have one role.

### Database Schema
There are two database tables - one contains a list of users and their roles, the other defines the roles and some their permissions.

#### Members Table

columns                    | type                               | description
-------------------------- | ---------------------------------- | -----------
`id`                       | `IDENTITY PRIMARY KEY`             | Unique account ID.
`user_email`               | `TEXT NOT NULL`                    | The email account used for the member's Google sign in.
`role`                     | `INT FOREIGN KEY`                  | The ID for a role from the Roles table.

#### Role Table

columns                    | type                               | description
-------------------------- | ---------------------------------- | -----------
`id`                       | `IDENTITY PRIMARY KEY`             | Unique ID for the role
`role_name`                | `TEXT NOT NULL`                    | The name of the role
`event_column_whitelist`   | `TEXT[]`                           | A list of column names from the Events table that can be updated by users with this role.
