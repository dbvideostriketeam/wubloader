var desertBusStart = new Date("1970-01-01T00:00:00Z");
var timeFormat = "AGO";

function pageSetup(isEditor) {
	//Get values from ThrimShim
	if (isEditor && /id=/.test(document.location.search)) {
		var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
		fetch("/thrimshim/" + rowId)
			.then(data => data.json())
			.then(function (data) {
				if (!data) {
					alert("No video available for stream.");
					return;
				}
				document.data = data;
				desertBusStart = new Date(data.bustime_start);
				document.getElementById("VideoTitlePrefix").value = data.title_prefix;
				document.getElementById("VideoTitle").setAttribute("maxlength", data.title_max_length);

				document.getElementById("StreamName").value = data.video_channel;
				document.getElementById("hiddenSubmissionID").value = data.id;
				// for editor, switch to bustime since that's the default
				timeFormat = "BUSTIME";
				// Apply padding - start 1min early, finish 2min late because these times are generally
				// rounded down to the minute, so if something ends at "00:10" it might actually end
				// at 00:10:59 so we should pad to 00:12:00.
				var start = data.event_start
					? new Date(fromTimestamp(data.event_start).getTime() - 60 * 1000)
					: null;
				var end = data.event_end
					? new Date(fromTimestamp(data.event_end).getTime() + 2 * 60 * 1000)
					: null;
				setTimeRange(start, end);
				// title and description both default to row description
				document.getElementById("VideoTitle").value = data.video_title
					? data.video_title
					: data.description;
				document.getElementById("VideoDescription").value = data.video_description
					? data.video_description
					: data.description;
				// tags default to tags from sheet
				document.getElementById("VideoTags").value = tags_list_to_string(
					data.video_tags ? data.video_tags : data.tags
				);

				// If any edit notes, show them
				if (data.notes.length > 0) {
					document.getElementById("EditNotes").value = data.notes;
					document.getElementById("EditNotesPane").style.display = "block";
				}

				// Restore advanced options. If any of these are non-default, automatically expand the advanced options pane.
				setOptions("uploadLocation", data.upload_locations, data.upload_location);
				document.getElementById("AllowHoles").checked = data.allow_holes;
				document.getElementById("uploaderWhitelist").value = !!data.uploader_whitelist
					? data.uploader_whitelist.join(",")
					: "";
				if (
					(data.upload_locations.length > 0 &&
						data.upload_location != null &&
						data.upload_location != data.upload_locations[0]) ||
					data.allow_holes ||
					!!data.uploader_whitelist
				) {
					document.getElementById("wubloaderAdvancedInputTable").style.display = "block";
				}

				loadPlaylist(isEditor, data.video_start, data.video_end, data.video_quality);
			});
	} else {
		if (isEditor) {
			document.getElementById("SubmitButton").disabled = true;
		}

		fetch("/thrimshim/defaults")
			.then(data => data.json())
			.then(function (data) {
				if (!data) {
					alert("Editor results call failed, is thrimshim running?");
					return;
				}
				desertBusStart = new Date(data.bustime_start);
				document.getElementById("StreamName").value = data.video_channel;
				if (isEditor) {
					document.getElementById("VideoTitlePrefix").value = data.title_prefix;
					document.getElementById("VideoTitle").setAttribute("maxlength", data.title_max_length);
					setOptions("uploadLocation", data.upload_locations);
				}

				// Default time format changes depending on mode.
				// But in both cases the default input value is 10min ago / "",
				// it's just for editor we convert it before the user sees.
				if (isEditor) {
					toggleTimeInput("BUSTIME");
				}

				loadPlaylist(isEditor);
			});
	}
};

// Time-formatting functions

function parseDuration(duration) {
	var direction = 1;
	if (duration.startsWith("-")) {
		duration = duration.slice(1);
		direction = -1;
	}
	var parts = duration.split(":");
	return (
		(parseInt(parts[0]) + (parts[1] || "0") / 60 + (parts[2] || "0") / 3600) * 60 * 60 * direction
	);
};

