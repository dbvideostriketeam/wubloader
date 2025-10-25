var googleUser = null;
var videoInfo;
var currentRange = 1;
let knownTransitions = [];
let thumbnailTemplates = {};
let globalPageState = 0;

// Set when a thumbnail already exists when we load a video.
// Used to re-upload the same image if a new one is not provided.
let existingThumbnailBase64;

const CHAPTER_MARKER_DELIMITER = "\n==========\n";
const CHAPTER_MARKER_DELIMITER_PARTIAL = "==========";

const PAGE_STATE = {
	CLEAN: 0,
	DIRTY: 1,
	SUBMITTING: 2,
	CONFIRMING: 3,
};

// References to Jcrop "stages" for the advanced thumbnail editor crop tool
let videoFrameStage;
let templateStage;

window.addEventListener("DOMContentLoaded", async (event) => {
	commonPageSetup();
	globalLoadChatWorker.onmessage = (event) => {
		updateChatDataFromWorkerResponse(event.data);
		renderChatLog();
	};
	window.addEventListener("beforeunload", handleLeavePage);

	const timeUpdateForm = document.getElementById("stream-time-settings");
	timeUpdateForm.addEventListener("submit", async (event) => {
		event.preventDefault();

		if (!videoInfo) {
			addError(
				"Time updates are ignored before the video metadata has been retrieved from Wubloader.",
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
		const rangeDefinitionsElements = document.getElementById("range-definitions").children;
		for (const rangeContainer of rangeDefinitionsElements) {
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
					"Some ranges couldn't be updated for the new video time endpoints. Please verify the time range values.",
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

	loadTransitions(); // Intentionally not awaiting, fire and forget
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
	if (canEditVideo()) {
		addRangeIcon.addEventListener("click", (_event) => {
			addRangeDefinition();
			handleFieldChange(event);
		});
		addRangeIcon.addEventListener("keypress", (event) => {
			if (event.key === "Enter") {
				addRangeDefinition();
				handleFieldChange(event);
			}
		});
	} else {
		addRangeIcon.classList.add("hidden");
	}

	const enableChaptersElem = document.getElementById("enable-chapter-markers");
	enableChaptersElem.addEventListener("change", (event) => {
		changeEnableChaptersHandler();
		handleFieldChange(event);
	});

	if (canEditVideo()) {
		for (const rangeStartSet of document.getElementsByClassName("range-definition-set-start")) {
			rangeStartSet.addEventListener("click", getRangeSetClickHandler("start"));
		}
		for (const rangeEndSet of document.getElementsByClassName("range-definition-set-end")) {
			rangeEndSet.addEventListener("click", getRangeSetClickHandler("end"));
		}
	}
	for (const rangeStartPlay of document.getElementsByClassName("range-definition-play-start")) {
		rangeStartPlay.addEventListener("click", rangePlayFromStartHandler);
	}
	for (const rangeEndPlay of document.getElementsByClassName("range-definition-play-end")) {
		rangeEndPlay.addEventListener("click", rangePlayFromEndHandler);
	}
	for (const rangeStart of document.getElementsByClassName("range-definition-start")) {
		rangeStart.addEventListener("change", (event) => {
			rangeDataUpdated();
			handleFieldChange(event);
		});
	}
	for (const rangeEnd of document.getElementsByClassName("range-definition-end")) {
		rangeEnd.addEventListener("change", (event) => {
			rangeDataUpdated();
			handleFieldChange(event);
		});
	}
	if (canEditMetadata()) {
		for (const addChapterMarker of document.getElementsByClassName(
			"add-range-definition-chapter-marker",
		)) {
			addChapterMarker.addEventListener("click", addChapterMarkerHandler);
		}
	}

	document
		.getElementById("range-definition-chapter-marker-first-description")
		.addEventListener("input", (event) => {
			validateChapterDescription(event.target);
		});
	document.getElementById("video-info-title").addEventListener("input", (event) => {
		validateVideoTitle();
		document.getElementById("video-info-title-abbreviated").innerText =
			videoInfo.title_prefix + document.getElementById("video-info-title").value;
		handleFieldChange(event);
	});
	document.getElementById("video-info-description").addEventListener("input", (event) => {
		validateVideoDescription();
		handleFieldChange(event);
	});
	document
		.getElementById("video-info-thumbnail-template")
		.addEventListener("change", (event) => {
			handleFieldChange(event);
			updateThumbnailImages();
		});
	document
		.getElementById("video-info-thumbnail-mode")
		.addEventListener("change", updateThumbnailInputState);
	document
		.getElementById("video-info-thumbnail-time")
		.addEventListener("change", (event) => {
			handleFieldChange(event);
			updateThumbnailImages();
		});

	if (canEditMetadata()) {
		document.getElementById("video-info-thumbnail-time-set").addEventListener("click", (_event) => {
			const field = document.getElementById("video-info-thumbnail-time");
			const videoPlayer = document.getElementById("video");
			const videoPlayerTime = videoPlayer.currentTime;
			field.value = videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
		});
		document
			.getElementById("video-info-thumbnail-time-play")
			.addEventListener("click", (_event) => {
				const field = document.getElementById("video-info-thumbnail-time");
				const thumbnailTime = videoPlayerTimeFromVideoHumanTime(field.value);
				if (thumbnailTime === null) {
					addError("Couldn't play from thumbnail frame; failed to parse time");
					return;
				}
				const videoPlayer = document.getElementById("video");
				videoPlayer.currentTime = thumbnailTime;
			});
	}

	document
		.getElementById("video-info-thumbnail-template-source-image-update")
		.addEventListener("click", (_event) => updateThumbnailImages());

	document
		.getElementById("video-info-thumbnail-crop-0")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-crop-1")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-crop-2")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-crop-3")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-location-0")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-location-1")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-location-2")
		.addEventListener("input", updateTemplateCropWidgets);
	document
		.getElementById("video-info-thumbnail-location-3")
		.addEventListener("input", updateTemplateCropWidgets);

	document
		.getElementById("video-info-thumbnail-lock-aspect-ratio")
		.addEventListener("change", updateTemplateCropAspectRatio);

	document
		.getElementById("video-info-thumbnail-aspect-ratio-match-right")
		.addEventListener("click", function () {
			// Calculate and copy the aspect ratio from the video field to the template
			const videoFieldX1 = document.getElementById("video-info-thumbnail-crop-0");
			const videoFieldY1 = document.getElementById("video-info-thumbnail-crop-1");
			const videoFieldX2 = document.getElementById("video-info-thumbnail-crop-2");
			const videoFieldY2 = document.getElementById("video-info-thumbnail-crop-3");
			const videoFieldAspectRatio =
				(videoFieldX2.value - videoFieldX1.value) / (videoFieldY2.value - videoFieldY1.value);

			templateStage.setOptions({ aspectRatio: videoFieldAspectRatio });

			// Re-apply the locked/unlocked status
			updateTemplateCropAspectRatio();
		});

	document
		.getElementById("video-info-thumbnail-aspect-ratio-match-left")
		.addEventListener("click", function () {
			// Calculate and copy the aspect ratio from the template to the video field
			const templateFieldX1 = document.getElementById("video-info-thumbnail-location-0");
			const templateFieldY1 = document.getElementById("video-info-thumbnail-location-1");
			const templateFieldX2 = document.getElementById("video-info-thumbnail-location-2");
			const templateFieldY2 = document.getElementById("video-info-thumbnail-location-3");
			const templateFieldAspectRatio =
				(templateFieldX2.value - templateFieldX1.value) /
				(templateFieldY2.value - templateFieldY1.value);

			videoFrameStage.setOptions({ aspectRatio: templateFieldAspectRatio });

			// Re-apply the locked/unlocked status
			updateTemplateCropAspectRatio();
		});

	document
		.getElementById("video-info-thumbnail-custom")
		.addEventListener("change", (_event) => updateThumbnailImages());

	document
		.getElementById("video-info-thumbnail-template-preview-generate")
		.addEventListener("click", async (_event) => {
			const imageElement = document.getElementById("video-info-thumbnail-template-preview-image");
			const thumbnailMode = document.getElementById("video-info-thumbnail-mode").value;

			if (thumbnailMode === "ONEOFF") {
				try {
					const data = await renderThumbnail();
					imageElement.src = `data:image/png;base64,${data}`;
				} catch (e) {
					imageElement.classList.add("hidden");
					addError(`${e}`);
					return;
				}
			} else {
				const timeEntryElement = document.getElementById("video-info-thumbnail-time");
				const imageTime = wubloaderTimeFromVideoHumanTime(timeEntryElement.value);
				if (imageTime === null) {
					imageElement.classList.add("hidden");
					addError("Couldn't preview thumbnail; couldn't parse thumbnail frame timestamp");
					return;
				}
				const imageTemplate = document.getElementById("video-info-thumbnail-template").value;
				const [crop, loc] = getTemplatePosition();
				const query = new URLSearchParams({
					timestamp: imageTime,
					template: imageTemplate,
					crop: crop.join(","),
					location: loc.join(","),
				});
				imageElement.src = `/thumbnail/${globalStreamName}/source.png?${query}`;
			}
			imageElement.classList.remove("hidden");
		});

	const thumbnailTemplateSelection = document.getElementById("video-info-thumbnail-template");
	const thumbnailTemplatesListResponse = await fetch("/thrimshim/templates");
	if (thumbnailTemplatesListResponse.ok) {
		const thumbnailTemplatesList = await thumbnailTemplatesListResponse.json();
		const templateNames = thumbnailTemplatesList.map((t) => t.name);
		templateNames.sort();
		for (const template of thumbnailTemplatesList) {
			thumbnailTemplates[template.name] = template;
		}
		for (const templateName of templateNames) {
			const templateOption = document.createElement("option");
			templateOption.innerText = templateName;
			templateOption.value = templateName;
			templateOption.title = thumbnailTemplates[templateName].description;
			if (templateName === videoInfo.thumbnail_template) {
				templateOption.selected = true;
			}
			thumbnailTemplateSelection.appendChild(templateOption);
		}
		setDefaultCrop(false);
	} else {
		addError("Failed to load thumbnail templates list");
	}
	if (videoInfo.thumbnail_crop !== null) {
		for (let i = 0; i < 4; i++) {
			document.getElementById(`video-info-thumbnail-crop-${i}`).value = videoInfo.thumbnail_crop[i];
		}
	}
	if (videoInfo.thumbnail_location !== null) {
		for (let i = 0; i < 4; i++) {
			document.getElementById(`video-info-thumbnail-location-${i}`).value =
				videoInfo.thumbnail_location[i];
		}
	}
	document.getElementById("video-info-thumbnail-mode").value = videoInfo.thumbnail_mode;
	existingThumbnailBase64 = videoInfo.thumbnail_image;
	updateThumbnailInputState();
	// Ensure that changing values on load doesn't set keep the page dirty.
	globalPageState = PAGE_STATE.CLEAN;

	document.getElementById("video-info-thumbnail-template-default-crop").addEventListener("click", (_event) => {
		setDefaultCrop(true);
	});

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
			"data-correction-force-reset-confirm",
		);
		forceResetConfirmationContainer.classList.remove("hidden");
	});
	document.getElementById("data-correction-force-reset-yes").addEventListener("click", (_event) => {
		resetVideoRow();
	});
	document.getElementById("data-correction-force-reset-no").addEventListener("click", (_event) => {
		const forceResetConfirmationContainer = document.getElementById(
			"data-correction-force-reset-confirm",
		);
		forceResetConfirmationContainer.classList.add("hidden");
	});

	document.getElementById("google-auth-sign-out").addEventListener("click", (_event) => {
		googleSignOut();
	});
});

