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
		const newStart = dateObjFromInputTime(newStartField.value);
		if (!newStart) {
			addError("Failed to parse start time");
			return;
		}

		const newEndField = document.getElementById("stream-time-setting-end");
		let newEnd = null;
		if (newEndField.value !== "") {
			newEnd = dateObjFromInputTime(newEndField.value);
			if (!newEnd) {
				addError("Failed to parse end time");
				return;
			}
		}

		const oldStart = getStartTime();
		const startAdjustment = newStart - oldStart;
		const newDuration = newEnd === null ? Infinity : newEnd - newStart;

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

		globalStartTimeString = getWubloaderTimeFromDateWithMilliseconds(newStart);
		globalEndTimeString = getWubloaderTimeFromDateWithMilliseconds(newEnd);

		updateSegmentPlaylist();

		for (const rangeContainer of document.getElementById("range-definitions").children) {
			const rangeStartField = rangeContainer.getElementsByClassName("range-definition-start")[0];
			const rangeEndField = rangeContainer.getElementsByClassName("range-definition-end")[0];

			const rangeStart = videoPlayerTimeFromVideoHumanTime(rangeStartField.value);
			if (rangeStart !== null) {
				rangeStartField.value = videoHumanTimeFromVideoPlayerTime(startAdjustment + rangeStart);
			}

			const rangeEnd = videoPlayerTimeFromVideoHumanTime(rangeEndField.value);
			if (rangeEnd !== null) {
				rangeEndField.value = videoHumanTimeFromVideoPlayerTime(startAdjustment + rangeEnd);
			}
		}

		const waveformImage = document.getElementById("waveform");
		if (newEnd === null) {
			waveformImage.classList.add("hidden");
		} else {
			updateWaveform();
			waveformImage.classList.remove("hidden");
		}
	});

	await loadVideoInfo();

	updateDownloadLink();

	document.getElementById("stream-time-setting-start-pad").addEventListener("click", (_event) => {
		const startTimeField = document.getElementById("stream-time-setting-start");
		let startTime = startTimeField.value;
		startTime = parseInputTimeAsNumberOfSeconds(startTime);
		if (isNaN(startTime)) {
			addError("Couldn't parse entered start time for padding");
			return;
		}
		startTime -= 60;
		const startTimeDate = new Date(globalBusStartTime);
		startTimeDate.setSeconds(startTimeDate.getSeconds() + startTime);
		startTime = getBusTimeFromDateObj(startTimeDate);
		startTimeField.value = startTime;
	});

	document.getElementById("stream-time-setting-end-pad").addEventListener("click", (_event) => {
		const endTimeField = document.getElementById("stream-time-setting-end");
		let endTime = endTimeField.value;
		endTime = parseInputTimeAsNumberOfSeconds(endTime);
		if (isNaN(endTime)) {
			addError("Couldn't parse entered end time for padding");
			return;
		}
		endTime += 60;
		const endTimeDate = new Date(globalBusStartTime);
		endTimeDate.setSeconds(endTimeDate.getSeconds() + endTime);
		endTime = getBusTimeFromDateObj(endTimeDate);
		endTimeField.value = endTime;
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
	globalBusStartTime = new Date(videoInfo.bustime_start);

	const eventStartTime = dateObjFromWubloaderTime(videoInfo.event_start);
	const eventEndTime = videoInfo.event_end ? dateObjFromWubloaderTime(videoInfo.event_end) : null;

	// To account for various things (stream delay, just slightly off logging, etc.), we pad the start time by one minute
	eventStartTime.setMinutes(eventStartTime.getMinutes() - 1);

	// To account for various things (stream delay, just slightly off logging, etc.), we pad the end time by one minute.
	// To account for the fact that we don't record seconds, but the event could've ended any time in the recorded minute, we pad by an additional minute.
	if (eventEndTime) {
		eventEndTime.setMinutes(eventEndTime.getMinutes() + 2);
	}

	globalStartTimeString = getWubloaderTimeFromDateWithMilliseconds(eventStartTime);
	if (eventEndTime) {
		globalEndTimeString = getWubloaderTimeFromDateWithMilliseconds(eventEndTime);
	} else {
		document.getElementById("waveform").classList.add("hidden");
	}

	// If a video was previously edited to points outside the video range, we should expand the loaded video to include the edited range
	if (videoInfo.video_start) {
		const videoStartTime = dateObjFromWubloaderTime(videoInfo.video_start);
		if (videoStartTime < eventStartTime) {
			videoStartTime.setMinutes(videoStartTime.getMinutes() - 1);
			globalStartTimeString = getWubloaderTimeFromDateWithMilliseconds(videoStartTime);
		}
	}

	if (videoInfo.video_end) {
		const videoEndTime = dateObjFromWubloaderTime(videoInfo.video_end);
		if (eventEndTime && videoEndTime > eventEndTime) {
			// If we're getting the time from a previous draft edit, we don't need to pad as hard on the end
			videoEndTime.setMinutes(videoEndTime.getMinutes() + 1);
			globalEndTimeString = getWubloaderTimeFromDateWithMilliseconds(videoEndTime);
		}
	}

	document.getElementById("stream-time-setting-stream").innerText = globalStreamName;
	document.getElementById("stream-time-setting-start").value =
		getBusTimeFromTimeString(globalStartTimeString);
	document.getElementById("stream-time-setting-end").value =
		getBusTimeFromTimeString(globalEndTimeString);

	updateWaveform();

	const titlePrefixElem = document.getElementById("video-info-title-prefix");
	titlePrefixElem.innerText = videoInfo.title_prefix;

	const titleElem = document.getElementById("video-info-title");
	if (videoInfo.video_title) {
		titleElem.value = videoInfo.video_title;
	} else {
		titleElem.value = videoInfo.description;
	}

	const descriptionElem = document.getElementById("video-info-description");
	if (videoInfo.video_description) {
		descriptionElem.value = videoInfo.video_description;
	} else {
		descriptionElem.value = videoInfo.description;
	}

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

	const player = getVideoJS();
	player.on("loadedmetadata", () => {
		// For now, there's only one range in the data we receive from thrimshim, so we'll populate that as-is here.
		// This will need to be updated when thrimshim supports multiple video ranges.
		const rangeDefinitionsContainer = document.getElementById("range-definitions");
		const rangeDefinitionStart =
			rangeDefinitionsContainer.getElementsByClassName("range-definition-start")[0];
		const rangeDefinitionEnd =
			rangeDefinitionsContainer.getElementsByClassName("range-definition-end")[0];
		rangeDefinitionStart.addEventListener("change", (_event) => {
			rangeDataUpdated();
		});
		rangeDefinitionEnd.addEventListener("change", (_event) => {
			rangeDataUpdated();
		});
		if (videoInfo.video_start) {
			rangeDefinitionStart.value = videoHumanTimeFromWubloaderTime(videoInfo.video_start);
		} else {
			rangeDefinitionStart.value = videoHumanTimeFromVideoPlayerTime(0);
		}
		if (videoInfo.video_end) {
			rangeDefinitionEnd.value = videoHumanTimeFromWubloaderTime(videoInfo.video_end);
		} else if (videoInfo.event_end) {
			const player = getVideoJS();
			rangeDefinitionEnd.value = videoHumanTimeFromVideoPlayerTime(player.duration());
		}
		if (videoInfo.video_end || videoInfo.event_end) {
			rangeDataUpdated();
		}
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
	return dateObjFromWubloaderTime(globalStartTimeString);
}

function getEndTime() {
	if (!globalEndTimeString) {
		return null;
	}
	return dateObjFromWubloaderTime(globalEndTimeString);
}

function getBusTimeFromTimeString(timeString) {
	if (timeString === "") {
		return "";
	}
	const time = dateObjFromWubloaderTime(timeString);
	return getBusTimeFromDateObj(time);
}

function getBusTimeFromDateObj(time) {
	const busTimeMilliseconds = time - globalBusStartTime;
	let remainingBusTimeSeconds = busTimeMilliseconds / 1000;

	let sign = "";
	if (remainingBusTimeSeconds < 0) {
		sign = "-";
		remainingBusTimeSeconds = Math.abs(remainingBusTimeSeconds);
	}

	const hours = Math.floor(remainingBusTimeSeconds / 3600);
	remainingBusTimeSeconds %= 3600;
	let minutes = Math.floor(remainingBusTimeSeconds / 60);
	let seconds = remainingBusTimeSeconds % 60;
	let milliseconds = Math.round((seconds % 1) * 1000);
	seconds = Math.trunc(seconds);

	while (minutes.toString().length < 2) {
		minutes = `0${minutes}`;
	}
	while (seconds.toString().length < 2) {
		seconds = `0${seconds}`;
	}

	if (milliseconds > 0) {
		while (milliseconds.toString().length < 3) {
			milliseconds = `0${milliseconds}`;
		}
		return `${sign}${hours}:${minutes}:${seconds}.${milliseconds}`;
	}

	return `${sign}${hours}:${minutes}:${seconds}`;
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

		let transitionType = rangeContainer.getElementsByClassName("range-definition-transition-type");
		let transitionDuration = rangeContainer.getElementsByClassName(
			"range-definition-transition-duration"
		);
		if (transitionType.length > 0 && transitionDuration.length > 0) {
			transitionType = transitionType[0].value;
			transitionDuration = transitionDuration[0].value;

			if (edited && transitionType !== "" && transitionDuration === "") {
				submissionResponseElem.classList.value = ["submission-response-error"];
				submissionResponseElem.innerText = "A non-cut transition was specified with no duration";
				return;
			}
		} else {
			transitionType = null;
			transitionDuration = null;
		}

		rangesData.push({
			start: rangeStartSubmit,
			end: rangeEndSubmit,
			transition: transitionType,
			duration: transitionDuration,
		});
	}

	// Currently this only supports one range. When multiple ranges are supported, expand this.
	const videoStart = rangesData[0].start;
	const videoEnd = rangesData[0].end;
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
		video_start: videoStart,
		video_end: videoEnd,
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
		editData.overrideChanges = true;
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
			submissionResponseElem.innerText = `Submitted edit from ${videoStart} to ${videoEnd}`;
		} else {
			submissionResponseElem.innerText = "Saved draft";
		}
	} else {
		submissionResponseElem.classList.value = ["submission-response-error"];
		if (submitResponse.status === 409) {
			const serverErrorNode = document.createTextNode(await submitResponse.text());
			const submitButton = document.createElement("button");
			submitButton.text = "Submit Anyway";
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

function updateDownloadLink() {
	// Currently this only supports one range. When download links can download multiple ranges, this should be updated.
	const firstRangeStartField = document.getElementsByClassName("range-definition-start")[0];
	const firstRangeEndField = document.getElementsByClassName("range-definition-end")[0];

	const startTime = firstRangeStartField.value
		? wubloaderTimeFromVideoHumanTime(firstRangeStartField.value)
		: getStartTime();
	const endTime = firstRangeEndField.value
		? wubloaderTimeFromVideoHumanTime(firstRangeEndField.value)
		: getEndTime();

	const downloadType = document.getElementById("download-type-select").value;
	const allowHoles = document.getElementById("advanced-submission-option-allow-holes").checked;

	const downloadURL = generateDownloadURL(
		startTime,
		endTime,
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

const RANGE_TRANSITION_TYPES = [
	"fade",
	"wipeleft",
	"wiperight",
	"wipeup",
	"wipedown",
	"slideleft",
	"slideright",
	"slideup",
	"slidedown",
	"circlecrop",
	"rectcrop",
	"distance",
	"fadeblack",
	"fadewhite",
	"radial",
	"smoothleft",
	"smoothright",
	"smoothup",
	"smoothdown",
	"circleopen",
	"circleclose",
	"vertopen",
	"vertclose",
	"horzopen",
	"horzclose",
	"dissolve",
	"pixelize",
	"diagtl",
	"diagtr",
	"diagbl",
	"diagbr",
	"hlslice",
	"hrslice",
	"vuslice",
	"vdslice",
	"hblur",
	"fadegrays",
	"wipetl",
	"wipetr",
	"wipebl",
	"wipebr",
	"squeezeh",
	"squeezev",
];

function rangeDefinitionDOM() {
	const container = document.createElement("div");
	container.classList.add("range-definition-removable");

	const transitionContainer = document.createElement("div");
	transitionContainer.classList.add("range-definition-transition");

	const transitionSelection = document.createElement("select");
	transitionSelection.classList.add("range-definition-transition-type");
	const noTransitionOption = document.createElement("option");
	noTransitionOption.value = "";
	noTransitionOption.innerText = "No transition (hard cut)";
	transitionSelection.appendChild(noTransitionOption);
	for (transitionType of RANGE_TRANSITION_TYPES) {
		const transitionOption = document.createElement("option");
		transitionOption.value = transitionType;
		transitionOption.innerText = transitionType;
		transitionSelection.appendChild(transitionOption);
	}
	transitionSelection.addEventListener("change", (_event) => {
		rangeDataUpdated();
	});
	transitionContainer.appendChild(transitionSelection);

	const transitionDurationInput = document.createElement("input");
	transitionDurationInput.type = "number";
	transitionDurationInput.min = 0;
	transitionDurationInput.step = "any";
	transitionDurationInput.placeholder = "Duration (seconds)";
	transitionDurationInput.classList.add("range-definition-transition-duration");
	transitionContainer.appendChild(transitionDurationInput);

	container.appendChild(transitionContainer);

	const rangeContainer = document.createElement("div");
	rangeContainer.classList.add("range-definition-times");
	const rangeStart = document.createElement("input");
	rangeStart.type = "text";
	rangeStart.classList.add("range-definition-start");
	const rangeStartSet = document.createElement("img");
	rangeStartSet.src = "images/pencil.png";
	rangeStartSet.alt = "Set range start point to current video time";
	rangeStartSet.classList.add("range-definition-set-start");
	rangeStartSet.classList.add("click");
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
	const removeRange = document.createElement("img");
	removeRange.alt = "Remove range";
	removeRange.src = "images/minus.png";
	removeRange.classList.add("range-definition-remove");
	removeRange.classList.add("click");

	rangeStartSet.addEventListener("click", getRangeSetClickHandler("start"));

	rangeEndSet.addEventListener("click", getRangeSetClickHandler("end"));

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
	rangeContainer.appendChild(rangeTimeGap);
	rangeContainer.appendChild(rangeEnd);
	rangeContainer.appendChild(rangeEndSet);
	rangeContainer.appendChild(removeRange);
	rangeContainer.appendChild(currentRangeMarker);

	container.appendChild(rangeContainer);

	return container;
}

function getRangeSetClickHandler(startOrEnd) {
	return function (event) {
		const setButton = event.currentTarget;
		const setField = setButton.parentElement.getElementsByClassName(
			`range-definition-${startOrEnd}`
		)[0];

		const player = getVideoJS();
		const videoPlayerTime = player.currentTime();

		setField.value = videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
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

function rangeDataUpdated() {
	const clipBar = document.getElementById("clip-bar");
	clipBar.innerHTML = "";

	const player = getVideoJS();
	const videoDuration = player.duration();

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
	const player = getVideoJS();
	rangeStartField.value = videoHumanTimeFromVideoPlayerTime(player.currentTime());
	rangeDataUpdated();
}

function setCurrentRangeEndToVideoTime() {
	const rangeEndField = document.querySelector(
		`#range-definitions > div:nth-child(${currentRange}) .range-definition-end`
	);
	const player = getVideoJS();
	rangeEndField.value = videoHumanTimeFromVideoPlayerTime(player.currentTime());
	rangeDataUpdated();
}

function videoPlayerTimeFromWubloaderTime(wubloaderTime) {
	const videoPlaylist = getPlaylistData();
	const wubloaderDateObj = dateObjFromWubloaderTime(wubloaderTime);
	let highestDiscontinuitySegmentBefore = 0;
	for (start of videoPlaylist.discontinuityStarts) {
		const discontinuityStartSegment = videoPlaylist.segments[start];
		if (
			discontinuityStartSegment.dateTimeObject < wubloaderDateObj &&
			discontinuityStartSegment.dateTimeObject >
				videoPlaylist.segments[highestDiscontinuitySegmentBefore].dateTimeObject
		) {
			highestDiscontinuitySegmentBefore = start;
		}
	}

	let highestDiscontinuitySegmentStart = 0;
	for (let segment = 0; segment < highestDiscontinuitySegmentBefore; segment++) {
		highestDiscontinuitySegmentStart += videoPlaylist.segments[segment].duration;
	}
	return (
		highestDiscontinuitySegmentStart +
		secondsDifference(
			videoPlaylist.segments[highestDiscontinuitySegmentBefore].dateTimeObject,
			wubloaderDateObj
		)
	);
}

function wubloaderTimeFromVideoPlayerTime(videoPlayerTime) {
	const videoPlaylist = getPlaylistData();
	let segmentStartTime = 0;
	let segmentDateObj;
	// Segments have start and end video player times on them, but only if the segments are already loaded.
	// This is not the case before the video is loaded for the first time, or outside the video's buffer if it hasn't played that far/part.
	for (segment of videoPlaylist.segments) {
		const segmentEndTime = segmentStartTime + segment.duration;
		if (segmentStartTime <= videoPlayerTime && segmentEndTime > videoPlayerTime) {
			segmentDateObj = segment.dateTimeObject;
			break;
		}
		segmentStartTime = segmentEndTime;
	}
	if (segmentDateObj === undefined) {
		return null;
	}
	let wubloaderDateObj = new Date(segmentDateObj);
	const offset = videoPlayerTime - segmentStartTime;
	const offsetMilliseconds = offset * 1000;
	wubloaderDateObj.setMilliseconds(wubloaderDateObj.getMilliseconds() + offsetMilliseconds);
	return wubloaderDateObj;
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

function dateObjFromInputTime(inputTime) {
	const inputSeconds = parseInputTimeAsNumberOfSeconds(inputTime);
	if (isNaN(inputSeconds)) {
		return null;
	}
	return new Date(globalBusStartTime.getTime() + 1000 * inputSeconds);
}

function getPlaylistData() {
	const player = getVideoJS();
	// Currently, this only supports a single playlist. We only give one playlist (or master playlist file) to VideoJS,
	// so this should be fine for now. If we need to support multiple playlists in the future (varying quality levels,
	// etc.), this and all callers will need to be updated.
	return player.tech("OK").vhs.playlists.master.playlists[0];
}

function secondsDifference(date1, date2) {
	if (date2 > date1) {
		return (date2 - date1) / 1000;
	}
	return (date1 - date2) / 1000;
}
