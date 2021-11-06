var googleUser = null;
var videoInfo;
var currentRange = 1;

window.addEventListener("DOMContentLoaded", async (event) => {
	commonPageSetup();

	const timeUpdateForm = document.getElementById("stream-time-settings");
	timeUpdateForm.addEventListener("submit", (event) => {
		event.preventDefault();

		if (!videoInfo) {
			addError(
				"Time updates are ignored before the video metadata has been retrieved from Wubloader."
			);
			return;
		}

		const newStartField = document.getElementById("stream-time-setting-start");
		const newStart = dateTimeFromBusTime(newStartField.value);
		if (!newStart) {
			addError("Failed to parse start time");
			return;
		}

		const newEndField = document.getElementById("stream-time-setting-end");
		let newEnd = null;
		if (newEndField.value !== "") {
			newEnd = dateTimeFromBusTime(newEndField.value);
			if (!newEnd) {
				addError("Failed to parse end time");
				return;
			}
		}

		const oldStart = getStartTime();
		const startAdjustment = newStart.diff(oldStart).as("seconds");
		let newDuration = newEnd === null ? Infinity : newEnd.diff(newStart).as("seconds");

		// The video duration isn't precisely the video times, but can be padded by up to the
		// segment length on either side.
		const segmentList = getSegmentList();
		newDuration += segmentList[0].duration;
		newDuration += segmentList[segmentList.length - 1].duration;

		// Abort for ranges that exceed new times
		for (const rangeContainer of document.getElementById("range-definitions").children) {
			const rangeStartField = rangeContainer.getElementsByClassName("range-definition-start")[0];
			const rangeEndField = rangeContainer.getElementsByClassName("range-definition-end")[0];
			const rangeStart = videoPlayerTimeFromVideoHumanTime(rangeStartField.value);
			const rangeEnd = videoPlayerTimeFromVideoHumanTime(rangeEndField.value);

			if (rangeStart !== null && rangeStart < startAdjustment) {
				addError("The specified video load time excludes part of an edited clip range.");
				return;
			}
			if (rangeEnd !== null && rangeEnd + startAdjustment > newDuration) {
				addError("The specified video load time excludes part of an edited clip range.");
				return;
			}
		}

		globalStartTimeString = wubloaderTimeFromDateTime(newStart);
		globalEndTimeString = wubloaderTimeFromDateTime(newEnd);

		updateSegmentPlaylist();

		let rangeErrorCount = 0;
		for (const rangeContainer of document.getElementById("range-definitions").children) {
			const rangeStartField = rangeContainer.getElementsByClassName("range-definition-start")[0];
			const rangeEndField = rangeContainer.getElementsByClassName("range-definition-end")[0];

			const rangeStart = videoPlayerTimeFromVideoHumanTime(rangeStartField.value);
			if (rangeStart === null) {
				rangeErrorCount++;
			} else {
				rangeStartField.value = videoHumanTimeFromVideoPlayerTime(rangeStart - startAdjustment);
			}

			const rangeEnd = videoPlayerTimeFromVideoHumanTime(rangeEndField.value);
			if (rangeEnd === null) {
				rangeErrorCount++;
			} else {
				rangeEndField.value = videoHumanTimeFromVideoPlayerTime(rangeEnd - startAdjustment);
			}
		}
		if (rangeErrorCount > 0) {
			addError(
				"Some ranges couldn't be updated for the new video time endpoints. Please verify the time range values."
			);
		}
		rangeDataUpdated();

		const waveformImage = document.getElementById("waveform");
		if (newEnd === null) {
			waveformImage.classList.add("hidden");
		} else {
			updateWaveform();
			waveformImage.classList.remove("hidden");
		}
	});

	await loadVideoInfo();

	document.getElementById("stream-time-setting-start-pad").addEventListener("click", (_event) => {
		const startTimeField = document.getElementById("stream-time-setting-start");
		let startTime = startTimeField.value;
		startTime = dateTimeFromBusTime(startTime);
		startTime = startTime.minus({ minutes: 1 });
		startTimeField.value = busTimeFromDateTime(startTime);
	});

	document.getElementById("stream-time-setting-end-pad").addEventListener("click", (_event) => {
		const endTimeField = document.getElementById("stream-time-setting-end");
		let endTime = endTimeField.value;
		endTime = dateTimeFromBusTime(endTime);
		endTime = endTime.plus({ minutes: 1 });
		endTimeField.value = busTimeFromDateTime(endTime);
	});

	const addRangeIcon = document.getElementById("add-range-definition");
	addRangeIcon.addEventListener("click", (_event) => {
		addRangeDefinition();
	});
	addRangeIcon.addEventListener("keypress", (event) => {
		if (event.key === "Enter") {
			addRangeDefinition();
		}
	});

	for (const rangeStartSet of document.getElementsByClassName("range-definition-set-start")) {
		rangeStartSet.addEventListener("click", getRangeSetClickHandler("start"));
	}
	for (const rangeEndSet of document.getElementsByClassName("range-definition-set-end")) {
		rangeEndSet.addEventListener("click", getRangeSetClickHandler("end"));
	}
	for (const rangeStartPlay of document.getElementsByClassName("range-definition-play-start")) {
		rangeStartPlay.addEventListener("click", rangePlayFromStartHandler);
	}
	for (const rangeEndPlay of document.getElementsByClassName("range-definition-play-end")) {
		rangeEndPlay.addEventListener("click", rangePlayFromEndHandler);
	}
	for (const rangeStart of document.getElementsByClassName("range-definition-start")) {
		rangeStart.addEventListener("change", (_event) => {
			rangeDataUpdated();
		});
	}
	for (const rangeEnd of document.getElementsByClassName("range-definition-end")) {
		rangeEnd.addEventListener("change", (_event) => {
			rangeDataUpdated();
		});
	}

	document.getElementById("video-info-title").addEventListener("input", (_event) => {
		validateVideoTitle();
	});
	document.getElementById("video-info-description").addEventListener("input", (_event) => {
		validateVideoDescription();
	});

	document.getElementById("submit-button").addEventListener("click", (_event) => {
		submitVideo();
	});
	document.getElementById("save-button").addEventListener("click", (_event) => {
		saveVideoDraft();
	});

	document.getElementById("advanced-submission").addEventListener("click", (_event) => {
		const advancedOptionsContainer = document.getElementById("advanced-submission-options");
		advancedOptionsContainer.classList.toggle("hidden");
	});

	document
		.getElementById("advanced-submission-option-allow-holes")
		.addEventListener("change", () => {
			updateDownloadLink();
		});
	document.getElementById("download-type-select").addEventListener("change", () => {
		updateDownloadLink();
	});

	document.getElementById("manual-link-update").addEventListener("click", (_event) => {
		const manualLinkDataContainer = document.getElementById("data-correction-manual-link");
		manualLinkDataContainer.classList.toggle("hidden");
	});
	document
		.getElementById("data-correction-manual-link-submit")
		.addEventListener("click", (_event) => {
			setManualVideoLink();
		});

	document.getElementById("cancel-video-upload").addEventListener("click", (_event) => {
		cancelVideoUpload();
	});

	document.getElementById("reset-entire-video").addEventListener("click", (_event) => {
		const forceResetConfirmationContainer = document.getElementById(
			"data-correction-force-reset-confirm"
		);
		forceResetConfirmationContainer.classList.remove("hidden");
	});
	document.getElementById("data-correction-force-reset-yes").addEventListener("click", (_event) => {
		resetVideoRow();
	});
	document.getElementById("data-correction-force-reset-no").addEventListener("click", (_event) => {
		const forceResetConfirmationContainer = document.getElementById(
			"data-correction-force-reset-confirm"
		);
		forceResetConfirmationContainer.classList.add("hidden");
	});

	document.getElementById("google-auth-sign-out").addEventListener("click", (_event) => {
		googleSignOut();
	});
});