function toBustime(date) {
	return (
		(date < desertBusStart ? "-" : "") +
		videojs.formatTime(Math.abs((date - desertBusStart) / 1000), 600.01).padStart(7, "0:")
	);
};

function fromBustime(bustime) {
	return new Date(desertBusStart.getTime() + 1000 * parseDuration(bustime));
};

function toTimestamp(date) {
	return date.toISOString().substring(0, 19);
};

function fromTimestamp(ts) {
	return new Date(ts + "Z");
};

function toAgo(date) {
	now = new Date();
	return (
		(date < now ? "" : "-") +
		videojs.formatTime(Math.abs((date - now) / 1000), 600.01).padStart(7, "0:")
	);
};

function fromAgo(ago) {
	return new Date(new Date().getTime() - 1000 * parseDuration(ago));
};

// Set the stream start/end range from a pair of Dates using the current format
// If given null, sets to blank.
function setTimeRange(start, end) {
	var toFunc = {
		UTC: toTimestamp,
		BUSTIME: toBustime,
		AGO: toAgo,
	}[timeFormat];
	document.getElementById("StreamStart").value = start ? toFunc(start) : "";
	document.getElementById("StreamEnd").value = end ? toFunc(end) : "";
};

// Get the current start/end range as Dates using the current format
// Returns an object containing 'start' and 'end' fields.
// If either is empty / invalid, returns null.
function getTimeRange() {
	var fromFunc = {
		UTC: fromTimestamp,
		BUSTIME: fromBustime,
		AGO: fromAgo,
	}[timeFormat];
	var convert = function (value) {
		if (!value) {
			return null;
		}
		var date = fromFunc(value);
		return isNaN(date) ? null : date;
	};
	return {
		start: convert(document.getElementById("StreamStart").value),
		end: convert(document.getElementById("StreamEnd").value),
	};
};

function getTimeRangeAsTimestamp() {
	var range = getTimeRange();
	return {
		// if not null, format as timestamp
		start: range.start && toTimestamp(range.start),
		end: range.end && toTimestamp(range.end),
	};
};

function toggleHiddenPane(paneID) {
	var pane = document.getElementById(paneID);
	pane.style.display = pane.style.display === "none" ? "block" : "none";
};

function toggleUltrawide() {
	var body = document.getElementsByTagName("Body")[0];
	body.classList.contains("ultrawide")
		? body.classList.remove("ultrawide")
		: body.classList.add("ultrawide");
};

function toggleTimeInput(toggleInput) {
	// Get times using current format, then change format, then write them back
	var range = getTimeRange();
	timeFormat = toggleInput;
	setTimeRange(range.start, range.end);
};

// For a given select input element id, add the given list of options.
// If selected is given, it should be the name of an option to select.
// Otherwise the first one is used.
function setOptions(element, options, selected) {
	if (!selected && options.length > 0) {
		selected = options[0];
	}
	options.forEach(function (option) {
		document.getElementById(element).innerHTML +=
			'<option value="' +
			option +
			'" ' +
			(option == selected ? "selected" : "") +
			">" +
			option +
			"</option>";
	});
};

function buildQuery(params) {
	return Object.keys(params)
		.filter(key => params[key] !== null)
		.map(key => encodeURIComponent(key) + "=" + encodeURIComponent(params[key]))
		.join("&");
};

