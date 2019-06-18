Information on how accounts and permissions are handled within Wubloader.

### Google Authentication

Google OAuth is used to authenticate users and return a user token. The Token is then passed alongside calls that need authentication 
and is validated server-side against a Google API. The API returns the authenticated user's email address (along with other basic 
profile information).

The email address is then used to look up the user in the database to check their permissions.

The current plan is to only authenticate/authorize users on datebase updates coming from Thrimbletrimmer; and since most use cases will 
only have a single update event every few minutes, we can authenticate only as need - rather than authenticating on page load and storing session IDs.

### Wubloader Authorization

Current tasks via Thrimshim are:
* `get_row`: Return a single row from the database by ID. Unauthenticated.
* `update_row`: Updates row in the Events table. Authenticated and limited to Editors and Admins (who can update different sets of rows).
* `manual_link`: Override the `video_link` field in the Events Table, in case of a manual upload. Authenticated and limited to Editors and Admins.
* `reset_row`: Clear `state` and `video_link` columns and reset `state` to 'UNEDITED' in Events table. Authenticated and limited to Admins?

Proposed actions:
* `get_all_rows`: Return the entire events table (or specific subsets of it), for building dashboards. Unauthenticated
* `submit_edits`: Rather than have have Thrimbletrimmer submit video edits to a generic update action/endpoint, have it go via a dedicated action that can only update the necessary actions. Authenticated to Editors and Admins.
* `admin_update_row`: An "update row" action that can update all non-sheet-input fields as an "admin override".

The planned roles are:
* `Admin`: Like editors, but with the ability to modify additional fields the "state" column in case of errors, and will have access to a special dashboard page for doing those edits.
* `Editor`: Normal users, able to submit edits for Wubloader to cut via Thrimbletrimmer.
* `Viewer`: For potential users such as Giffers, who will have their own viewer page in Thrimbletrimmer, and cannot make any updates to the system. Since we aren't currently doing any authentication on Read actions, this won't be used for now.

Each user can only have one role.

### Database Schema

#### Members Table

columns                    | type                               | description
-------------------------- | ---------------------------------- | -----------
`id`                       | `IDENTITY PRIMARY KEY`             | Unique account ID.
`user_email`               | `TEXT NOT NULL`                    | The email account used for the member's Google sign in.
`role`                     | `TEXT NOT NULL`                    | Name of the role to be used
