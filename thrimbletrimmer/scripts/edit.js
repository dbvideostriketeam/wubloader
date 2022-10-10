var googleUser = null;
var videoInfo;
var currentRange = 1;

const CHAPTER_MARKER_DELIMITER = "\n==========\n";
const CHAPTER_MARKER_DELIMITER_PARTIAL = "==========";

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

		const rangesData = [];
		const rangeDefinitionsElements = document.getElementById("range-definitions").children;
		for (const rangeContainer of rangeDefinitionsElements) {
			const rangeStartField = rangeContainer.getElementsByClassName("range-definition-start")[0];
			const rangeEndField = rangeContainer.getElementsByClassName("range-definition-end")[0];

			const rangeStartTimeString = rangeStartField.value;
			const rangeEndTimeString = rangeEndField.value;

			const rangeStartTime = dateTimeFromVideoHumanTime(rangeStartTimeString);
			const rangeEndTime = dateTimeFromVideoHumanTime(rangeEndTimeString);

			rangesData.push({ start: rangeStartTime, end: rangeEndTime });
		}

		const videoElement = document.getElementById("video");
		const currentVideoPosition = dateTimeFromVideoPlayerTime(videoElement.currentTime);

		globalStartTimeString = wubloaderTimeFromDateTime(newStart);
		globalEndTimeString = wubloaderTimeFromDateTime(newEnd);

		updateSegmentPlaylist();

		globalPlayer.once(Hls.Events.LEVEL_LOADED, (_data) => {
			const newVideoPosition = videoPlayerTimeFromDateTime(currentVideoPosition);
			if (newVideoPosition !== null) {
				videoElement.currentTime = newVideoPosition;
			}

			let rangeErrorCount = 0;
			for (const [rangeIndex, rangeData] of rangesData.entries()) {
				const rangeContainer = rangeDefinitionsElements[rangeIndex];
				const rangeStartField = rangeContainer.getElementsByClassName("range-definition-start")[0];
				const rangeEndField = rangeContainer.getElementsByClassName("range-definition-end")[0];

				if (rangeData.start) {
					rangeStartField.value = videoHumanTimeFromDateTime(rangeData.start);
				} else {
					rangeErrorCount++;
				}

				if (rangeData.end) {
					rangeEndField.value = videoHumanTimeFromDateTime(rangeData.end);
				} else {
					rangeErrorCount++;
				}
			}
			if (rangeErrorCount > 0) {
				addError(
					"Some ranges couldn't be updated for the new video time endpoints. Please verify the time range values."
				);
			}

			rangeDataUpdated();
		});

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

	const enableChaptersElem = document.getElementById("enable-chapter-markers");
	enableChaptersElem.addEventListener("change", (_event) => {
		changeEnableChaptersHandler();
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
	for (const addChapterMarker of document.getElementsByClassName(
		"add-range-definition-chapter-marker"
	)) {
		addChapterMarker.addEventListener("click", addChapterMarkerHandler);
	}

	document.getElementById("video-info-title").addEventListener("input", (_event) => {
		validateVideoTitle();
	});
	document.getElementById("video-info-description").addEventListener("input", (_event) => {
		validateVideoDescription();
	});
	document.getElementById("video-info-thumbnail-mode").addEventListener("change", () => {
		const newValue = document.getElementById("video-info-thumbnail-mode").value;
		const unhideIDs = [];

		if (newValue === "BARE") {
			unhideIDs.push("video-info-thumbnail-time-options");
		} else if (newValue === "TEMPLATE") {
			unhideIDs.push("video-info-thumbnail-template-options");
			unhideIDs.push("video-info-thumbnail-time-options");
		} else if (newValue === "CUSTOM") {
			unhideIDs.push("video-info-thumbnail-custom-options");
		}

		document.getElementsByClassName("video-info-thumbnail-mode-options").classList.add("hidden");
		for (elemID of unhideIDs) {
			document.getElementById(elemID).classList.remove("hidden");
		}
	});
	document.getElementById("video-info-thumbnail-time-set").addEventListener("click", (_event) => {
		const field = document.getElementById("video-info-thumbnail-time");
		const videoPlayer = document.getElementById("video");
		const videoPlayerTime = videoPlayer.currentTime;
		field.value = videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
	});
	document.getElementById("video-info-thumbnail-time-play").addEventListener("click", (_event) => {
		const field = document.getElementById("video-info-thumbnail-time");
		const thumbnailTime = videoPlayerTimeFromVideoHumanTime(field.value);
		if (thumbnailTime === null) {
			addError("Couldn't play from thumbnail frame; failed to parse time");
			return;
		}
		const videoPlayer = document.getElementById("video");
		videoPlayer.currentTime = thumbnailTime;
	});
	const thumbnailTemplateSelection = document.getElementById("video-info-thumbnail-template");
	const thumbnailTemplatesListResponse = await fetch("/files/thumbnail_templates");
	if (thumbnailTemplatesListResponse.ok) {
		const thumbnailTemplatesList = await thumbnailTemplatesListResponse.json();
		for (const templateFileName of thumbnailTemplatesList) {
			const templateOption = document.createElement("option");
			const templateName = templateFileName.substring(0, templateFileName.lastIndexOf("."));
			templateOption.innerText = templateName;
			templateOption.value = templateName;
			if (templateName === videoInfo.thumbnail_template) {
				templateOption.selected = true;
			}
			thumbnailTemplateSelection.appendChild(templateOption);
		}
	} else {
		addError("Failed to load thumbnail templates list");
	}
	document.getElementById("video-info-thumbnail-mode").value = videoInfo.thumbnail_mode;
	if (videoInfo.thumbnail_time) {
		document.getElementById("video-info-thumbnail-time").value = videoHumanTimeFromWubloaderTime(
			videoInfo.thumbnail_time
		);
	}

	document.getElementById("submit-button").addEventListener("click", (_event) => {
		submitVideo();
	});
	document.getElementById("save-button").addEventListener("click", (_event) => {
		saveVideoDraft();
	});
	document.getElementById("submit-changes-button").addEventListener("click", (_event) => {
		submitVideoChanges();
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

	document.getElementById("download-frame").addEventListener("click", (_event) => {
		downloadFrame();
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

		if (latestEndTime && eventEndTime && latestEndTime.diff(eventEndTime).milliseconds > 0) {
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

	const unlistedCheckbox = document.getElementById("advanced-submission-option-unlisted");
	unlistedCheckbox.checked = !videoInfo.public;
	if (!videoInfo.public) {
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

	if (videoInfo.state === "DONE") {
		const submitButton = document.getElementById("submit-button");
		submitButton.classList.add("hidden");
		const saveButton = document.getElementById("save-button");
		saveButton.classList.add("hidden");
		const submitChangesButton = document.getElementById("submit-changes-button");
		submitChangesButton.classList.remove("hidden");
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
			const chapterData = [];
			const descriptionField = document.getElementById("video-info-description");
			let description = descriptionField.value;
			if (description.indexOf(CHAPTER_MARKER_DELIMITER) !== -1) {
				enableChapterMarkers(true);
				const descriptionParts = description.split(CHAPTER_MARKER_DELIMITER, 2);
				description = descriptionParts[0];
				const chapterLines = descriptionParts[1].split("\n");
				for (const chapterLine of chapterLines) {
					const chapterLineData = chapterLine.split(" - ");
					const chapterTime = unformatChapterTime(chapterLineData.shift());
					const chapterDescription = chapterLineData.join(" - ");
					chapterData.push({ start: chapterTime, description: chapterDescription });
				}
			}

			let currentChapterIndex = 0;
			let canAddChapters = true;
			let rangeStartOffset = 0;
			for (let rangeIndex = 0; rangeIndex < videoInfo.video_ranges.length; rangeIndex++) {
				if (rangeIndex >= rangeDefinitionsContainer.children.length) {
					addRangeDefinition();
				}
				const startWubloaderTime = videoInfo.video_ranges[rangeIndex][0];
				const endWubloaderTime = videoInfo.video_ranges[rangeIndex][1];
				const startPlayerTime = videoPlayerTimeFromWubloaderTime(startWubloaderTime);
				const endPlayerTime = videoPlayerTimeFromWubloaderTime(endWubloaderTime);
				if (startWubloaderTime) {
					const startField =
						rangeDefinitionsContainer.children[rangeIndex].getElementsByClassName(
							"range-definition-start"
						)[0];
					startField.value = videoHumanTimeFromVideoPlayerTime(startPlayerTime);
				}
				if (endWubloaderTime) {
					const endField =
						rangeDefinitionsContainer.children[rangeIndex].getElementsByClassName(
							"range-definition-end"
						)[0];
					endField.value = videoHumanTimeFromVideoPlayerTime(endPlayerTime);
				}

				const rangeDuration = endPlayerTime - startPlayerTime;
				const rangeEndVideoTime = rangeStartOffset + rangeDuration;
				if (canAddChapters && startWubloaderTime && endWubloaderTime) {
					const chapterContainer = rangeDefinitionsContainer.children[
						rangeIndex
					].getElementsByClassName("range-definition-chapter-markers")[0];
					while (
						currentChapterIndex < chapterData.length &&
						chapterData[currentChapterIndex].start < rangeEndVideoTime
					) {
						const chapterMarker = chapterMarkerDefinitionDOM();
						const chapterStartField = chapterMarker.getElementsByClassName(
							"range-definition-chapter-marker-start"
						)[0];
						chapterStartField.value = videoHumanTimeFromVideoPlayerTime(
							chapterData[currentChapterIndex].start - rangeStartOffset + startPlayerTime
						);
						const chapterDescField = chapterMarker.getElementsByClassName(
							"range-definition-chapter-marker-description"
						)[0];
						chapterDescField.value = chapterData[currentChapterIndex].description;
						chapterContainer.appendChild(chapterMarker);
						currentChapterIndex++;
					}
				} else {
					canAddChapters = false;
				}
				rangeStartOffset = rangeEndVideoTime;
			}
			if (canAddChapters) {
				descriptionField.value = description;
				validateVideoDescription();
			}
		} else {
			const rangeStartField =
				rangeDefinitionsContainer.getElementsByClassName("range-definition-start")[0];
			rangeStartField.value = videoHumanTimeFromWubloaderTime(globalStartTimeString);
			rangeStartField.dataset.oldTime = rangeStartField.value;
			if (globalEndTimeString) {
				const rangeEndField =
					rangeDefinitionsContainer.getElementsByClassName("range-definition-end")[0];
				rangeEndField.value = videoHumanTimeFromWubloaderTime(globalEndTimeString);
			}
		}
		rangeDataUpdated();
		videoElement.removeEventListener("loadedmetadata", handleInitialSetupForDuration);
	};
	videoElement.addEventListener("loadedmetadata", handleInitialSetupForDuration);
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
	let waveformURL =
		"/waveform/" + globalStreamName + "/" + videoInfo.video_quality + ".png?size=1920x125&";

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
	} else if (videoDesc.indexOf(CHAPTER_MARKER_DELIMITER) !== -1) {
		videoDescField.classList.add("input-error");
		videoDescField.title = "Description contains a manual chapter marker";
	} else {
		videoDescField.classList.remove("input-error");
		videoDescField.title = "";
	}
}

async function submitVideo() {
	const enableChaptersElem = document.getElementById("enable-chapter-markers");
	const chapterStartFieldList = document.getElementsByClassName("range-definition-chapter-time");
	if (enableChaptersElem.checked && chapterStartFieldList.length > 0) {
		const firstRangeStartElem = document.getElementsByClassName("range-definition-start")[0];
		const firstRangeStart = videoPlayerTimeFromMVideoHumanTime(firstRangeStartElem.value);

		const firstChapterStartField = chapterStartFieldList[0];
		const firstChapterStart = videoPlayerTimeFromVideoHumanTime(firstChapterStartField.value);

		if (firstRangeStart !== firstChapterStart) {
			addError("The first chapter marker must be at the beginning of the video");
			return;
		}
	}

	return sendVideoData("EDITED", false);
}

async function saveVideoDraft() {
	return sendVideoData("UNEDITED", false);
}

async function submitVideoChanges() {
	return sendVideoData("MODIFIED", false);
}

async function sendVideoData(newState, overrideChanges) {
	let videoDescription = document.getElementById("video-info-description").value;
	if (videoDescription.indexOf(CHAPTER_MARKER_DELIMITER_PARTIAL) !== -1) {
		addError(
			"Couldn't submit edits: Description contains manually entered chapter marker delimiter"
		);
		return;
	}

	const edited = newState === "EDITED";

	const submissionResponseElem = document.getElementById("submission-response");
	submissionResponseElem.classList.value = ["submission-response-pending"];
	submissionResponseElem.innerText = "Submitting video...";
	window.addEventListener("beforeunload", handleLeavePageWhilePending);

	const rangesData = [];
	const chaptersData = [];
	const chaptersEnabled = document.getElementById("enable-chapter-markers").checked;
	let rangeStartInFinalVideo = 0;
	for (const rangeContainer of document.getElementById("range-definitions").children) {
		const rangeStartHuman =
			rangeContainer.getElementsByClassName("range-definition-start")[0].value;
		const rangeEndHuman = rangeContainer.getElementsByClassName("range-definition-end")[0].value;
		const rangeStartPlayer = videoPlayerTimeFromVideoHumanTime(rangeStartHuman);
		const rangeEndPlayer = videoPlayerTimeFromVideoHumanTime(rangeEndHuman);
		const rangeStartSubmit = wubloaderTimeFromVideoPlayerTime(rangeStartPlayer);
		const rangeEndSubmit = wubloaderTimeFromVideoPlayerTime(rangeEndPlayer);

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

		if (edited && rangeEndPlayer < rangeStartPlayer) {
			submissionResponseElem.innerText =
				"One or more ranges has an end time prior to its start time.";
			submissionResponseElem.classList.value = ["submission-response-error"];
			return;
		}

		rangesData.push({
			start: rangeStartSubmit,
			end: rangeEndSubmit,
		});

		if (chaptersEnabled && rangeStartSubmit && rangeEndSubmit) {
			for (const chapterContainer of rangeContainer.getElementsByClassName(
				"range-definition-chapter-markers"
			)[0].children) {
				const startField = chapterContainer.getElementsByClassName(
					"range-definition-chapter-marker-start"
				)[0];
				const descField = chapterContainer.getElementsByClassName(
					"range-definition-chapter-marker-description"
				)[0];

				const startFieldTime = videoPlayerTimeFromVideoHumanTime(startField.value);
				if (startFieldTime === null) {
					if (edited) {
						submissionResponseElem.innerText = `Unable to parse chapter start time: ${startField.value}`;
						submissionResponseElem.classList.value = ["submission-response-error"];
						return;
					}
					continue;
				}
				if (startFieldTime < rangeStartPlayer || startFieldTime > rangeEndPlayer) {
					submissionResponseElem.innerText = `The chapter at "${startField.value}" is outside its containing time range.`;
					submissionResponseElem.classList.value = ["submission-response-error"];
					return;
				}
				const chapterStartTime = rangeStartInFinalVideo + startFieldTime - rangeStartPlayer;
				const chapterData = {
					start: chapterStartTime,
					description: descField.value,
				};
				chaptersData.push(chapterData);
			}
		} else {
			const enableChaptersElem = document.getElementById("enable-chapter-markers");
			if (
				enableChaptersElem.checked &&
				rangeContainer.getElementsByClassName("range-definition-chapter-marker-start").length > 0
			) {
				submissionResponseElem.classList.value = ["submission-response-error"];
				submissionResponseElem.innerText =
					"Chapter markers can't be saved for ranges without valid endpoints.";
				return;
			}
		}
		rangeStartInFinalVideo += rangeEndPlayer - rangeStartPlayer;
	}
	const finalVideoDuration = rangeStartInFinalVideo;
	const videoHasHours = finalVideoDuration >= 3600;

	const ranges = [];
	const transitions = [];
	for (const range of rangesData) {
		ranges.push([range.start, range.end]);
		// In the future, handle transitions
		transitions.push(null);
	}
	// The first range will never have a transition defined, so remove that one
	transitions.shift();

	if (chaptersData.length > 0) {
		if (chaptersData[0].start !== 0) {
			submissionResponseElem.innerText =
				"The first chapter must start at the beginning of the video";
			submissionResponseElem.classList.value = ["submission-response-error"];
			return;
		}
		let lastChapterStart = 0;
		for (let chapterIndex = 1; chapterIndex < chaptersData.length; chapterIndex++) {
			if (chaptersData[chapterIndex].start < lastChapterStart) {
				submissionResponseElem.innerText = "Chapters are out of order";
				submissionResponseElem.classList.value = ["submission-response-error"];
				return;
			}
			if (edited && chaptersData[chapterIndex].start - lastChapterStart < 10) {
				submissionResponseElem.innerText = "Chapters must be at least 10 seconds apart";
				submissionResponseElem.classList.value = ["submission-response-error"];
				return;
			}
			lastChapterStart = chaptersData[chapterIndex].start;
		}

		const chapterTextList = [];
		for (const chapterData of chaptersData) {
			const startTime = formatChapterTime(chapterData.start, videoHasHours);
			chapterTextList.push(`${startTime} - ${chapterData.description}`);
		}

		videoDescription = videoDescription + CHAPTER_MARKER_DELIMITER + chapterTextList.join("\n");
	}

	const thumbnailMode = document.getElementById("video-info-thumbnail-mode").value;
	let thumbnailTemplate = null;
	let thumbnailTime = null;
	let thumbnailImage = null;
	if (thumbnailMode === "BARE" || thumbnailMode === "TEMPLATE") {
		thumbnailTime = wubloaderTimeFromVideoHumanTime(
			document.getElementById("video-info-thumbnail-time").value
		);
		if (thumbnailTime === null) {
			submissionResponseElem.innerText = "The thumbnail time is invalid";
			submissionResponseElem.classList.value = ["submission-response-error"];
			return;
		}
	}
	if (thumbnailMode === "TEMPLATE") {
		thumbnailTemplate = document.getElementById("video-info-thumbnail-template").value;
	}
	if (thumbnailMode === "CUSTOM") {
		const fileInput = document.getElementById("video-info-thumbnail-custom");
		if (fileInput.files.length === 0) {
			if (!videoInfo.thumbnail_image) {
				submissionResponseElem.innerText =
					"A thumbnail file was not provided for the custom thumbnail";
				submissionResponseElem.classList.value = ["submission-response-error"];
				return;
			}
			thumbnailImage = videoInfo.thumbnail_image;
		} else {
			const fileHandle = fileInput.files[0];
			const fileReader = new FileReader();
			let loadPromiseResolve;
			const loadPromise = new Promise((resolve, _reject) => {
				loadPromiseResolve = resolve;
			});
			fileReader.addEventListener("loadend", (event) => {
				loadPromiseResolve(event.target);
			});
			fileReader.readAsArrayBuffer(fileHandle);
			const fileLoadData = await loadPromise;
			if (fileLoadData.error) {
				submissionResponseElem.innerText = `An error (${fileLoadData.error.name}) occurred loading the custom thumbnail: ${fileLoadData.error.message}`;
				submissionResponseElem.classList.value = ["submission-response-error"];
				return;
			}
			const fileData = fileLoadData.result;
			const fileBytes = new Uint8Array(fileData);
			const fileBinaryString = String.fromCharCode(...fileBytes);
			thumbnailImage = btoa(fileBinaryString);
		}
	}

	const videoTitle = document.getElementById("video-info-title").value;
	const videoTags = document.getElementById("video-info-tags").value.split(",");
	const allowHoles = document.getElementById("advanced-submission-option-allow-holes").checked;
	const isPublic = !document.getElementById("advanced-submission-option-unlisted").checked;
	const uploadLocation = document.getElementById(
		"advanced-submission-option-upload-location"
	).value;
	const uploaderAllowlistValue = document.getElementById(
		"advanced-submission-option-uploader-allow"
	).value;
	const uploaderAllowlist = uploaderAllowlistValue ? uploaderAllowlistValue.split(",") : null;

	const editData = {
		video_ranges: ranges,
		video_transitions: transitions,
		video_title: videoTitle,
		video_description: videoDescription,
		video_tags: videoTags,
		allow_holes: allowHoles,
		upload_location: uploadLocation,
		public: isPublic,
		video_channel: globalStreamName,
		video_quality: videoInfo.video_quality,
		uploader_whitelist: uploaderAllowlist,
		state: newState,
		thumbnail_mode: thumbnailMode,
		thumbnail_template: thumbnailTemplate,
		thumbnail_time: thumbnailTime,
		thumbnail_image: thumbnailImage,

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

	window.removeEventListener("beforeunload", handleLeavePageWhilePending);

	if (submitResponse.ok) {
		submissionResponseElem.classList.value = ["submission-response-success"];
		if (newState === "EDITED") {
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
		} else if (newState === "UNEDITED") {
			submissionResponseElem.innerText = "Saved draft";
		} else if (newState === "MODIFIED") {
			submissionResponseElem.innerText = "Submitted changes";
		} else {
			// should never happen but shrug
			submissionResponseElem.innerText = `Submitted state ${newState}`;
		}
	} else {
		submissionResponseElem.classList.value = ["submission-response-error"];
		if (submitResponse.status === 409) {
			const serverErrorNode = document.createTextNode(await submitResponse.text());
			const submitButton = document.createElement("button");
			submitButton.innerText = "Submit Anyway";
			submitButton.addEventListener("click", (_event) => {
				sendVideoData(newState, true);
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

function formatChapterTime(playerTime, hasHours) {
	let hours = Math.trunc(playerTime / 3600);
	let minutes = Math.trunc((playerTime / 60) % 60);
	let seconds = Math.trunc(playerTime % 60);

	while (minutes.toString().length < 2) {
		minutes = `0${minutes}`;
	}
	while (seconds.toString().length < 2) {
		seconds = `0${seconds}`;
	}

	if (hasHours) {
		return `${hours}:${minutes}:${seconds}`;
	}
	return `${minutes}:${seconds}`;
}

function unformatChapterTime(chapterTime) {
	const timeParts = chapterTime.split(":");
	while (timeParts.length < 3) {
		timeParts.unshift(0);
	}
	const hours = +timeParts[0];
	const minutes = +timeParts[1];
	const seconds = +timeParts[2];

	return hours * 3600 + minutes * 60 + seconds;
}

function handleLeavePageWhilePending(event) {
	event.preventDefault();
	event.returnValue =
		"The video submission is still pending. Are you sure you want to exit? You may lose your edits.";
	return event.returnValue;
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
		responseElem.innerText = "Row has been cancelled.";
		setTimeout(() => {
			responseElem.innerText = "";
		}, 2000);
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
		responseElem.innerText = "Row has been reset.";
		const forceResetConfirmationContainer = document.getElementById(
			"data-correction-force-reset-confirm"
		);
		forceResetConfirmationContainer.classList.add("hidden");
		setTimeout(() => {
			responseElem.innerText = "";
		}, 2000);
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

	const rangeTimesContainer = document.createElement("div");
	rangeTimesContainer.classList.add("range-definition-times");
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

	rangeTimesContainer.appendChild(rangeStart);
	rangeTimesContainer.appendChild(rangeStartSet);
	rangeTimesContainer.appendChild(rangeStartPlay);
	rangeTimesContainer.appendChild(rangeTimeGap);
	rangeTimesContainer.appendChild(rangeEnd);
	rangeTimesContainer.appendChild(rangeEndSet);
	rangeTimesContainer.appendChild(rangeEndPlay);
	rangeTimesContainer.appendChild(removeRange);
	rangeTimesContainer.appendChild(currentRangeMarker);

	const rangeChaptersContainer = document.createElement("div");
	const enableChaptersElem = document.getElementById("enable-chapter-markers");
	const chaptersEnabled = enableChaptersElem.checked;
	rangeChaptersContainer.classList.add("range-definition-chapter-markers");
	if (!chaptersEnabled) {
		rangeChaptersContainer.classList.add("hidden");
	}

	const rangeAddChapterElem = document.createElement("img");
	rangeAddChapterElem.src = "images/plus.png";
	rangeAddChapterElem.alt = "Add chapter marker";
	rangeAddChapterElem.title = "Add chapter marker";
	rangeAddChapterElem.classList.add("add-range-definition-chapter-marker");
	rangeAddChapterElem.classList.add("click");
	if (!chaptersEnabled) {
		rangeAddChapterElem.classList.add("hidden");
	}
	rangeAddChapterElem.addEventListener("click", addChapterMarkerHandler);

	rangeContainer.appendChild(rangeTimesContainer);
	rangeContainer.appendChild(rangeChaptersContainer);
	rangeContainer.appendChild(rangeAddChapterElem);

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

function chapterMarkerDefinitionDOM() {
	const startFieldContainer = document.createElement("div");
	const startField = document.createElement("input");
	startField.type = "text";
	startField.classList.add("range-definition-chapter-marker-start");
	startField.placeholder = "Start time";

	const setStartTime = document.createElement("img");
	setStartTime.src = "images/pencil.png";
	setStartTime.alt = "Set chapter start time";
	setStartTime.title = setStartTime.alt;
	setStartTime.classList.add("range-definition-chapter-marker-set-start");
	setStartTime.classList.add("click");

	setStartTime.addEventListener("click", (event) => {
		const chapterContainer = event.currentTarget.parentElement;
		const startTimeField = chapterContainer.getElementsByClassName(
			"range-definition-chapter-marker-start"
		)[0];
		const videoElement = document.getElementById("video");
		startTimeField.value = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	});

	startFieldContainer.appendChild(startField);
	startFieldContainer.appendChild(setStartTime);

	const descriptionField = document.createElement("input");
	descriptionField.type = "text";
	descriptionField.classList.add("range-definition-chapter-marker-description");
	descriptionField.placeholder = "Description";

	const removeButton = document.createElement("img");
	removeButton.src = "images/minus.png";
	removeButton.alt = "Remove this chapter";
	removeButton.title = removeButton.alt;
	removeButton.classList.add("range-definition-chapter-marker-remove");
	removeButton.classList.add("click");

	removeButton.addEventListener("click", (event) => {
		const thisDefinition = event.currentTarget.parentElement;
		thisDefinition.parentNode.removeChild(thisDefinition);
	});

	const chapterContainer = document.createElement("div");
	chapterContainer.appendChild(startFieldContainer);
	chapterContainer.appendChild(descriptionField);
	chapterContainer.appendChild(removeButton);

	return chapterContainer;
}

function addChapterMarkerHandler(event) {
	const newChapterMarker = chapterMarkerDefinitionDOM();
	event.currentTarget.previousElementSibling.appendChild(newChapterMarker);
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

		if (rangeStart !== null && rangeEnd !== null) {
			const rangeStartPercentage = (rangeStart / videoDuration) * 100;
			const rangeEndPercentage = (rangeEnd / videoDuration) * 100;
			const widthPercentage = rangeEndPercentage - rangeStartPercentage;

			const marker = document.createElement("div");
			marker.style.width = `${widthPercentage}%`;
			marker.style.left = `${rangeStartPercentage}%`;
			clipBar.appendChild(marker);
		}

		let oldRangeStart = rangeStartField.dataset.oldTime;
		let oldRangeEnd = rangeEndField.dataset.oldTime;
		if (oldRangeStart) {
			oldRangeStart = videoPlayerTimeFromVideoHumanTime(oldRangeStart);
		} else {
			oldRangeStart = null;
		}
		if (oldRangeEnd) {
			oldRangeEnd = videoPlayerTimeFromVideoHumanTime(oldRnageEnd);
		} else {
			oldRangeEnd = null;
		}
		if (rangeStart === null) {
			delete rangeStartField.dataset.oldTime;
		} else if (oldRangeStart === null) {
			rangeStartField.dataset.oldTime = rangeStartField.value;
		} else {
			const startOffset = rangeStart - oldRangeStart;
			for (const chapterStartField of rangeDefinition.getElementsByClassName(
				"range-definition-chapter-marker-start"
			)) {
				const chapterStart = videoPlayerTimeFromVideoHumanTime(chapterStartField.value);
				if (chapterStart !== null) {
					chapterStartField.value = videoHumanTimeFromVideoPlayerTime(chapterStart + startOffset);
				}
			}
			rangeStartField.dataset.oldTime = rangeStartField.value;
		}
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

function enableChapterMarkers(enable) {
	document.getElementById("enable-chapter-markers").checked = enable;
	changeEnableChaptersHandler();
}

function changeEnableChaptersHandler() {
	const chaptersEnabled = document.getElementById("enable-chapter-markers").checked;
	for (const chapterMarkerContainer of document.getElementsByClassName(
		"range-definition-chapter-markers"
	)) {
		if (chaptersEnabled) {
			chapterMarkerContainer.classList.remove("hidden");
		} else {
			chapterMarkerContainer.classList.add("hidden");
		}
	}
	for (const addChapterMarkerElem of document.getElementsByClassName(
		"add-range-definition-chapter-marker"
	)) {
		if (chaptersEnabled) {
			addChapterMarkerElem.classList.remove("hidden");
		} else {
			addChapterMarkerElem.classList.add("hidden");
		}
	}
}

function videoPlayerTimeFromWubloaderTime(wubloaderTime) {
	const wubloaderDateTime = dateTimeFromWubloaderTime(wubloaderTime);
	const segmentList = getSegmentList();
	for (let segmentIndex = 0; segmentIndex < segmentList.length - 1; segmentIndex++) {
		const thisSegment = segmentList[segmentIndex];
		const nextSegment = segmentList[segmentIndex + 1];
		const segmentStartTime = DateTime.fromISO(thisSegment.rawProgramDateTime);
		const nextSegmentStartTime = DateTime.fromISO(nextSegment.rawProgramDateTime);
		if (segmentStartTime <= wubloaderDateTime && nextSegmentStartTime > wubloaderDateTime) {
			let offset = wubloaderDateTime.diff(segmentStartTime).as("seconds");
			// If there's a hole in the video and this wubloader time is in the hole, this will end up
			// at a random point. We can fix that by capping the offset at the segment duration.
			if (offset > thisSegment.duration) {
				offset = thisSegment.duration;
			}
			return thisSegment.start + offset;
		}
	}
	const lastSegment = segmentList[segmentList.length - 1];
	const lastSegmentStartTime = DateTime.fromISO(lastSegment.rawProgramDateTime);
	const lastSegmentEndTime = lastSegmentStartTime.plus({ seconds: lastSegment.duration });
	if (lastSegmentStartTime <= wubloaderDateTime && wubloaderDateTime <= lastSegmentEndTime) {
		return lastSegment.start + wubloaderDateTime.diff(lastSegmentStartTime).as("seconds");
	}
	return null;
}

function videoPlayerTimeFromDateTime(dateTime) {
	const segmentList = getSegmentList();
	for (const segment of segmentList) {
		const segmentStart = DateTime.fromISO(segment.rawProgramDateTime);
		const segmentEnd = segmentStart.plus({ seconds: segment.duration });
		if (dateTime >= segmentStart && dateTime <= segmentEnd) {
			return segment.start + dateTime.diff(segmentStart).as("seconds");
		}
	}
	return null;
}

function dateTimeFromVideoHumanTime(videoHumanTime) {
	const videoPlayerTime = videoPlayerTimeFromVideoHumanTime(videoHumanTime);
	if (videoPlayerTime === null) {
		return null;
	}
	return dateTimeFromVideoPlayerTime(videoPlayerTime);
}

function videoHumanTimeFromDateTime(dateTime) {
	const videoPlayerTime = videoPlayerTimeFromDateTime(dateTime);
	if (videoPlayerTime === null) {
		return null;
	}
	return videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
}

function wubloaderTimeFromVideoPlayerTime(videoPlayerTime) {
	const dt = dateTimeFromVideoPlayerTime(videoPlayerTime);
	return wubloaderTimeFromDateTime(dt);
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