function loadPlaylist(isEditor, startTrim, endTrim, defaultQuality) {
	var playlist = "/playlist/" + document.getElementById("StreamName").value + ".m3u8";

	var range = getTimeRangeAsTimestamp();
	var queryString = buildQuery(range);

	// Preserve existing edit times
	if (player && player.trimmingControls && player.vhs.playlists.master) {
		var discontinuities = mapDiscontinuities();
		if (!startTrim) {
			startTrim = getRealTimeForPlayerTime(
				discontinuities,
				player.trimmingControls().options.startTrim
			);
			if (startTrim) {
				startTrim = startTrim.replace("Z", "");
			}
		}
		if (!endTrim) {
			endTrim = getRealTimeForPlayerTime(
				discontinuities,
				player.trimmingControls().options.endTrim
			);
			if (endTrim) {
				endTrim = endTrim.replace("Z", "");
			}
		}
	}

	setupPlayer(isEditor, playlist + "?" + queryString, startTrim, endTrim);

	//Get quality levels for advanced properties / download
	document.getElementById("qualityLevel").innerHTML = "";
	fetch("/files/" + document.getElementById("StreamName").value)
		.then(data => data.json())
		.then(function (data) {
			if (!data.length) {
				console.log("Could not retrieve quality levels");
				return;
			}
			var qualityLevels = data.sort().reverse();
			setOptions("qualityLevel", qualityLevels, defaultQuality);
			if (!!defaultQuality && qualityLevels.length > 0 && defaultQuality != qualityLevels[0]) {
				document.getElementById("wubloaderAdvancedInputTable").style.display = "block";
			}
		});
};

function thrimbletrimmerSubmit(state, override_changes = false) {
	document.getElementById("SubmitButton").disabled = true;
	var discontinuities = mapDiscontinuities();

	var start = getRealTimeForPlayerTime(
		discontinuities,
		player.trimmingControls().options.startTrim
	);
	if (start) {
		start = start.replace("Z", "");
	}
	var end = getRealTimeForPlayerTime(discontinuities, player.trimmingControls().options.endTrim);
	if (end) {
		end = end.replace("Z", "");
	}

	var wubData = {
		video_start: start,
		video_end: end,
		video_title: document.getElementById("VideoTitle").value,
		video_description: document.getElementById("VideoDescription").value,
		video_tags: tags_string_to_list(document.getElementById("VideoTags").value),
		allow_holes: document.getElementById("AllowHoles").checked,
		upload_location: document.getElementById("uploadLocation").value,
		video_channel: document.getElementById("StreamName").value,
		video_quality:
			document.getElementById("qualityLevel").options[
				document.getElementById("qualityLevel").options.selectedIndex
			].value,
		uploader_whitelist: document.getElementById("uploaderWhitelist").value
			? document.getElementById("uploaderWhitelist").value.split(",")
			: null,
		state: state,
		//pass back the sheet columns to check if any have changed
		sheet_name: document.data.sheet_name,
		event_start: document.data.event_start,
		event_end: document.data.event_end,
		category: document.data.category,
		description: document.data.description,
		notes: document.data.notes,
		tags: document.data.tags,
	};
	if (!!user) {
		wubData.token = user.getAuthResponse().id_token;
	}
	if (override_changes) {
		wubData["override_changes"] = true;
	}
	console.log(wubData);
	console.log(JSON.stringify(wubData));

	if (!wubData.video_start) {
		alert("No start time set");
		return;
	}
	if (!wubData.video_end) {
		alert("No end time set");
		return;
	}

	//Submit to thrimshim
	var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
	fetch("/thrimshim/" + rowId, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(wubData),
	}).then(response =>
		response.text().then(text => {
			if (!response.ok) {
				var error = response.statusText + ": " + text;
				if (response.status == 409) {
					dialogue = text + "\nClick Ok to submit anyway; Click Cancel to return to editing";
					if (confirm(dialogue)) {
						thrimbletrimmerSubmit(state, true);
					}
				} else {
					alert(error);
				}
			} else if (state == "EDITED") {
				alert(`Edit submitted for video from ${start} to ${end}`);
			} else {
				alert("Draft saved");
			}
			document.getElementById("SubmitButton").disabled = false;
		})
	);
};