async function loadTransitions() {
	const response = await fetch("/thrimshim/transitions");
	if (!response.ok) {
		addError(
			"Failed to fetch possible transition types. This probably means the wubloader host is down.",
		);
		return;
	}
	knownTransitions = await response.json();
	updateTransitionTypes();
}

async function updateThumbnailImages() {
	const thumbnailMode = document.getElementById("video-info-thumbnail-mode").value;
	if (thumbnailMode !== "TEMPLATE" && thumbnailMode !== "ONEOFF") {
		return;
	}

	const videoFrameImageElement = document.getElementById(
		"video-info-thumbnail-template-video-source-image",
	);

	const timeEntryElement = document.getElementById("video-info-thumbnail-time");
	const imageTime = wubloaderTimeFromVideoHumanTime(timeEntryElement.value);
	if (imageTime === null) {
		videoFrameImageElement.classList.add("hidden");
		addError("Couldn't preview thumbnail; couldn't parse thumbnail frame timestamp");
		return;
	}
	const videoFrameQuery = new URLSearchParams({
		timestamp: imageTime,
	});
	videoFrameImageElement.src = `/frame/${globalStreamName}/source.png?${videoFrameQuery}`;
	videoFrameImageElement.classList.remove("hidden");

	const templateImageElement = document.getElementById(
		"video-info-thumbnail-template-overlay-image",
	);

	if (thumbnailMode === "TEMPLATE") {
		const imageTemplate = document.getElementById("video-info-thumbnail-template").value;
		templateImageElement.src = `/thrimshim/template/${imageTemplate}.png`;
	} else if (thumbnailMode === "ONEOFF") {
		const templateData = await uploadedImageToBase64();
		templateImageElement.src = `data:image/png;base64,${templateData}`;
	}
	templateImageElement.classList.remove("hidden");

	const aspectRatioControls = document.getElementById(
		"video-info-thumbnail-aspect-ratio-controls",
	);
	aspectRatioControls.classList.remove("hidden");

	createTemplateCropWidgets();
}

