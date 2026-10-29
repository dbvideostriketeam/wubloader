#!/bin/bash

set -eu

usage() {
	echo "USAGE: $0 [OPTIONS] NAME CONNINFO"
	echo "NAME should be a unique name for your node"
	echo "CONNINFO should be a postgres connection url like postgresql://USER:PASS@HOSTNAME/DATABASE"
	echo "Options:"
	echo "  --limit LIMIT"
	echo "      Exits after doing LIMIT jobs, default unlimited."
	echo "      Use limit 0 if you just want to clean up after a crash without doing any jobs."
	echo "  --claim URL"
	echo "      Explicitly pick the first job to claim (by dest URL). Will error if already claimed by someone else."
	exit 1
}

WORKDIR=${WORKDIR:-.}
LIMIT=-1
FIRST_CLAIM=

ARGS=()
while [ "$#" -gt 0 ]; do
	arg=$1
	shift
	case "$arg" in
		--limit)
			LIMIT=${1?--limit argument required}
			shift
			;;
		--claim)
			FIRST_CLAIM=${1?--claim argument required}
			shift
			;;
		--*)
			echo "Unknown option: $arg"
			;;
		*)
			ARGS+=("$arg")
	esac
done

if [ "${#ARGS[@]}" -ne 2 ]; then
	usage
fi

NAME="${ARGS[0]}"
CONNINFO="${ARGS[1]}"

logcmd() {
	echo "Running: $*" >&2
	"$@"
}

retry() {
	stdin=$(cat)
	TRIES=$1
	shift
	for try in $(seq "$((TRIES - 1))"); do
		if "$@" <<<"$stdin"; then
			return
		fi
		echo "$1 exited $?, retrying in $try seconds" >&2
	done
	"$@" <<<"$stdin"
}

db() {
	retry 5 psql -Atqbv ON_ERROR_STOP=on "$CONNINFO" "$@"
}

# Expects a url matching "scp://USER:PASS@HOST:PORT/PATH"
# Returns USER PASS HOST PORT PATH, assumes all but path contain no whitespace. Assumes no URL-encoded chars.
url_to_parts() {
	parts=$(sed -E 's|scp://([^:@]+):([^@]+)@([^:]+):([0-9]+)/(.+)|\1 \2 \3 \4 \5|' <<<"$1")
	if [ "$parts" == "$1" ]; then # no substitution
		echo "Could not parse URL: $1" >&2
		return 1
	fi
	echo "$parts"
}

url_to_filename() {
	local user pass host port path name
	parts=$(url_to_parts "$1")
	read -r user pass host port path <<<"$parts"
	name=$(basename "$path")
	echo "$WORKDIR/$name"
}

copy_file() {
	local user pass host port path file
	parts=$(url_to_parts "$1")
	read -r user pass host port path <<<"$parts"
	file=$(url_to_filename "$1")
	passfile=$(mktemp)
	# shellcheck disable=SC2064
	trap "rm -f $passfile" RETURN
	echo "$pass" > "$passfile"
	if [ "$2" == "up" ]; then
		RSYNC_ARGS=("$file" "$user@$host:$path")
	else
		RSYNC_ARGS=("$user@$host:$path" "$file")
	fi
	retry 5 \
		logcmd \
		sshpass -f "$passfile" \
		rsync -avzP -e "ssh -p $port -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no" \
			"${RSYNC_ARGS[@]}" </dev/null
}

download_file() {
	copy_file "$1" down
}

upload_file() {
	copy_file "$1" up
}

encode() {
	local src dest args
	src="$1"
	dest="$2"
	shift 2
	args=()
	for arg in "$@"; do
		sub=$(sed "s|{SRC_FILE}|$src|g; s|{DEST_FILE}|$dest|g" <<<"$arg")
		args+=("$sub")
	done
	logcmd ffmpeg -hide_banner -nostdin -y "${args[@]}"
}

quit_after_current() {
	LIMIT=0
	echo "Will quit when current job is finished"
}

trap quit_after_current TERM