async function loadVideoInfo() {
	const queryParams = new URLSearchParams(window.location.search);
	if (!queryParams.has("id")) {
		addError("No video ID specified. Failed to load video data.");
		return;
	}
	const videoID = queryParams.get("id");
	const dataResponse = await fetch("/thrimshim/" + videoID);
	if (!dataResponse.ok) {
		addError(
			"Failed to load video data. This probably means that the URL is out of date (video ID changed) or that everything is broken (or that the Wubloader host is down)."
		);
		return;
	}
	videoInfo = await dataResponse.json();
	initializeVideoInfo();
}

async function initializeVideoInfo() {
	globalStreamName = videoInfo.video_channel;
	globalBusStartTime = DateTime.fromISO(videoInfo.bustime_start);

	let eventStartTime = dateTimeFromWubloaderTime(videoInfo.event_start);
	let eventEndTime = videoInfo.event_end ? dateTimeFromWubloaderTime(videoInfo.event_end) : null;

	// To account for various things (stream delay, just slightly off logging, etc.), we pad the start time by one minute
	eventStartTime = eventStartTime.minus({ minutes: 1 });

	// To account for various things (stream delay, just slightly off logging, etc.), we pad the end time by one minute.
	// To account for the fact that we don't record seconds, but the event could've ended any time in the recorded minute, we pad by an additional minute.
	if (eventEndTime) {
		eventEndTime = eventEndTime.plus({ minutes: 2 });
	}

	globalStartTimeString = wubloaderTimeFromDateTime(eventStartTime);
	if (eventEndTime) {
		globalEndTimeString = wubloaderTimeFromDateTime(eventEndTime);
	} else {
		document.getElementById("waveform").classList.add("hidden");
	}

	// If a video was previously edited to points outside the event range, we should expand the loaded video to include the edited range
	if (videoInfo.video_ranges && videoInfo.video_ranges.length > 0) {
		let earliestStartTime = null;
		let latestEndTime = null;
		for (const range of videoInfo.video_ranges) {
			let startTime = range[0];
			let endTime = range[1];

			if (startTime) {
				startTime = dateTimeFromWubloaderTime(startTime);
			} else {
				startTime = null;
			}

			if (endTime) {
				endTime = dateTimeFromWubloaderTime(endTime);
			} else {
				endTime = null;
			}

			if (!earliestStartTime || (startTime && startTime.diff(earliestStartTime).milliseconds < 0)) {
				earliestStartTime = startTime;
			}
			if (!latestEndTime || (endTime && endTime.diff(latestEndTime).milliseconds > 0)) {
				latestEndTime = endTime;
			}
		}

		if (earliestStartTime && earliestStartTime.diff(eventStartTime).milliseconds < 0) {
			earliestStartTime = earliestStartTime.minus({ minutes: 1 });
			globalStartTimeString = wubloaderTimeFromDateTime(earliestStartTime);
		}

		if (latestEndTime && latestEndTime.diff(eventEndTime).milliseconds > 0) {
			// If we're getting the time from a previous draft edit, we have seconds, so one minute is enough
			latestEndTime = latestEndTime.plus({ minutes: 1 });
			globalEndTimeString = wubloaderTimeFromDateTime(latestEndTime);
		}
	}

	document.getElementById("stream-time-setting-stream").innerText = globalStreamName;
	document.getElementById("stream-time-setting-start").value =
		busTimeFromWubloaderTime(globalStartTimeString);
	document.getElementById("stream-time-setting-end").value =
		busTimeFromWubloaderTime(globalEndTimeString);

	updateWaveform();

	const titlePrefixElem = document.getElementById("video-info-title-prefix");
	titlePrefixElem.innerText = videoInfo.title_prefix;

	const titleElem = document.getElementById("video-info-title");
	if (videoInfo.video_title) {
		titleElem.value = videoInfo.video_title;
	} else {
		titleElem.value = videoInfo.description;
	}
	validateVideoTitle();

	const descriptionElem = document.getElementById("video-info-description");
	if (videoInfo.video_description) {
		descriptionElem.value = videoInfo.video_description;
	} else {
		descriptionElem.value = videoInfo.description;
	}
	validateVideoDescription();

	const tagsElem = document.getElementById("video-info-tags");
	if (videoInfo.video_tags) {
		tagsElem.value = videoInfo.video_tags.join(",");
	} else {
		tagsElem.value = videoInfo.tags.join(",");
	}

	if (videoInfo.notes) {
		const notesTextElem = document.getElementById("video-info-editor-notes");
		notesTextElem.innerText = videoInfo.notes;

		const notesContainer = document.getElementById("video-info-editor-notes-container");
		notesContainer.classList.remove("hidden");
	}

	let modifiedAdvancedOptions = false;
	if (videoInfo.allow_holes) {
		const allowHolesCheckbox = document.getElementById("advanced-submission-option-allow-holes");
		allowHolesCheckbox.checked = true;
		modifiedAdvancedOptions = true;
	}

	const uploadLocationSelection = document.getElementById(
		"advanced-submission-option-upload-location"
	);
	for (locationName of videoInfo.upload_locations) {
		const option = document.createElement("option");
		option.value = locationName;
		option.innerText = locationName;
		if (videoInfo.upload_location === locationName) {
			option.selected = true;
		}
		uploadLocationSelection.appendChild(option);
	}
	if (uploadLocationSelection.options.selectedIndex > 0) {
		modifiedAdvancedOptions = true;
	}

	if (videoInfo.uploader_whitelist) {
		modifiedAdvancedOptions = true;
		const uploaderAllowlistBox = document.getElementById(
			"advanced-submission-option-uploader-allow"
		);
		uploaderAllowlistBox.value = videoInfo.uploader_whitelist.join(",");
	}

	if (modifiedAdvancedOptions) {
		const advancedSubmissionContainer = document.getElementById("advanced-submission-options");
		advancedSubmissionContainer.classList.remove("hidden");
	}

	await loadVideoPlayerFromDefaultPlaylist();

	const videoElement = document.getElementById("video");
	const handleInitialSetupForDuration = (_event) => {
		const rangeDefinitionsContainer = document.getElementById("range-definitions");
		if (videoInfo.video_ranges && videoInfo.video_ranges.length > 0) {
			for (let rangeIndex = 0; rangeIndex < videoInfo.video_ranges.length; rangeIndex++) {
				if (rangeIndex >= rangeDefinitionsContainer.children.length) {
					addRangeDefinition();
				}
				const startWubloaderTime = videoInfo.video_ranges[rangeIndex][0];
				const endWubloaderTime = videoInfo.video_ranges[rangeIndex][1];
				if (startWubloaderTime) {
					const startField =
						rangeDefinitionsContainer.children[rangeIndex].getElementsByClassName(
							"range-definition-start"
						)[0];
					startField.value = videoHumanTimeFromWubloaderTime(startWubloaderTime);
				}
				if (endWubloaderTime) {
					const endField =
						rangeDefinitionsContainer.children[rangeIndex].getElementsByClassName(
							"range-definition-end"
						)[0];
					endField.value = videoHumanTimeFromWubloaderTime(endWubloaderTime);
				}
			}
		} else {
			const rangeStartField =
				rangeDefinitionsContainer.getElementsByClassName("range-definition-start")[0];
			rangeStartField.value = videoHumanTimeFromWubloaderTime(globalStartTimeString);
			if (globalEndTimeString) {
				const rangeEndField =
					rangeDefinitionsContainer.getElementsByClassName("range-definition-end")[0];
				rangeEndField.value = videoHumanTimeFromWubloaderTime(globalEndTimeString);
			}
		}
		videoElement.removeEventListener("durationchange", handleInitialSetupForDuration);
	};
	videoElement.addEventListener("durationchange", handleInitialSetupForDuration);
	videoElement.addEventListener("durationchange", (_event) => {
		// Every time this is updated, we need to update based on the new video duration
		rangeDataUpdated();
	});

	videoElement.addEventListener("timeupdate", (_event) => {
		const timePercent = (videoElement.currentTime / videoElement.duration) * 100;
		document.getElementById("waveform-marker").style.left = `${timePercent}%`;
	});
}

