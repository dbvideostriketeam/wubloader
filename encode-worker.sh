#!/bin/bash

set -eu

if [ "$#" -lt 2 ]; then
	echo "USAGE: $0 NAME CONNINFO [LIMIT]"
	echo "NAME should be a unique name for your node"
	echo "CONNINFO should be a postgres connection url like postgresql://USER:PASS@HOSTNAME/DATABASE"
	echo "Exits after doing LIMIT jobs, default unlimited. Use limit 0 if you just want to clean up after a crash without doing any jobs."
	exit 1
fi

NAME="$1"
CONNINFO="$2"
LIMIT="${3:--1}"
WORKDIR=${WORKDIR:-.}

logcmd() {
	echo "Running: $*" >&2
	"$@"
}

db() {
	psql -Atqbv ON_ERROR_STOP=on "$CONNINFO" "$@"
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

download_file() {
	local user pass host port path file
	parts=$(url_to_parts "$1")
	read -r user pass host port path <<<"$parts"
	file=$(url_to_filename "$1")
	logcmd sshpass -p "$pass" scp -P "$port" "$user@$host:$path" "$file"
}

upload_file() {
	local user pass host port path file
	parts=$(url_to_parts "$1")
	read -r user pass host port path <<<"$parts"
	file=$(url_to_filename "$1")
	logcmd sshpass -p "$pass" scp -P "$port" "$file" "$user@$host:$path"
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
	db -v name="$NAME" <<-SQL
		SELECT claimed_at, dest_url FROM encodes
		WHERE claimed_by = :'name' AND dest_hash IS NULL
	SQL
)
if [ -n "$existing" ]; then
	echo "WARNING: The following files are already claimed by this node:"
	echo "$existing"
	echo
	echo -n "This is likely due to a crash. Unclaim these files? [Y/n] > "
	read -r resp
	if [ "$resp" != "n" ]; then
		db -v name="$NAME" <<-SQL
			UPDATE encodes SET
				claimed_by = NULL,
				claimed_at = NULL
			WHERE claimed_by = :'name' AND dest_hash IS NULL
		SQL
	fi
fi

while [ "$((LIMIT--))" -ne 0 ] ; do
	echo "Checking for jobs"
	claimed=$(
		db -F ' ' -v name="$NAME" <<-SQL
			UPDATE encodes SET
				claimed_by = :'name',
				claimed_at = now()
			WHERE dest_url = (
				SELECT dest_url FROM encodes
				WHERE claimed_by IS NULL AND dest_hash IS NULL
				LIMIT 1
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
		echo "Downloading source file (no progress bar sorry, blame scp)"
		download_file "$src_url"
		echo "Checking source file checksum"
		sha256sum --status -c - <<<"$src_hash  $src_file"
	fi
	echo "Starting encode"
	encode "$src_file" "$dest_file" "${encode_args[@]}"
	echo "Encode complete, uploading output file (still no progress bar)"
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