existing=$(
	db -F ' ' -v name="$NAME" <<-SQL
		SELECT dest_url FROM encodes
		WHERE claimed_by = :'name' AND dest_hash IS NULL
	SQL
)
if [ -n "$existing" ]; then
	echo "WARNING: The following files are already claimed by this node:"
	echo "$existing"
	echo
	echo -n "This is likely due to a crash. (U)nclaim, (r)esume or (i)gnore? [U/r/i] > "
	read -r resp
	case "$resp" in
		"u" | "")
			db -v name="$NAME" <<-SQL
				UPDATE encodes SET
					claimed_by = NULL,
					claimed_at = NULL
				WHERE claimed_by = :'name' AND dest_hash IS NULL
			SQL
			;;
		"r")
			if [ "$(wc -l <<<"$existing")" -ne 1 ]; then
				echo "Cannot resume: multiple claimed rows. This shouldn't happen!"
				exit 1
			fi
			FIRST_CLAIM="$existing"
			;;
		"i")
			echo "Continuing without unclaiming rows."
			;;
		*)
			echo "Unknown option: $resp"
			exit 1
	esac
fi

while [ "$((LIMIT--))" -ne 0 ] ; do
	if [ -n "$FIRST_CLAIM" ]; then
		echo "Claiming $FIRST_CLAIM"
		claimed=$(
			db -F ' ' -v "url=$FIRST_CLAIM" <<-SQL
				SELECT src_url, src_hash, claimed_by, COALESCE(dest_hash, 'unset')
				FROM encodes
				WHERE dest_url = :'url'
			SQL
		)
		if ! [ -n "$claimed" ]; then
			echo "Explicitly claimed job not found: $FIRST_CLAIM"
			exit 1
		fi

		read -r src_url src_hash claimed_by dest_hash <<<"$claimed"
		if [ "$dest_hash" != "unset" ]; then
			echo "Explicitly claimed job is already complete: $FIRST_CLAIM"
			exit 1
		fi
		if [ "$claimed_by" != "$NAME" ]; then
			echo "Explicitly claimed job already claimed by $claimed_by: $FIRST_CLAIM"
			exit 1
		fi
		dest_url="$FIRST_CLAIM"
		FIRST_CLAIM=
	else
		echo "Checking for jobs"
		claimed=$(
			db -F ' ' -v name="$NAME" <<-SQL
				UPDATE encodes SET
					claimed_by = :'name',
					claimed_at = now()
				WHERE dest_url = (
					SELECT dest_url FROM encodes
					WHERE claimed_by IS NULL AND dest_hash IS NULL
					ORDER BY priority DESC, random()
					LIMIT 1
					FOR UPDATE
				)
				RETURNING src_url, src_hash, dest_url
			SQL
		)
		if [ -z "$claimed" ]; then
			echo "No available jobs, will check again in 1min"
			sleep 60
			continue
		fi

		read -r src_url src_hash dest_url <<<"$claimed"
	fi

	src_file=$(url_to_filename "$src_url")
	dest_file=$(url_to_filename "$dest_url")
	echo "Got task to encode $dest_file"
	# Read encode args seperately as we need to split out the array.
	# The following query outputs one row per arg, seperated by nul chars.
	# readarray -d '' will read into the given array after splitting on nul chars.
	readarray -td '' encode_args < <(
		db -0 -v dest_url="$dest_url" <<-SQL
			SELECT unnest(encode_args) FROM encodes
			WHERE dest_url = :'dest_url'
		SQL
	)
	if [ -f "$src_file" ]; then
		if sha256sum --status -c - <<<"$src_hash  $src_file"; then
			echo "Source file already exists - skipping download"
		else
			echo "Existing source file does not match hash - assuming corrupt and re-downloading."
			rm "$src_file"
		fi
	fi
	if ! [ -f "$src_file" ]; then
		echo "Downloading source file"
		download_file "$src_url"
		echo "Checking source file checksum"
		sha256sum --status -c - <<<"$src_hash  $src_file"
	fi
	echo "Starting encode"
	encode "$src_file" "$dest_file" "${encode_args[@]}"
	echo "Encode complete, uploading output file"
	upload_file "$dest_url"
	echo "Calculating output hash and marking complete"
	dest_hash=$(sha256sum "$dest_file" | cut -d' ' -f1)
	# Re-setting claimed_by *should* be a no-op here but if something has
	# gone wrong at least we'll know which node is writing.
	db -v dest_url="$dest_url" -v dest_hash="$dest_hash" -v name="$NAME" <<-SQL
		UPDATE encodes SET
			dest_hash = :'dest_hash',
			claimed_by = :'name',
			finished_at = now()
		WHERE dest_url = :'dest_url'
	SQL

done