function updateWaveform() {
	let waveformURL = "/waveform/" + globalStreamName + "/" + videoInfo.video_quality + ".png?";

	const queryStringParts = startAndEndTimeQueryStringParts();
	waveformURL += queryStringParts.join("&");

	const waveformElem = document.getElementById("waveform");
	waveformElem.src = waveformURL;
}

function googleOnSignIn(googleUserData) {
	googleUser = googleUserData;
	const signInElem = document.getElementById("google-auth-sign-in");
	const signOutElem = document.getElementById("google-auth-sign-out");
	signInElem.classList.add("hidden");
	signOutElem.classList.remove("hidden");
}

async function googleSignOut() {
	if (googleUser) {
		googleUser = null;
		await gapi.auth2.getAuthInstance().signOut();
		const signInElem = document.getElementById("google-auth-sign-in");
		const signOutElem = document.getElementById("google-auth-sign-out");
		signInElem.classList.remove("hidden");
		signOutElem.classList.add("hidden");
	}
}

function getStartTime() {
	if (!globalStartTimeString) {
		return null;
	}
	return dateTimeFromWubloaderTime(globalStartTimeString);
}

function getEndTime() {
	if (!globalEndTimeString) {
		return null;
	}
	return dateTimeFromWubloaderTime(globalEndTimeString);
}