function thrimbletrimmerDownload(isEditor) {
	var range = getTimeRangeAsTimestamp();
	if (isEditor) {
		if (player.trimmingControls().options.startTrim >= player.trimmingControls().options.endTrim) {
			alert("End Time must be greater than Start Time");
			return;
		}
		var discontinuities = mapDiscontinuities();
		range.start = getRealTimeForPlayerTime(
			discontinuities,
			player.trimmingControls().options.startTrim
		);
		range.end = getRealTimeForPlayerTime(
			discontinuities,
			player.trimmingControls().options.endTrim
		);
	}

	var targetURL =
		"/cut/" +
		document.getElementById("StreamName").value +
		"/" +
		document.getElementById("qualityLevel").options[
			document.getElementById("qualityLevel").options.selectedIndex
		].value +
		".ts" +
		"?" +
		buildQuery({
			start: range.start,
			end: range.end,
			// In non-editor, always use rough cut. They don't have the edit controls to do
			// fine time selection anyway.
			type: isEditor
				? document.getElementById("DownloadType").options[
						document.getElementById("DownloadType").options.selectedIndex
				  ].value
				: "rough",
			// Always allow holes in non-editor, accidentially including holes isn't important
			allow_holes: isEditor ? String(document.getElementById("AllowHoles").checked) : "true",
		});
	console.log(targetURL);
	document.getElementById("DownloadLink").href = targetURL;
	document.getElementById("DownloadLink").style.display = "";
};

function thrimbletrimmerManualLink() {
	document.getElementById("ManualButton").disabled = true;
	var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
	var upload_location = document.getElementById("ManualYoutube").checked
		? "youtube-manual"
		: "manual";
	var body = {
		link: document.getElementById("ManualLink").value,
		upload_location: upload_location,
	};
	if (!!user) {
		body.token = user.getAuthResponse().id_token;
	}
	fetch("/thrimshim/manual-link/" + rowId, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(body),
	}).then(response =>
		response.text().then(text => {
			if (!response.ok) {
				var error = response.statusText + ": " + text;
				console.log(error);
				alert(error);
				document.getElementById("ManualButton").disabled = false;
			} else {
				alert("Manual link set to " + body.link);
				setTimeout(() => {
					window.location.href = "/thrimbletrimmer/dashboard.html";
				}, 500);
			}
		})
	);
};

function thrimbletrimmerResetLink(force) {
	var rowId = /id=(.*)(?:&|$)/.exec(document.location.search)[1];
	if (
		force &&
		!confirm(
			"Are you sure you want to reset this event? " +
				"This will set the row back to UNEDITED and forget about any video that already may exist. " +
				"It is intended as a last-ditch command to clear a malfunctioning cutter, " +
				"or if a video needs to be re-edited and replaced. " +
				"IT IS YOUR RESPONSIBILITY TO DEAL WITH ANY VIDEO THAT MAY HAVE ALREADY BEEN UPLOADED. "
		)
	) {
		return;
	}
	document.getElementById("ResetButton").disabled = true;
	document.getElementById("CancelButton").disabled = true;
	var body = {};
	if (!!user) {
		body.token = user.getAuthResponse().id_token;
	}
	fetch("/thrimshim/reset/" + rowId + "?force=" + force, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(body),
	}).then(response =>
		response.text().then(text => {
			if (!response.ok) {
				var error = response.statusText + ": " + text;
				console.log(error);
				alert(error);
				document.getElementById("ResetButton").disabled = false;
				document.getElementById("CancelButton").disabled = true;
			} else {
				alert("Row has been " + (force ? "reset" : "cancelled") + ". Reloading...");
				setTimeout(() => {
					window.location.reload();
				}, 500);
			}
		})
	);
};

function tags_list_to_string(tag_list) {
	return tag_list.join(", ");
};

function tags_string_to_list(tag_string) {
	return tag_string
		.split(",")
		.map(tag => tag.trim())
		.filter(tag => tag.length > 0);
};

function round_trip_tag_string() {
	var element = document.getElementById("VideoTags");
	element.value = tags_list_to_string(tags_string_to_list(element.value));
};