// Update the given list of transition type <select> tags (or all of them if not given)
// to contain the full list of known transitions.
// We're careful to update description etc in place if one already exists,
// as this might happen when loading an already-edited video.
function updateTransitionTypes(
	elements = document.getElementsByClassName("range-transition-type"),
) {
	for (const select of elements) {
		// For each transition type, we look for it in the current select tag.
		// If it's there, then we update it and move it to the bottom.
		// Otherwise, we create a new one and append it.
		// That way anything already selected stays selected but is moved into the proper place.
		// This isn't particularly efficient, but it doesn't really matter.
		for (const type of knownTransitions) {
			let option;
			for (const child of select.children) {
				if (child.value === type.name) {
					option = child;
					break;
				}
			}
			if (option === undefined) {
				option = document.createElement("option");
				option.value = type.name;
			}
			option.textContent = type.name;
			option.title = type.description;
			select.append(option);
		}
	}
}

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
			"Failed to load video data. This probably means that the URL is out of date (video ID changed) or that everything is broken (or that the Wubloader host is down).",
		);
		return;
	}
	videoInfo = await dataResponse.json();
	await initializeVideoInfo();
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
	if (videoInfo.video_title !== null) {
		// If a video titles was saved (even if it is blank), use that. Titles
		// can't currently be blank, but we may be loosening validation for drafts.
		titleElem.value = videoInfo.video_title;
	} else {
		// If a video title hasn't been set yet, leave it blank.
		// Exception: RDPs always use the standard title.
		if (videoInfo.tags.includes("RDP")) {
			titleElem.value = videoInfo.description;
		}
	}
	validateVideoTitle();
	document.getElementById("video-info-title-abbreviated").innerText =
		videoInfo.title_prefix + titleElem.value;

	const descriptionElem = document.getElementById("video-info-description");
	if (videoInfo.video_description !== null) {
		// If a video description was saved (even if it is blank), use that.
		descriptionElem.value = videoInfo.video_description;
	} else {
		// If a video description hasn't been set yet, use the descripton from the row.
		// Exception: RDPs start blank because the row is used for the title.
		if (!videoInfo.tags.includes("RDP")) {
			descriptionElem.value = videoInfo.description;
		}
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
		"advanced-submission-option-upload-location",
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
			"advanced-submission-option-uploader-allow",
		);
		uploaderAllowlistBox.value = videoInfo.uploader_whitelist.join(",");
	}

	if (!canEditVideo()) {
		if (canEditMetadata()) {
			const submitButton = document.getElementById("submit-button");
			submitButton.classList.add("hidden");
			const saveButton = document.getElementById("save-button");
			saveButton.classList.add("hidden");
			const submitChangesButton = document.getElementById("submit-changes-button");
			submitChangesButton.classList.remove("hidden");

			document.getElementById("add-range-definition").classList.add("hidden");
			const startTimes = document.getElementsByClassName("range-definition-start");
			const endTimes = document.getElementsByClassName("range-definition-end");
			for (const timeField of startTimes) {
				timeField.disabled = true;
			}
			for (const timeField of endTimes) {
				timeField.disabled = true;
			}

			for (const editIcon of document.getElementsByClassName("range-definition-set-start")) {
				editIcon.classList.add("hidden");
			}
			for (const editIcon of document.getElementsByClassName("range-definition-set-end")) {
				editIcon.classList.add("hidden");
			}
		} else {
			for (const input of document.getElementsByTagName("input")) {
				if (!isNonVideoInput(input)) {
					input.disabled = true;
				}
			}
			for (const textArea of document.getElementsByTagName("textarea")) {
				if (!isNonVideoInput(textArea)) {
					textArea.disabled = true;
				}
			}
			for (const button of document.getElementsByTagName("button")) {
				if (!isNonVideoInput(button)) {
					button.disabled = true;
				}
			}
			for (const selectBox of document.getElementsByTagName("select")) {
				if (!isNonVideoInput(selectBox)) {
					selectBox.disabled = true;
				}
			}
		}
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
			let totalOffsetForTransitions = 0;
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
				const rangeContainer = rangeDefinitionsContainer.children[rangeIndex];

				// Update transition data before converting into player time,
				// as this can affect the conversion.
				// Note that the Nth range is associated here with the (N-1)th transition
				// and so we skip this entirely for N = 0.
				if (rangeIndex > 0) {
					const transition = videoInfo.video_transitions[rangeIndex - 1];
					const transitionType = rangeContainer.getElementsByClassName("range-transition-type")[0];
					const transitionDuration = rangeContainer.getElementsByClassName(
						"range-transition-duration",
					)[0];
					const transitionDurationSection = rangeContainer.getElementsByClassName(
						"range-transition-duration-section",
					)[0];
					if (transition === null) {
						transitionType.value = "";
						transitionDuration.value = "";
						transitionDurationSection.classList.add("hidden");
					} else {
						const [type, duration] = transition;
						// Check if the option is present. If not, create it with no description.
						let found = false;
						for (const option of transitionType.children) {
							if (option.value === type) {
								found = true;
								break;
							}
						}
						if (!found) {
							const option = document.createElement("option");
							option.value = type;
							option.textContent = type;
							transitionType.append(option);
						}
						// Set type and duration.
						transitionType.value = type;
						transitionDuration.value = duration.toString();
						transitionDurationSection.classList.remove("hidden");

						totalOffsetForTransitions += duration;
					}
				}

				const startWubloaderTime = videoInfo.video_ranges[rangeIndex][0];
				const endWubloaderTime = videoInfo.video_ranges[rangeIndex][1];
				const startPlayerTime = videoPlayerTimeFromWubloaderTime(startWubloaderTime);
				const endPlayerTime = videoPlayerTimeFromWubloaderTime(endWubloaderTime);
				if (startWubloaderTime) {
					const startField =
						rangeDefinitionsContainer.children[rangeIndex].getElementsByClassName(
							"range-definition-start",
						)[0];
					startField.value = videoHumanTimeFromVideoPlayerTime(startPlayerTime);
				}
				if (endWubloaderTime) {
					const endField =
						rangeDefinitionsContainer.children[rangeIndex].getElementsByClassName(
							"range-definition-end",
						)[0];
					endField.value = videoHumanTimeFromVideoPlayerTime(endPlayerTime);
				}

				const rangeDuration = endPlayerTime - startPlayerTime;
				const rangeEndVideoTime = rangeStartOffset + rangeDuration;
				if (canAddChapters && startWubloaderTime && endWubloaderTime) {
					const chapterContainer = rangeDefinitionsContainer.children[
						rangeIndex
					].getElementsByClassName("range-definition-chapter-markers")[0];

					if (currentChapterIndex === 0) {
						const chapterStartField = document.getElementById(
							"range-definition-chapter-marker-first-start",
						);
						const chapterDescField = document.getElementById(
							"range-definition-chapter-marker-first-description",
						);
						let chapterStartValue = 0;
						let chapterDescValue = "";
						if (chapterData.length > 0) {
							chapterStartValue = chapterData[0].start;
							chapterDescValue = chapterData[0].description;
						}
						chapterStartField.value = videoHumanTimeFromVideoPlayerTime(
							chapterStartValue - rangeStartOffset + startPlayerTime,
						);
						chapterDescField.value = chapterDescValue;
						currentChapterIndex++;
					}

					while (
						currentChapterIndex < chapterData.length &&
						chapterData[currentChapterIndex].start < rangeEndVideoTime
					) {
						const chapterMarker = chapterMarkerDefinitionDOM();
						const chapterStartField = chapterMarker.getElementsByClassName(
							"range-definition-chapter-marker-start",
						)[0];
						chapterStartField.value = videoHumanTimeFromVideoPlayerTime(
							chapterData[currentChapterIndex].start - rangeStartOffset + startPlayerTime + totalOffsetForTransitions,
						);
						const chapterDescField = chapterMarker.getElementsByClassName(
							"range-definition-chapter-marker-description",
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
			if (globalEndTimeString) {
				const rangeEndField =
					rangeDefinitionsContainer.getElementsByClassName("range-definition-end")[0];
				rangeEndField.value = videoHumanTimeFromWubloaderTime(globalEndTimeString);
			}
		}

		const firstChapterPlayFromStartTime = document.getElementById(
			"range-definition-chapter-marker-first-play-start",
		);
		if (canEditMetadata()) {
			firstChapterPlayFromStartTime.addEventListener("click", chapterMarkerPlayStartTimeHandler);
		} else {
			firstChapterPlayFromStartTime.classList.add("hidden");
		}

		if (videoInfo.thumbnail_time) {
			document.getElementById("video-info-thumbnail-time").value = videoHumanTimeFromWubloaderTime(
				videoInfo.thumbnail_time,
			);
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

	// Ensure that changes made to fields during initial load don't affect the state
	globalPageState = PAGE_STATE.CLEAN;
}

function updateWaveform() {
	let waveformURL =
		"/waveform/" + globalStreamName + "/" + videoInfo.video_quality + ".png?size=1920x125&";

	const query = startAndEndTimeQuery();
	waveformURL += query.toString();

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

function updateThumbnailInputState(event) {
	handleFieldChange(event);

	const newValue = document.getElementById("video-info-thumbnail-mode").value;
	const unhideIDs = [];

	if (newValue === "BARE") {
		unhideIDs.push("video-info-thumbnail-time-options");
	} else if (newValue === "TEMPLATE") {
		unhideIDs.push("video-info-thumbnail-template-options");
		unhideIDs.push("video-info-thumbnail-time-options");
		unhideIDs.push("video-info-thumbnail-position-options");
		unhideIDs.push("video-info-thumbnail-template-preview");
	} else if (newValue === "ONEOFF") {
		unhideIDs.push("video-info-thumbnail-time-options");
		unhideIDs.push("video-info-thumbnail-position-options");
		unhideIDs.push("video-info-thumbnail-custom-options");
		unhideIDs.push("video-info-thumbnail-template-preview");
	} else if (newValue === "CUSTOM") {
		unhideIDs.push("video-info-thumbnail-custom-options");
	}

	for (const optionElement of document.getElementsByClassName(
		"video-info-thumbnail-mode-options",
	)) {
		optionElement.classList.add("hidden");
	}
	for (elemID of unhideIDs) {
		document.getElementById(elemID).classList.remove("hidden");
	}

	updateThumbnailImages()
}

function setDefaultCrop(updateWidgets) {
	const newTemplate = document.getElementById("video-info-thumbnail-template").value;
	if (newTemplate) {
		for (const field of ["crop", "location"]) {
			const newValue = thumbnailTemplates[newTemplate][field];
			for (let i = 0; i < 4; i++) {
				document.getElementById(`video-info-thumbnail-${field}-${i}`).value = newValue[i];
			}
		}
	}

	if (updateWidgets) {
		updateTemplateCropWidgets();
	}
	handleFieldChange();
}

// Returns [crop, location], with either being null on error.
function getTemplatePosition() {
	const ret = [];

	for (const field of ["crop", "location"]) {
		let values = [null, null, null, null];
		for (let i = 0; i < 4; i++) {
			const value = parseInt(document.getElementById(`video-info-thumbnail-${field}-${i}`).value);
			if (isNaN(value)) {
				values = null;
				break;
			}
			values[i] = value;
		}
		ret.push(values);
	}

	return ret;
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

function validateChapterDescription(chapterDescField) {
	const chapterDesc = chapterDescField.value;
	if (chapterDesc.indexOf("<") !== -1 || chapterDesc.indexOf(">") !== -1) {
		chapterDescField.classList.add("input-error");
		chapterDescField.title = "Chapter description may not contain angle brackets (< or >)";
	} else if (Array.from(chapterDesc).some((c) => c.charCodeAt(0) > 127)) {
		// any char is non-ascii
		// We don't know what chars are safe outside the ascii range, so we just warn on any of them.
		// We know emoji are not safe.
		chapterDescField.classList.add("input-error");
		chapterDescField.title =
			"Chapter descriptions with non-ascii characters may cause issues; proceed with caution";
	} else {
		chapterDescField.classList.remove("input-error");
		chapterDescField.title = "";
	}
}

async function submitVideo() {
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
			"Couldn't submit edits: Description contains manually entered chapter marker delimiter",
		);
		return;
	}

	const edited = newState === "EDITED";

	const submissionResponseElem = document.getElementById("submission-response");
	submissionResponseElem.classList.value = ["submission-response-pending"];
	submissionResponseElem.innerText = "Submitting video...";

	function submissionError(message) {
		submissionResponseElem.innerText = message;
		submissionResponseElem.classList.value = ["submission-response-error"];
	}

	const rangesData = [];
	const transitions = [];
	let chaptersData = [];
	const chaptersEnabled = document.getElementById("enable-chapter-markers").checked;
	let rangeStartInFinalVideo = 0;
	for (const rangeContainer of document.getElementById("range-definitions").children) {
		// First range container has no transition.
		const transitionTypeElements = rangeContainer.getElementsByClassName("range-transition-type");
		if (transitionTypeElements.length > 0) {
			const transitionType = transitionTypeElements[0].value;
			const transitionDurationStr = rangeContainer.getElementsByClassName(
				"range-transition-duration",
			)[0].value;
			if (transitionType === "") {
				transitions.push(null);
			} else {
				// parseFloat() ignores trailing invalid chars, Number() returns 0 for empty string,
				// but 0 is an error here anyway.
				// Note that !(x > 0) is not equivalent to (x <= 0) due to NaN.
				const transitionDuration = Number(transitionDurationStr);
				if (!(transitionDuration > 0)) {
					submissionError(
						`Couldn't submit edits: Invalid transition duration: "${transitionDurationStr}"`,
					);
					return;
				}
				transitions.push([transitionType, transitionDuration]);
				// Since we're overlapping with the previous range, this range's start time is
				// actually earlier. This matters for chapter markers.
				rangeStartInFinalVideo -= transitionDuration;
			}
		}

		const rangeStartHuman =
			rangeContainer.getElementsByClassName("range-definition-start")[0].value;
		const rangeEndHuman = rangeContainer.getElementsByClassName("range-definition-end")[0].value;
		const rangeStartPlayer = videoPlayerTimeFromVideoHumanTime(rangeStartHuman);
		const rangeEndPlayer = videoPlayerTimeFromVideoHumanTime(rangeEndHuman);
		const rangeStartSubmit = wubloaderTimeFromVideoPlayerTime(rangeStartPlayer);
		const rangeEndSubmit = wubloaderTimeFromVideoPlayerTime(rangeEndPlayer);

		if (edited && (!rangeStartSubmit || !rangeEndSubmit)) {
			let errorMessage;
			if (!rangeStartSubmit && !rangeEndSubmit) {
				errorMessage = `The range endpoints "${rangeStartSubmit}" and "${rangeEndSubmit}" are not valid.`;
			} else if (!rangeStartSubmit) {
				errorMessage = `The range endpoint "${rangeStartSubmit} is not valid.`;
			} else {
				errorMessage = `The range endpoint "${rangeEndSubmit}" is not valid.`;
			}
			submissionError(errorMessage);
			return;
		}

		if (edited && rangeEndPlayer < rangeStartPlayer) {
			submissionError("One or more ranges has an end time prior to its start time.");
			return;
		}

		rangesData.push({
			start: rangeStartSubmit,
			end: rangeEndSubmit,
		});

		if (chaptersEnabled && rangeStartSubmit && rangeEndSubmit) {
			const rangeChapters = [];
			for (const chapterContainer of rangeContainer.getElementsByClassName(
				"range-definition-chapter-markers",
			)[0].children) {
				const startField = chapterContainer.getElementsByClassName(
					"range-definition-chapter-marker-start",
				)[0];
				const descField = chapterContainer.getElementsByClassName(
					"range-definition-chapter-marker-description",
				)[0];

				const startFieldTime = videoPlayerTimeFromVideoHumanTime(startField.value);
				if (startFieldTime === null) {
					if (edited) {
						submissionError(`Unable to parse chapter start time: ${startField.value}`);
						return;
					}
					continue;
				}
				if (startFieldTime < rangeStartPlayer || startFieldTime > rangeEndPlayer) {
					submissionError(
						`The chapter at "${startField.value}" is outside its containing time range.`,
					);
					return;
				}
				const chapterStartTime = rangeStartInFinalVideo + startFieldTime - rangeStartPlayer;
				const chapterData = {
					start: chapterStartTime,
					videoStart: startFieldTime,
					description: descField.value,
				};
				rangeChapters.push(chapterData);
			}
			rangeChapters.sort((a, b) => a.videoStart - b.videoStart);
			chaptersData = chaptersData.concat(rangeChapters);
		} else {
			const enableChaptersElem = document.getElementById("enable-chapter-markers");
			if (
				enableChaptersElem.checked &&
				rangeContainer.getElementsByClassName("range-definition-chapter-marker-start").length > 0
			) {
				submissionError("Chapter markers can't be saved for ranges without valid endpoints.");
				return;
			}
		}
		rangeStartInFinalVideo += rangeEndPlayer - rangeStartPlayer;
	}
	const finalVideoDuration = rangeStartInFinalVideo;
	const videoHasHours = finalVideoDuration >= 3600;

	const ranges = [];
	for (const range of rangesData) {
		ranges.push([range.start, range.end]);
	}

	if (chaptersData.length > 0) {
		if (chaptersData[0].start !== 0) {
			submissionError("The first chapter must start at the beginning of the video");
			return;
		}
		let lastChapterStart = 0;
		for (let chapterIndex = 1; chapterIndex < chaptersData.length; chapterIndex++) {
			if (edited && chaptersData[chapterIndex].start - lastChapterStart < 10) {
				submissionError("Chapters must be at least 10 seconds apart");
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

	let thumbnailMode = document.getElementById("video-info-thumbnail-mode").value;
	let thumbnailTemplate = null;
	let thumbnailTime = null;
	let thumbnailImage = null;
	let thumbnailCrop = null;
	let thumbnailLocation = null;
	if (thumbnailMode === "BARE" || thumbnailMode === "TEMPLATE") {
		thumbnailTime = wubloaderTimeFromVideoHumanTime(
			document.getElementById("video-info-thumbnail-time").value,
		);
		if (thumbnailTime === null) {
			submissionError("The thumbnail time is invalid");
			return;
		}
	}
	if (thumbnailMode === "TEMPLATE") {
		thumbnailTemplate = document.getElementById("video-info-thumbnail-template").value;
		[thumbnailCrop, thumbnailLocation] = getTemplatePosition();
		if (thumbnailCrop === null || thumbnailLocation === null) {
			submissionError("The thumbnail crop/location options are invalid");
			return;
		}
	}
	try {
		if (thumbnailMode === "CUSTOM") {
			thumbnailImage = await uploadedImageToBase64();
		} else if (thumbnailMode === "ONEOFF") {
			thumbnailImage = await renderThumbnail();
			thumbnailMode = "CUSTOM";
		}
	} catch (e) {
		submissionError(`${e}`);
		return;
	}

	const videoTitle = document.getElementById("video-info-title").value;
	const videoTags = document.getElementById("video-info-tags").value.split(",");
	const allowHoles = document.getElementById("advanced-submission-option-allow-holes").checked;
	const isPublic = !document.getElementById("advanced-submission-option-unlisted").checked;
	const uploadLocation = document.getElementById(
		"advanced-submission-option-upload-location",
	).value;
	const uploaderAllowlistValue = document.getElementById(
		"advanced-submission-option-uploader-allow",
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
		thumbnail_crop: thumbnailCrop,
		thumbnail_location: thumbnailLocation,
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

	globalPageState = PAGE_STATE.SUBMITTING;

	const submitResponse = await fetch(`/thrimshim/${videoInfo.id}`, {
		method: "POST",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/json",
		},
		body: JSON.stringify(editData),
	});

	if (submitResponse.ok) {
		globalPageState = PAGE_STATE.CLEAN;
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
		globalPageState = PAGE_STATE.DIRTY;
		submissionResponseElem.classList.value = ["submission-response-error"];
		if (submitResponse.status === 409) {
			globalPageState = PAGE_STATE.CONFIRMING;
			const serverErrorNode = document.createTextNode(await submitResponse.text());
			const submitButton = document.createElement("button");
			if (newState === "UNEDITED") {
				submitButton.innerText = "Save Draft Anyway";
			} else if (newState === "MODIFIED") {
				submitButton.innerText = "Submit Changes Anyway";
			} else {
				submitButton.innerText = "Submit Anyway";
			}
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
	if (seconds > 59) {
		seconds = 59;
	}

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

function handleFieldChange(_event) {
	globalPageState = PAGE_STATE.DIRTY;
}

function handleLeavePage(event) {
	if (globalPageState === PAGE_STATE.CLEAN) {
		return;
	}
	event.preventDefault();
	switch (globalPageState) {
		case PAGE_STATE.DIRTY:
			event.returnValue =
				"There are unsaved edits. Are you sure you want to exit? You will lose your edits.";
			break;
		case PAGE_STATE.SUBMITTING:
			event.returnValue =
				"The video is stsill being submitted. Are you sure you want to exit? You may lose your edits.";
			break;
		case PAGE_STATE.CONFIRMING:
			event.returnValue =
				"There's a confirmation for video submission. Are you sure you want to exit? You will lose your edits.";
			break;
	}
	return event.returnValue;
}

function generateDownloadURL(timeRanges, transitions, downloadType, allowHoles, quality) {
	const query = new URLSearchParams({
		type: downloadType,
		allow_holes: allowHoles,
	});
	for (const range of timeRanges) {
		let timeRangeString = "";
		if (range.hasOwnProperty("start")) {
			timeRangeString += range.start;
		}
		timeRangeString += ",";
		if (range.hasOwnProperty("end")) {
			timeRangeString += range.end;
		}
		query.append("range", timeRangeString);
	}
	for (const transition of transitions) {
		query.append("transition", transition);
	}

	const downloadURL = `/cut/${globalStreamName}/${quality}.ts?${query.toString()}`;
	return downloadURL;
}

// Reads file data from the custom thumbnail upload input, and returns base64 string.
// Will use a previously-uploaded image if no image is given and previous upload is available.
// Throws on error.
async function uploadedImageToBase64() {
	const fileInput = document.getElementById("video-info-thumbnail-custom");
	if (fileInput.files.length === 0) {
		if (existingThumbnail !== undefined) {
			return existingThumbnailBase64
		}
		throw new Error("A file was not provided for the thumbnail");
	}

	const fileHandle = fileInput.files[0];
	const fileReader = new FileReader();
	let loadPromiseResolve;
	const loadPromise = new Promise((resolve, _reject) => {
		loadPromiseResolve = resolve;
	});
	fileReader.addEventListener("loadend", (event) => {
		loadPromiseResolve();
	});
	fileReader.readAsDataURL(fileHandle);
	await loadPromise;

	const fileLoadData = fileReader.result;
	if (fileLoadData.error) {
		throw new Error(
			`An error (${fileLoadData.error.name}) occurred loading the thumbnail: ${fileLoadData.error.message}`,
		);
	}
	if (fileLoadData.substring(0, 22) !== "data:image/png;base64,") {
		throw new Error("An error occurred converting the uploaded image to base64.");
	}
	return fileLoadData.substring(22);
}

// Submits a thumbnail to restreamer to be rendered, and returns the result as base64.
// Throws on error.
async function renderThumbnail() {
	const thumbnailTime = wubloaderTimeFromVideoHumanTime(
		document.getElementById("video-info-thumbnail-time").value,
	);
	if (thumbnailTime === null) {
		throw new Error("The thumbnail time is invalid");
	}
	const [thumbnailCrop, thumbnailLocation] = getTemplatePosition();
	if (thumbnailCrop === null || thumbnailLocation === null) {
		throw new Error("The thumbnail crop/location options are invalid");
	}
	const query = new URLSearchParams({
		timestamp: thumbnailTime,
		crop: thumbnailCrop.join(","),
		location: thumbnailLocation.join(","),
	});
	const templateData = await uploadedImageToBase64();
	// Client-side javascript makes it shockingly hard to correctly decode base64.
	// See https://developer.mozilla.org/en-US/docs/Glossary/Base64#the_unicode_problem
	// The "cleanest" solution is to "fetch" the data URL containing base64 data.
	const datares = await fetch(`data:application/octet-stream;base64,${templateData}`);
	const body = new Uint8Array(await datares.arrayBuffer());
	const res = await fetch(`/thumbnail/${globalStreamName}/source.png?${query}`, {
		method: "POST",
		body,
	});
	if (!res.ok) {
		throw new Error(`Rendering thumbnail failed with ${res.status} ${res.statusText}`);
	}
	// Converting the result into base64 is similarly painful.
	const blob = await res.blob();
	const data = await new Promise((resolve) => {
		const reader = new FileReader();
		reader.onload = () => resolve(reader.result);
		reader.readAsDataURL(blob);
	});
	if (data.substring(0, 22) !== "data:image/png;base64,") {
		throw new Error("An error occurred converting the uploaded image to base64.");
	}
	return data.substring(22);
}

function updateDownloadLink() {
	const downloadType = document.getElementById("download-type-select").value;
	const allowHoles = document.getElementById("advanced-submission-option-allow-holes").checked;

	const timeRanges = [];
	const transitions = [];
	for (const rangeContainer of document.getElementById("range-definitions").children) {
		// First range container has no transition.
		const transitionTypeElements = rangeContainer.getElementsByClassName("range-transition-type");
		if (transitionTypeElements.length > 0) {
			const transitionType = transitionTypeElements[0].value;
			const transitionDurationStr = rangeContainer.getElementsByClassName(
				"range-transition-duration",
			)[0].value;
			if (transitionType === "") {
				transitions.push("");
			} else {
				let transitionDuration = Number(transitionDurationStr);
				// We don't have a sensible way to error out here, so default invalid durations to 1s
				if (!(transitionDuration > 0)) {
					transitionDuration = 1;
				}
				transitions.push(`${transitionType},${transitionDuration}`);
			}
		}

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
		transitions,
		downloadType,
		allowHoles,
		videoInfo.video_quality,
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
			"data-correction-force-reset-confirm",
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

function makeElement(tag, classes = [], values = {}) {
	const element = document.createElement(tag);
	for (const cls of classes) {
		element.classList.add(cls);
	}
	for (const [key, value] of Object.entries(values)) {
		element[key] = value;
	}
	return element;
}

function rangeDefinitionDOM() {
	// Shortcut builder for image-based buttons
	const button = (cls, src, alt) =>
		makeElement("img", [cls, "click"], {
			src,
			alt,
			title: alt,
		});

	const rangeContainer = makeElement("div", ["range-definition-removable"]);

	const transitionContainer = makeElement("div", ["range-transition"]);

	const transitionType = makeElement("select", ["range-transition-type"]);
	// Always add the special-case hard cut option first.
	transitionType.append(
		makeElement("option", [], {
			value: "",
			textContent: "cut",
			title: "A hard cut with no transition. Duration is ignored.",
		}),
	);
	updateTransitionTypes([transitionType]);

	// Duration always starts hidden because type always starts as cut.
	const transitionDurationSection = makeElement("div", [
		"range-transition-duration-section",
		"hidden",
	]);
	// Add/remove hidden when type changes
	transitionType.addEventListener("change", (event) => {
		if (transitionType.value === "") {
			transitionDurationSection.classList.add("hidden");
		} else {
			transitionDurationSection.classList.remove("hidden");
		}
		updateDownloadLink();
		handleFieldChange();
	});
	const transitionDuration = makeElement("input", ["range-transition-duration"], {
		type: "text",
		value: "1",
	});
	transitionDuration.addEventListener("change", (event) => {
		updateDownloadLink();
		handleFieldChange();
	});
	transitionDurationSection.append(" over ", transitionDuration, " seconds");
	transitionContainer.append("Transition: ", transitionType, transitionDurationSection);

	const rangeTimesContainer = makeElement("div", ["range-definition-times"]);
	const rangeStart = makeElement("input", ["range-definition-start"], { type: "text" });
	const rangeStartSet = button(
		"range-definition-set-start",
		"images/pencil.png",
		"Set range start point to the current video time",
	);
	const rangeStartPlay = button(
		"range-definition-play-start",
		"images/play_to.png",
		"Play from start point",
	);
	const rangeTimeGap = makeElement("div", ["range-definition-between-time-gap"]);
	const rangeEnd = makeElement("input", ["range-definition-end"], { type: "text" });
	const rangeEndSet = button(
		"range-definition-set-end",
		"images/pencil.png",
		"Set range end point to the current video time",
	);
	const rangeEndPlay = button(
		"range-definition-play-end",
		"images/play_to.png",
		"Play from end point",
	);
	const removeRange = button("range-definition-remove", "images/minus.png", "Remove range");

	if (canEditVideo()) {
		rangeStartSet.addEventListener("click", getRangeSetClickHandler("start"));
		rangeEndSet.addEventListener("click", getRangeSetClickHandler("end"));
	} else {
		rangeStartSet.classList.add("hidden");
		rangeEndSet.classList.add("hidden");
		rangeStart.disabled = true;
		rangeEnd.disabled = true;
	}

	rangeStartPlay.addEventListener("click", rangePlayFromStartHandler);
	rangeEndPlay.addEventListener("click", rangePlayFromEndHandler);

	if (canEditVideo()) {
		removeRange.addEventListener("click", (event) => {
			handleFieldChange(event);

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
	} else {
		removeRange.classList.add("hidden");
	}

	const currentRangeMarkerAlt = "Range affected by keyboard shortcuts";
	const currentRangeMarker = makeElement("img", ["range-definition-current", "hidden"], {
		src: "images/arrow.png",
		alt: currentRangeMarkerAlt,
		title: currentRangeMarkerAlt,
	});

	rangeTimesContainer.append(
		rangeStart,
		rangeStartSet,
		rangeStartPlay,
		rangeTimeGap,
		rangeEnd,
		rangeEndSet,
		rangeEndPlay,
		removeRange,
		currentRangeMarker,
	);

	const rangeChaptersContainer = makeElement("div", ["range-definition-chapter-markers"]);
	const enableChaptersElem = document.getElementById("enable-chapter-markers");
	const chaptersEnabled = enableChaptersElem.checked;
	if (!chaptersEnabled) {
		rangeChaptersContainer.classList.add("hidden");
	}

	const rangeAddChapterElem = button(
		"add-range-definition-chapter-marker",
		"images/plus.png",
		"Add chapter marker",
	);
	if (!chaptersEnabled) {
		rangeAddChapterElem.classList.add("hidden");
	}
	if (canEditMetadata()) {
		rangeAddChapterElem.addEventListener("click", addChapterMarkerHandler);
	} else {
		rangeAddChapterElem.classList.add("hidden");
	}

	rangeContainer.append(
		transitionContainer,
		rangeTimesContainer,
		rangeChaptersContainer,
		rangeAddChapterElem,
	);

	return rangeContainer;
}

function getRangeSetClickHandler(startOrEnd) {
	return (event) => {
		if (!canEditVideo()) {
			return;
		}
		const setButton = event.currentTarget;
		const setField = setButton.parentElement.getElementsByClassName(
			`range-definition-${startOrEnd}`,
		)[0];

		const videoElement = document.getElementById("video");
		const videoPlayerTime = videoElement.currentTime;

		setField.value = videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
		rangeDataUpdated();
	};
}

function moveToNextRange() {
	currentRange++;
	if (
		canEditVideo() &&
		currentRange > document.getElementById("range-definitions").children.length
	) {
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
	startFieldContainer.classList.add("range-definition-chapter-marker-start-field");

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
			"range-definition-chapter-marker-start",
		)[0];
		const videoElement = document.getElementById("video");
		startTimeField.value = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	});

	const playFromStartTime = document.createElement("img");
	playFromStartTime.src = "images/play_to.png";
	playFromStartTime.alt = "Play from chapter start time";
	playFromStartTime.title = playFromStartTime.alt;
	playFromStartTime.classList.add("range-definition-chapter-marker-play-start");
	playFromStartTime.classList.add("click");

	if (canEditMetadata()) {
		playFromStartTime.addEventListener("click", chapterMarkerPlayStartTimeHandler);
	} else {
		playFromStartTime.classList.add("hidden");
	}

	startFieldContainer.appendChild(startField);
	startFieldContainer.appendChild(setStartTime);
	startFieldContainer.appendChild(playFromStartTime);

	const descriptionField = document.createElement("input");
	descriptionField.type = "text";
	descriptionField.classList.add("range-definition-chapter-marker-description");
	descriptionField.placeholder = "Description";
	descriptionField.addEventListener("input", (event) => {
		validateChapterDescription(descriptionField);
	});

	const removeButton = document.createElement("img");
	removeButton.src = "images/minus.png";
	removeButton.alt = "Remove this chapter";
	removeButton.title = removeButton.alt;
	removeButton.classList.add("range-definition-chapter-marker-remove");
	removeButton.classList.add("click");

	if (canEditMetadata()) {
		removeButton.addEventListener("click", (event) => {
			const thisDefinition = event.currentTarget.parentElement;
			thisDefinition.parentNode.removeChild(thisDefinition);
		});
	} else {
		removeButton.classList.add("hidden");
	}

	const chapterContainer = document.createElement("div");
	chapterContainer.appendChild(startFieldContainer);
	chapterContainer.appendChild(descriptionField);
	chapterContainer.appendChild(removeButton);

	return chapterContainer;
}

function addChapterMarkerHandler(event) {
	if (canEditMetadata()) {
		const newChapterMarker = chapterMarkerDefinitionDOM();
		event.currentTarget.previousElementSibling.appendChild(newChapterMarker);
		handleFieldChange(event);
	}
}

function chapterMarkerPlayStartTimeHandler(event) {
	const chapterContainer = event.currentTarget.parentElement;
	const startTimeField = chapterContainer.getElementsByClassName(
		"range-definition-chapter-marker-start",
	)[0];
	const newVideoTime = videoPlayerTimeFromVideoHumanTime(startTimeField.value);
	if (newVideoTime !== null) {
		const videoElement = document.getElementById("video");
		videoElement.currentTime = newVideoTime;
	}
}

async function rangeDataUpdated() {
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
	}

	const firstRangeStartField = document.getElementsByClassName("range-definition-start")[0]; // There should always be a first one
	const firstChapterStartField = document.getElementById(
		"range-definition-chapter-marker-first-start",
	);
	firstChapterStartField.value = firstRangeStartField.value;

	updateDownloadLink();
}

function setCurrentRangeStartToVideoTime() {
	if (!canEditVideo()) {
		return;
	}

	const rangeStartField = document.querySelector(
		`#range-definitions > div:nth-child(${currentRange}) .range-definition-start`,
	);
	const videoElement = document.getElementById("video");
	rangeStartField.value = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	rangeDataUpdated();
}

function setCurrentRangeEndToVideoTime() {
	if (!canEditVideo()) {
		return;
	}

	const rangeEndField = document.querySelector(
		`#range-definitions > div:nth-child(${currentRange}) .range-definition-end`,
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
		"range-definition-chapter-markers",
	)) {
		if (chaptersEnabled) {
			chapterMarkerContainer.classList.remove("hidden");
		} else {
			chapterMarkerContainer.classList.add("hidden");
		}
	}
	for (const addChapterMarkerElem of document.getElementsByClassName(
		"add-range-definition-chapter-marker",
	)) {
		if (chaptersEnabled) {
			addChapterMarkerElem.classList.remove("hidden");
		} else {
			addChapterMarkerElem.classList.add("hidden");
		}
	}
}

function renderChatLog() {
	const chatReplayParent = document.getElementById("chat-replay");
	chatReplayParent.innerHTML = "";
	for (const chatMessage of globalChatData) {
		if (chatMessage.message.command === "PRIVMSG") {
			const chatDOM = renderChatMessage(chatMessage);
			if (chatDOM) {
				chatReplayParent.appendChild(chatDOM);
			}
		} else if (chatMessage.message.command === "CLEARMSG") {
			const removedMessageID = chatMessage.message.tags["target-msg-id"];
			const removedMessageElem = document.getElementById(`chat-replay-message-${removedMessageID}`);
			if (removedMessageElem) {
				removedMessageElem.classList.add("chat-replay-message-cleared");
			}
		} else if (chatMessage.message.command === "CLEARCHAT") {
			if (chatMessage.message.params.length > 1) {
				const removedSender = chatMessage.message.params[1];
				for (const childNode of document.getElementById("chat-replay").children) {
					if (childNode.dataset.sender === removedSender) {
						childNode.classList.add("chat-replay-message-cleared");
					}
				}
			} else {
				// Without a target parameter, the CLEARCHAT clears all messages in the entire chat.
				for (const childNode of document.getElementById("chat-replay").children) {
					childNode.classList.add("chat-replay-message-cleared");
				}
			}
		} else if (chatMessage.message.command === "USERNOTICE") {
			const chatDOMList = renderSystemMessages(chatMessage);
			for (const chatDOM of chatDOMList) {
				chatReplayParent.appendChild(chatDOM);
			}
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

function dateTimeFromVideoHumanTime(videoHumanTime) {
	const videoPlayerTime = videoPlayerTimeFromVideoHumanTime(videoHumanTime);
	if (videoPlayerTime === null) {
		return null;
	}
	return dateTimeFromVideoPlayerTime(videoPlayerTime);
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

function canEditVideo() {
	return (
		videoInfo.state === "UNEDITED" || videoInfo.state === "EDITED" || videoInfo.state === "CLAIMED"
	);
}

function canEditMetadata() {
	return canEditVideo() || videoInfo.state === "DONE" || videoInfo.state === "MODIFIED";
}

function isNonVideoInput(element) {
	return element.id.startsWith("data-correction-force-reset");
}

/**
 * Helper function to create the Jcrop widgets the first time the user chooses
 * to load the advanced template cropping tool images in a given session.
 */
function createTemplateCropWidgets() {
	if (videoFrameStage == null) {
		videoFrameStage = Jcrop.attach("video-info-thumbnail-template-video-source-image");
		videoFrameStage.listen("crop.update", function (widget, e) {
			const pos = widget.pos;
			const fieldX1 = document.getElementById("video-info-thumbnail-crop-0");
			const fieldY1 = document.getElementById("video-info-thumbnail-crop-1");
			const fieldX2 = document.getElementById("video-info-thumbnail-crop-2");
			const fieldY2 = document.getElementById("video-info-thumbnail-crop-3");
			// 640x320 -> 1920x1080
			fieldX1.value = Math.round(pos.x * 3);
			fieldY1.value = Math.round(pos.y * 3);
			fieldX2.value = Math.round((pos.x + pos.w) * 3);
			fieldY2.value = Math.round((pos.y + pos.h) * 3);
		});
		videoFrameStage.listen("crop.change", function (widget, e) {
			// This only fires when the user is finished dragging, not every time the size
			// of the cropped area updates. This avoids the template area updating every
			// instant due to minute changes in the aspect ratio, which causes it to shrink
			// while resizing.
			updateTemplateCropAspectRatio();
		});
	}
	if (templateStage == null) {
		templateStage = Jcrop.attach("video-info-thumbnail-template-overlay-image");
		templateStage.listen("crop.update", function (widget, e) {
			const pos = widget.pos;
			const fieldX1 = document.getElementById("video-info-thumbnail-location-0");
			const fieldY1 = document.getElementById("video-info-thumbnail-location-1");
			const fieldX2 = document.getElementById("video-info-thumbnail-location-2");
			const fieldY2 = document.getElementById("video-info-thumbnail-location-3");
			// 640x320 -> 1280x720
			fieldX1.value = Math.round(pos.x * 2);
			fieldY1.value = Math.round(pos.y * 2);
			fieldX2.value = Math.round((pos.x + pos.w) * 2);
			fieldY2.value = Math.round((pos.y + pos.h) * 2);
		});
	}

	updateTemplateCropWidgets();
	updateTemplateCropAspectRatio();
}

/**
 * Helper function to update the Jcrop widgets (creating them if needed) based
 * on the current values in the advanced template cropping text input fields.
 */
function updateTemplateCropWidgets() {
	const videoFieldX1 = document.getElementById("video-info-thumbnail-crop-0");
	const videoFieldY1 = document.getElementById("video-info-thumbnail-crop-1");
	const videoFieldX2 = document.getElementById("video-info-thumbnail-crop-2");
	const videoFieldY2 = document.getElementById("video-info-thumbnail-crop-3");
	// Video frame: 640x360 -> 1920x1080
	const videoFrameRect = Jcrop.Rect.create(
		videoFieldX1.value / 3,
		videoFieldY1.value / 3,
		(videoFieldX2.value - videoFieldX1.value) / 3,
		(videoFieldY2.value - videoFieldY1.value) / 3,
	);
	if (videoFrameStage.active == null) {
		videoFrameStage.newWidget(videoFrameRect);
	} else {
		videoFrameStage.active.pos = videoFrameRect;
		videoFrameStage.active.render();
	}

	const templateFieldX1 = document.getElementById("video-info-thumbnail-location-0");
	const templateFieldY1 = document.getElementById("video-info-thumbnail-location-1");
	const templateFieldX2 = document.getElementById("video-info-thumbnail-location-2");
	const templateFieldY2 = document.getElementById("video-info-thumbnail-location-3");
	// Template: 640x360 -> 1280x720
	const templateRect = Jcrop.Rect.create(
		templateFieldX1.value / 2,
		templateFieldY1.value / 2,
		(templateFieldX2.value - templateFieldX1.value) / 2,
		(templateFieldY2.value - templateFieldY1.value) / 2,
	);
	if (templateStage.active == null) {
		templateStage.newWidget(templateRect);
	} else {
		templateStage.active.pos = templateRect;
		templateStage.active.render();
	}

	updateTemplateCropAspectRatio();
}

function updateTemplateCropAspectRatio() {
	const aspectRatioCheckbox = document.getElementById("video-info-thumbnail-lock-aspect-ratio");
	if (aspectRatioCheckbox.checked) {
		const videoFieldX1 = document.getElementById("video-info-thumbnail-crop-0");
		const videoFieldY1 = document.getElementById("video-info-thumbnail-crop-1");
		const videoFieldX2 = document.getElementById("video-info-thumbnail-crop-2");
		const videoFieldY2 = document.getElementById("video-info-thumbnail-crop-3");
		const videoFieldAspectRatio =
			(videoFieldX2.value - videoFieldX1.value) / (videoFieldY2.value - videoFieldY1.value);
		videoFrameStage.setOptions({ aspectRatio: videoFieldAspectRatio });
		templateStage.setOptions({ aspectRatio: videoFieldAspectRatio });
	} else {
		videoFrameStage.setOptions({ aspectRatio: null });
		templateStage.setOptions({ aspectRatio: null });
	}
}