function validateVideoTitle() {
	const videoTitleField = document.getElementById("video-info-title");
	const videoTitle = videoTitleField.value;
	if (videoTitle.length > videoInfo.title_max_length) {
		videoTitleField.classList.add("input-error");
		videoTitleField.title = "Title is too long";
	} else if (videoTitle.indexOf("<") !== -1 || videoTitle.indexOf(">") !== -1) {
		videoTitleField.classList.add("input-error");
		videoTitleField.title = "Title contains invalid characters";
	} else {
		videoTitleField.classList.remove("input-error");
		videoTitleField.title = "";
	}
}

function validateVideoDescription() {
	const videoDescField = document.getElementById("video-info-description");
	const videoDesc = videoDescField.value;
	if (videoDesc.length > 5000) {
		videoDescField.classList.add("input-error");
		videoDescField.title = "Description is too long";
	} else if (videoDesc.indexOf("<") !== -1 || videoDesc.indexOf(">") !== -1) {
		videoDescField.classList.add("input-error");
		videoDescField.title = "Description contains invalid characters";
	} else {
		videoDescField.classList.remove("input-error");
		videoDescField.title = "";
	}
}

async function submitVideo() {
	return sendVideoData(true, false);
}

async function saveVideoDraft() {
	return sendVideoData(false, false);
}

