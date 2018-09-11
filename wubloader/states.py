# -*- coding: utf-8 -*-

QUEUED = "[✓] Queued"
PROCESSING_VIDEO = "[^] Processing Video"
AWAITING_EDITS = "[✓] Awaiting Edits"
EDITS_QUEUED = "[✓] Edits Queued"
PROCESSING_EDITS = "[^] Processing Edits"
UPLOADING = "[^] Uploading"
PUBLISHED = "[✓] Published"
ERROR = "[❌] Error"


# Map {name: (ready, *in progress, complete)} state flows.
# Note that due to bot deaths, etc, it can be pretty easy for something to be in an in-progress state
# but not actually be in progress. We treat in progress and ready states as basically equivalent and only
# existing for human feedback. Our actual in progress indicator comes from the uploader field,
# which can be ignored if the uploader in question is dead.
FLOWS = {
	'draft': (QUEUED, PROCESSING_VIDEO, AWAITING_EDITS),
	'publish': (EDITS_QUEUED, PROCESSING_EDITS, UPLOADING, PUBLISHED),
	'chunk': (QUEUED, PROCESSING_VIDEO, UPLOADING, PUBLISHED),
}
CHUNK_FLOWS = ('chunk',)
MAIN_FLOWS = ('draft', 'publish')


# Whether this is a state we want to act on, defined as any non-complete state.
def is_actionable(sheet_type, state):
	flows = CHUNK_FLOWS if sheet_type == 'chunks' else MAIN_FLOWS
	for name in flows:
		flow = FLOWS[name]
		if state in flow[:-1]:
			return True
	return False


# General map from in-progress states to the state to rollback to.
# For non-in-progress states, we just map them to themselves.
def rollback(sheet_type, state):
	flows = CHUNK_FLOWS if sheet_type == 'chunks' else MAIN_FLOWS
	for name in flows:
		flow = FLOWS[name]
		for s in flow[1:-1]: # for each in progress state
			if s == state:
				return flow[0] # return the first state in the flow
	return state # if no in progress state matches, return same state