async function sendVideoData(edited, overrideChanges) {
	const submissionResponseElem = document.getElementById("submission-response");
	submissionResponseElem.classList.value = ["submission-response-pending"];
	submissionResponseElem.innerText = "Submitting video...";

	const rangesData = [];
	for (const rangeContainer of document.getElementById("range-definitions").children) {
		const rangeStart = rangeContainer.getElementsByClassName("range-definition-start")[0].value;
		const rangeEnd = rangeContainer.getElementsByClassName("range-definition-end")[0].value;
		const rangeStartSubmit = wubloaderTimeFromVideoHumanTime(rangeStart);
		const rangeEndSubmit = wubloaderTimeFromVideoHumanTime(rangeEnd);

		if (edited && (!rangeStartSubmit || !rangeEndSubmit)) {
			submissionResponseElem.classList.value = ["submission-response-error"];
			let errorMessage;
			if (!rangeStartSubmit && !rangeEndSubmit) {
				errorMessage = `The range endpoints "${rangeStartSubmit}" and "${rangeEndSubmit}" are not valid.`;
			} else if (!rangeStartSubmit) {
				errorMessage = `The range endpoint "${rangeStartSubmit} is not valid.`;
			} else {
				errorMessage = `The range endpoint "${rangeEndSubmit}" is not valid.`;
			}
			submissionResponseElem.innerText = errorMessage;
			return;
		}

		rangesData.push({
			start: rangeStartSubmit,
			end: rangeEndSubmit,
		});
	}

	const ranges = [];
	const transitions = [];
	for (const range of rangesData) {
		ranges.push([range.start, range.end]);
		// In the future, handle transitions
		transitions.push(null);
	}
	// The first range will never have a transition defined, so remove that one
	transitions.shift();

	const videoTitle = document.getElementById("video-info-title").value;
	const videoDescription = document.getElementById("video-info-description").value;
	const videoTags = document.getElementById("video-info-tags").value.split(",");
	const allowHoles = document.getElementById("advanced-submission-option-allow-holes").checked;
	const uploadLocation = document.getElementById(
		"advanced-submission-option-upload-location"
	).value;
	const uploaderAllowlistValue = document.getElementById(
		"advanced-submission-option-uploader-allow"
	).value;
	const uploaderAllowlist = uploaderAllowlistValue ? uploaderAllowlistValue.split(",") : null;
	const state = edited ? "EDITED" : "UNEDITED";

	const editData = {
		video_ranges: ranges,
		video_transitions: transitions,
		video_title: videoTitle,
		video_description: videoDescription,
		video_tags: videoTags,
		allow_holes: allowHoles,
		upload_location: uploadLocation,
		video_channel: globalStreamName,
		video_quality: videoInfo.video_quality,
		uploader_whitelist: uploaderAllowlist,
		state: state,

		// We also provide some sheet column values to verify data hasn't changed.
		sheet_name: videoInfo.sheet_name,
		event_start: videoInfo.event_start,
		event_end: videoInfo.event_end,
		category: videoInfo.category,
		description: videoInfo.description,
		notes: videoInfo.notes,
		tags: videoInfo.tags,
	};
	if (googleUser) {
		editData.token = googleUser.getAuthResponse().id_token;
	}
	if (overrideChanges) {
		editData.override_changes = true;
	}

	const submitResponse = await fetch(`/thrimshim/${videoInfo.id}`, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(editData),
	});

	if (submitResponse.ok) {
		submissionResponseElem.classList.value = ["submission-response-success"];
		if (edited) {
			submissionResponseElem.innerText = "Submitted edit";
			const submissionTimesListContainer = document.createElement("ul");
			for (const range of rangesData) {
				const submissionTimeResponse = document.createElement("li");
				const rangeStartWubloader = range.start;
				const rangeStartVideoHuman = videoHumanTimeFromWubloaderTime(rangeStartWubloader);
				const rangeEndWubloader = range.end;
				const rangeEndVideoHuman = videoHumanTimeFromWubloaderTime(rangeEndWubloader);
				submissionTimeResponse.innerText = `from ${rangeStartVideoHuman} (${rangeStartWubloader}) to ${rangeEndVideoHuman} (${rangeEndWubloader})`;
				submissionTimesListContainer.appendChild(submissionTimeResponse);
			}
			submissionResponseElem.appendChild(submissionTimesListContainer);
		} else {
			submissionResponseElem.innerText = "Saved draft";
		}
	} else {
		submissionResponseElem.classList.value = ["submission-response-error"];
		if (submitResponse.status === 409) {
			const serverErrorNode = document.createTextNode(await submitResponse.text());
			const submitButton = document.createElement("button");
			submitButton.innerText = "Submit Anyway";
			submitButton.addEventListener("click", (_event) => {
				sendVideoData(edited, true);
			});
			submissionResponseElem.innerHTML = "";
			submissionResponseElem.appendChild(serverErrorNode);
			submissionResponseElem.appendChild(submitButton);
		} else if (submitResponse.status === 401) {
			submissionResponseElem.innerText = "Unauthorized. Did you remember to sign in?";
		} else {
			submissionResponseElem.innerText = `${
				submitResponse.statusText
			}: ${await submitResponse.text()}`;
		}
	}
}

function generateDownloadURL(timeRanges, downloadType, allowHoles, quality) {
	const queryParts = [`type=${downloadType}`, `allow_holes=${allowHoles}`];
	for (const range of timeRanges) {
		let timeRangeString = "";
		if (range.hasOwnProperty("start")) {
			timeRangeString += range.start;
		}
		timeRangeString += ",";
		if (range.hasOwnProperty("end")) {
			timeRangeString += range.end;
		}
		queryParts.push(`range=${timeRangeString}`);
	}

	const downloadURL = `/cut/${globalStreamName}/${quality}.ts?${queryParts.join("&")}`;
	return downloadURL;
}

function updateDownloadLink() {
	const downloadType = document.getElementById("download-type-select").value;
	const allowHoles = document.getElementById("advanced-submission-option-allow-holes").checked;

	const timeRanges = [];
	for (const rangeContainer of document.getElementById("range-definitions").children) {
		const startField = rangeContainer.getElementsByClassName("range-definition-start")[0];
		const endField = rangeContainer.getElementsByClassName("range-definition-end")[0];
		const timeRangeData = {};
		const startTime = wubloaderTimeFromVideoHumanTime(startField.value);
		if (startTime) {
			timeRangeData.start = startTime;
		}
		const endTime = wubloaderTimeFromVideoHumanTime(endField.value);
		if (endTime) {
			timeRangeData.end = endTime;
		}
		timeRanges.push(timeRangeData);
	}

	const downloadURL = generateDownloadURL(
		timeRanges,
		downloadType,
		allowHoles,
		videoInfo.video_quality
	);
	document.getElementById("download-link").href = downloadURL;
}

async function setManualVideoLink() {
	let uploadLocation;
	if (document.getElementById("data-correction-manual-link-youtube").checked) {
		uploadLocation = "youtube-manual";
	} else {
		uploadLocation = "manual";
	}

	const link = document.getElementById("data-correction-manual-link-entry").value;

	const request = {
		link: link,
		upload_location: uploadLocation,
	};
	if (googleUser) {
		request.token = googleUser.getAuthResponse().id_token;
	}

	const responseElem = document.getElementById("data-correction-manual-link-response");
	responseElem.innerText = "Submitting link...";

	const response = await fetch(`/thrimshim/manual-link/${videoInfo.id}`, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(request),
	});

	if (response.ok) {
		responseElem.innerText = `Manual link set to ${link}`;
	} else {
		responseElem.innerText = `${response.statusText}: ${await response.text()}`;
	}
}

async function cancelVideoUpload() {
	const request = {};
	if (googleUser) {
		request.token = googleUser.getAuthResponse().id_token;
	}

	const responseElem = document.getElementById("data-correction-cancel-response");
	responseElem.innerText = "Submitting cancel request...";

	const response = await fetch(`/thrimshim/reset/${videoInfo.id}?force=false`, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(request),
	});

	if (response.ok) {
		responseElem.innerText = "Row has been cancelled. Reloading...";
		setTimeout(() => {
			window.location.reload();
		}, 1000);
	} else {
		responseElem.innerText = `${response.statusText}: ${await response.text()}`;
	}
}

async function resetVideoRow() {
	const request = {};
	if (googleUser) {
		request.token = googleUser.getAuthResponse().id_token;
	}

	const responseElem = document.getElementById("data-correction-cancel-response");
	responseElem.innerText = "Submitting reset request...";

	const response = await fetch(`/thrimshim/reset/${videoInfo.id}?force=true`, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(request),
	});

	if (response.ok) {
		responseElem.innerText = "Row has been reset. Reloading...";
		setTimeout(() => {
			window.location.reload();
		}, 1000);
	} else {
		responseElem.innerText = `${response.statusText}: ${await response.text()}`;
	}
}

function addRangeDefinition() {
	const newRangeDOM = rangeDefinitionDOM();
	const rangeContainer = document.getElementById("range-definitions");
	rangeContainer.appendChild(newRangeDOM);
}

function rangeDefinitionDOM() {
	const rangeContainer = document.createElement("div");
	rangeContainer.classList.add("range-definition-removable");
	rangeContainer.classList.add("range-definition-times");
	const rangeStart = document.createElement("input");
	rangeStart.type = "text";
	rangeStart.classList.add("range-definition-start");
	const rangeStartSet = document.createElement("img");
	rangeStartSet.src = "images/pencil.png";
	rangeStartSet.alt = "Set range start point to current video time";
	rangeStartSet.classList.add("range-definition-set-start");
	rangeStartSet.classList.add("click");
	const rangeStartPlay = document.createElement("img");
	rangeStartPlay.src = "images/play_to.png";
	rangeStartPlay.alt = "Play from start point";
	rangeStartPlay.classList.add("range-definition-play-start");
	rangeStartPlay.classList.add("click");
	const rangeTimeGap = document.createElement("div");
	rangeTimeGap.classList.add("range-definition-between-time-gap");
	const rangeEnd = document.createElement("input");
	rangeEnd.type = "text";
	rangeEnd.classList.add("range-definition-end");
	const rangeEndSet = document.createElement("img");
	rangeEndSet.src = "images/pencil.png";
	rangeEndSet.alt = "Set range end point to current video time";
	rangeEndSet.classList.add("range-definition-set-end");
	rangeEndSet.classList.add("click");
	const rangeEndPlay = document.createElement("img");
	rangeEndPlay.src = "images/play_to.png";
	rangeEndPlay.alt = "Play from end point";
	rangeEndPlay.classList.add("range-definition-play-end");
	rangeEndPlay.classList.add("click");
	const removeRange = document.createElement("img");
	removeRange.alt = "Remove range";
	removeRange.src = "images/minus.png";
	removeRange.classList.add("range-definition-remove");
	removeRange.classList.add("click");

	rangeStartSet.addEventListener("click", getRangeSetClickHandler("start"));
	rangeStartPlay.addEventListener("click", rangePlayFromStartHandler);
	rangeEndSet.addEventListener("click", getRangeSetClickHandler("end"));
	rangeEndPlay.addEventListener("click", rangePlayFromEndHandler);

	removeRange.addEventListener("click", (event) => {
		let rangeContainer = event.currentTarget;
		while (rangeContainer && !rangeContainer.classList.contains("range-definition-removable")) {
			rangeContainer = rangeContainer.parentElement;
		}
		if (rangeContainer) {
			const rangeParent = rangeContainer.parentNode;
			for (let rangeNum = 0; rangeNum < rangeParent.children.length; rangeNum++) {
				if (rangeContainer === rangeParent.children[rangeNum]) {
					if (rangeNum + 1 <= currentRange) {
						// currentRange is 1-indexed to index into DOM with querySelector
						currentRange--;
						break;
					}
				}
			}
			rangeParent.removeChild(rangeContainer);
			updateCurrentRangeIndicator();
			rangeDataUpdated();
		}
	});

	const currentRangeMarker = document.createElement("img");
	currentRangeMarker.alt = "Range affected by keyboard shortcuts";
	currentRangeMarker.title = "Range affected by keyboard shortcuts";
	currentRangeMarker.src = "images/arrow.png";
	currentRangeMarker.classList.add("range-definition-current");
	currentRangeMarker.classList.add("hidden");

	rangeContainer.appendChild(rangeStart);
	rangeContainer.appendChild(rangeStartSet);
	rangeContainer.appendChild(rangeStartPlay);
	rangeContainer.appendChild(rangeTimeGap);
	rangeContainer.appendChild(rangeEnd);
	rangeContainer.appendChild(rangeEndSet);
	rangeContainer.appendChild(rangeEndPlay);
	rangeContainer.appendChild(removeRange);
	rangeContainer.appendChild(currentRangeMarker);

	return rangeContainer;
}

function getRangeSetClickHandler(startOrEnd) {
	return (event) => {
		const setButton = event.currentTarget;
		const setField = setButton.parentElement.getElementsByClassName(
			`range-definition-${startOrEnd}`
		)[0];

		const videoElement = document.getElementById("video");
		const videoPlayerTime = videoElement.currentTime;

		setField.value = videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
		rangeDataUpdated();
	};
}

function moveToNextRange() {
	currentRange++;
	if (currentRange > document.getElementById("range-definitions").children.length) {
		addRangeDefinition();
	}
	updateCurrentRangeIndicator();
}

function moveToPreviousRange() {
	if (currentRange <= 1) {
		return;
	}

	currentRange--;
	updateCurrentRangeIndicator();
}

function updateCurrentRangeIndicator() {
	for (let arrowElem of document.getElementsByClassName("range-definition-current")) {
		arrowElem.classList.add("hidden");
	}
	document
		.querySelector(`#range-definitions > div:nth-child(${currentRange}) .range-definition-current`)
		.classList.remove("hidden");
}

function rangePlayFromStartHandler(event) {
	const playButton = event.currentTarget;
	const startField = playButton.parentElement.getElementsByClassName("range-definition-start")[0];
	const startTime = videoPlayerTimeFromVideoHumanTime(startField.value);
	if (startTime === null) {
		addError("Couldn't play from range start: failed to parse time");
		return;
	}

	const videoElement = document.getElementById("video");
	videoElement.currentTime = startTime;
}

function rangePlayFromEndHandler(event) {
	const playButton = event.currentTarget;
	const endField = playButton.parentElement.getElementsByClassName("range-definition-end")[0];
	const endTime = videoPlayerTimeFromVideoHumanTime(endField.value);
	if (endTime === null) {
		addError("Couldn't play from range end; failed to parse time");
		return;
	}

	const videoElement = document.getElementById("video");
	videoElement.currentTime = endTime;
}

function rangeDataUpdated() {
	const clipBar = document.getElementById("clip-bar");
	clipBar.innerHTML = "";

	const videoElement = document.getElementById("video");
	const videoDuration = videoElement.duration;

	for (let rangeDefinition of document.getElementById("range-definitions").children) {
		const rangeStartField = rangeDefinition.getElementsByClassName("range-definition-start")[0];
		const rangeEndField = rangeDefinition.getElementsByClassName("range-definition-end")[0];
		const rangeStart = videoPlayerTimeFromVideoHumanTime(rangeStartField.value);
		const rangeEnd = videoPlayerTimeFromVideoHumanTime(rangeEndField.value);

		if (rangeStart === null || rangeEnd === null) {
			continue;
		}

		const rangeStartPercentage = (rangeStart / videoDuration) * 100;
		const rangeEndPercentage = (rangeEnd / videoDuration) * 100;
		const widthPercentage = rangeEndPercentage - rangeStartPercentage;

		const marker = document.createElement("div");
		marker.style.width = `${widthPercentage}%`;
		marker.style.left = `${rangeStartPercentage}%`;
		clipBar.appendChild(marker);
	}
	updateDownloadLink();
}

function setCurrentRangeStartToVideoTime() {
	const rangeStartField = document.querySelector(
		`#range-definitions > div:nth-child(${currentRange}) .range-definition-start`
	);
	const videoElement = document.getElementById("video");
	rangeStartField.value = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	rangeDataUpdated();
}

function setCurrentRangeEndToVideoTime() {
	const rangeEndField = document.querySelector(
		`#range-definitions > div:nth-child(${currentRange}) .range-definition-end`
	);
	const videoElement = document.getElementById("video");
	rangeEndField.value = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	rangeDataUpdated();
}

function videoPlayerTimeFromWubloaderTime(wubloaderTime) {
	const wubloaderDateTime = dateTimeFromWubloaderTime(wubloaderTime);
	const segmentList = getSegmentList();
	for (const segment of segmentList) {
		const segmentStart = DateTime.fromISO(segment.rawProgramDateTime, { zone: "utc" });
		const segmentEnd = segmentStart.plus({ seconds: segment.duration });
		if (segmentStart <= wubloaderDateTime && segmentEnd > wubloaderDateTime) {
			return segment.start + wubloaderDateTime.diff(segmentStart).as("seconds");
		}
	}
	return null;
}

function dateTimeFromVideoPlayerTime(videoPlayerTime) {
	const segmentList = getSegmentList();
	let segmentStartTime;
	let segmentStartISOTime;
	for (const segment of segmentList) {
		const segmentEndTime = segment.start + segment.duration;
		if (videoPlayerTime >= segment.start && videoPlayerTime < segmentEndTime) {
			segmentStartTime = segment.start;
			segmentStartISOTime = segment.rawProgramDateTime;
			break;
		}
	}
	if (segmentStartISOTime === undefined) {
		return null;
	}
	const wubloaderDateTime = DateTime.fromISO(segmentStartISOTime);
	const offset = videoPlayerTime - segmentStartTime;
	return wubloaderDateTime.plus({ seconds: offset });
}

function wubloaderTimeFromVideoPlayerTime(videoPlayerTime) {
	const dt = dateTimeFromVideoPlayerTime(videoPlayerTime);
	return wubloaderTimeFromDateTime(dt);
}

function videoHumanTimeFromVideoPlayerTime(videoPlayerTime) {
	const minutes = Math.floor(videoPlayerTime / 60);
	let seconds = Math.floor(videoPlayerTime % 60);
	let milliseconds = Math.floor((videoPlayerTime * 1000) % 1000);

	while (seconds.toString().length < 2) {
		seconds = `0${seconds}`;
	}
	while (milliseconds.toString().length < 3) {
		milliseconds = `0${milliseconds}`;
	}

	return `${minutes}:${seconds}.${milliseconds}`;
}

function videoPlayerTimeFromVideoHumanTime(videoHumanTime) {
	let timeParts = videoHumanTime.split(":", 2);
	let minutes;
	let seconds;

	if (timeParts.length < 2) {
		minutes = 0;
		seconds = +timeParts[0];
	} else {
		minutes = parseInt(timeParts[0]);
		seconds = +timeParts[1];
	}
	if (isNaN(minutes) || isNaN(seconds)) {
		return null;
	}

	return minutes * 60 + seconds;
}

function videoHumanTimeFromWubloaderTime(wubloaderTime) {
	const videoPlayerTime = videoPlayerTimeFromWubloaderTime(wubloaderTime);
	return videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
}

function wubloaderTimeFromVideoHumanTime(videoHumanTime) {
	const videoPlayerTime = videoPlayerTimeFromVideoHumanTime(videoHumanTime);
	if (videoPlayerTime === null) {
		return null;
	}
	return wubloaderTimeFromVideoPlayerTime(videoPlayerTime);
}

function getSegmentList() {
	return globalPlayer.latencyController.levelDetails.fragments;
}
