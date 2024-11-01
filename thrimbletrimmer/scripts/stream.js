const TIME_FRAME_UTC = 1;
const TIME_FRAME_BUS = 2;
const TIME_FRAME_AGO = 3;

var globalLoadedVideoPlayer = false;
var globalVideoTimeReference = TIME_FRAME_AGO;
var globalChatPreviousRenderTime = null;

window.addEventListener("DOMContentLoaded", async (event) => {
	commonPageSetup();
	globalLoadChatWorker.onmessage = (event) => {
		updateChatDataFromWorkerResponse(event.data);
		initialChatRender();
	};

	const queryParams = new URLSearchParams(window.location.search);
	if (queryParams.has("start")) {
		document.getElementById("stream-time-frame-of-reference-utc").checked = true;
		document.getElementById("stream-time-setting-start").value = queryParams.get("start");
		if (queryParams.has("end")) {
			document.getElementById("stream-time-setting-end").value = queryParams.get("end");
		}
	}
	if (queryParams.has("stream")) {
		document.getElementById("stream-time-setting-stream").value = queryParams.get("stream");
	}

	await loadDefaults();

	const timeSettingsForm = document.getElementById("stream-time-settings");
	timeSettingsForm.addEventListener("submit", (event) => {
		event.preventDefault();
		updateTimeSettings();
	});

	document.getElementById("download-frame").addEventListener("click", (_event) => {
		downloadFrame();
	});

	const timeConversionForm = document.getElementById("time-converter");
	timeConversionForm.addEventListener("submit", (event) => {
		event.preventDefault();
		convertEnteredTimes();
	});

	const timeConversionLink = document.getElementById("time-converter-link");
	timeConversionLink.addEventListener("click", (_event) => {
		const timeConversionForm = document.getElementById("time-converter");
		timeConversionForm.classList.toggle("hidden");
	});

	const addTimeConversionButton = document.getElementById("time-converter-add-time");
	addTimeConversionButton.addEventListener("click", (_event) => {
		const newField = document.createElement("input");
		newField.classList.add("time-converter-time");
		newField.type = "text";
		newField.placeholder = "Time to convert";
		const container = document.getElementById("time-converter-time-container");
		container.appendChild(newField);
	});

	await updateTimeSettings();

	const videoPlayer = document.getElementById("video");
	videoPlayer.addEventListener("loadedmetadata", (_event) => initialChatRender());
	videoPlayer.addEventListener("timeupdate", (_event) => updateChatRender());
});

async function loadDefaults() {
	const defaultDataResponse = await fetch("/thrimshim/defaults");
	if (!defaultDataResponse.ok) {
		addError(
			"Failed to load Thrimbletrimmer data. This probably means that everything is broken (or, possibly, just that the Wubloader host is down). Please sound the alarm.",
		);
		return;
	}
	const defaultData = await defaultDataResponse.json();

	const streamNameField = document.getElementById("stream-time-setting-stream");
	if (streamNameField.value === "") {
		streamNameField.value = defaultData.video_channel;
	}

	globalBusStartTime = DateTime.fromISO(defaultData.bustime_start);
}

// Gets the start time of the video from settings. Returns an invalid date object if the user entered bad data.
function getStartTime() {
	return dateTimeFromTimeString(globalStartTimeString, globalVideoTimeReference);
}

// Gets the end time of the video from settings. Returns null if there's no end time. Returns an invalid date object if the user entered bad data.
function getEndTime() {
	if (globalEndTimeString === "") {
		return null;
	}
	return dateTimeFromTimeString(globalEndTimeString, globalVideoTimeReference);
}

function dateTimeFromTimeString(timeString, timeStringFormat) {
	switch (timeStringFormat) {
		case 1:
			return dateTimeFromWubloaderTime(timeString);
		case 2:
			return dateTimeFromBusTime(timeString);
		case 3:
			return DateTime.now().setZone("utc").minus(dateTimeMathObjectFromBusTime(timeString));
	}
}

async function updateTimeSettings() {
	updateStoredTimeSettings();
	if (globalLoadedVideoPlayer) {
		updateSegmentPlaylist();
	} else {
		loadVideoPlayerFromDefaultPlaylist();
		globalLoadedVideoPlayer = true;
	}

	updateDownloadLink();

	const startTime = getStartTime();
	const endTime = getEndTime();
	const query = new URLSearchParams({
		stream: globalStreamName,
		start: wubloaderTimeFromDateTime(startTime),
	});
	if (endTime) {
		query.append("end", wubloaderTimeFromDateTime(endTime));
	}
	document.getElementById("stream-time-link").href = `?${query}`;
}

function generateDownloadURL(startTime, endTime, downloadType, allowHoles, quality) {
	const startURLTime = wubloaderTimeFromDateTime(startTime);
	const endURLTime = wubloaderTimeFromDateTime(endTime);

	const query = new URLSearchParams({
		type: downloadType,
		allow_holes: allowHoles,
	});
	if (startURLTime) {
		query.append("start", startURLTime);
	}
	if (endURLTime) {
		query.append("end", endURLTime);
	}

	const downloadURL = `/cut/${globalStreamName}/${quality}.ts?${query}`;
	return downloadURL;
}

function updateDownloadLink() {
	const downloadLink = document.getElementById("download");
	const downloadURL = generateDownloadURL(getStartTime(), getEndTime(), "smart", true, "source");
	downloadLink.href = downloadURL;
}

function updateStoredTimeSettings() {
	globalStreamName = document.getElementById("stream-time-setting-stream").value;
	globalStartTimeString = document.getElementById("stream-time-setting-start").value;
	globalEndTimeString = document.getElementById("stream-time-setting-end").value;

	const radioSelection = document.querySelectorAll("#stream-time-frame-of-reference > input");
	for (radioItem of radioSelection) {
		if (radioItem.checked) {
			globalVideoTimeReference = +radioItem.value;
			break;
		}
	}
}

function convertEnteredTimes() {
	let timeConvertFrom = undefined;
	const timeConvertFromSelection = document.querySelectorAll(
		"#time-converter input[name=time-converter-from]",
	);
	for (const convertFromItem of timeConvertFromSelection) {
		if (convertFromItem.checked) {
			timeConvertFrom = +convertFromItem.value;
			break;
		}
	}
	if (!timeConvertFrom) {
		addError("Failed to convert times - input format not specified");
		return;
	}

	let timeConvertTo = undefined;
	const timeConvertToSelection = document.querySelectorAll(
		"#time-converter input[name=time-converter-to]",
	);
	for (const convertToItem of timeConvertToSelection) {
		if (convertToItem.checked) {
			timeConvertTo = +convertToItem.value;
			break;
		}
	}
	if (!timeConvertTo) {
		addError("Failed to convert times - output format not specified");
		return;
	}

	const timeFieldList = document.getElementsByClassName("time-converter-time");
	const now = DateTime.now().setZone("utc");
	for (const timeField of timeFieldList) {
		const enteredTime = timeField.value;
		if (enteredTime === "") {
			continue;
		}

		let time = dateTimeFromTimeString(enteredTime, timeConvertFrom);
		if (!time) {
			addError(
				`Failed to parse the time '${enteredTime}' as a value of the selected "convert from" time format.`,
			);
			continue;
		}

		if (timeConvertTo === TIME_FRAME_UTC) {
			timeField.value = wubloaderTimeFromDateTime(time);
		} else if (timeConvertTo === TIME_FRAME_BUS) {
			timeField.value = busTimeFromDateTime(time);
		} else if (timeConvertTo === TIME_FRAME_AGO) {
			const difference = now.diff(time);
			timeField.value = formatIntervalForDisplay(difference);
		}
	}

	if (timeConvertTo === TIME_FRAME_UTC) {
		document.getElementById("time-converter-from-utc").checked = true;
	} else if (timeConvertTo === TIME_FRAME_BUS) {
		document.getElementById("time-converter-from-bus").checked = true;
	} else if (timeConvertTo === TIME_FRAME_AGO) {
		document.getElementById("time-converter-from-ago").checked = true;
	}
}

function initialChatRender() {
	if (!globalChatData || globalChatData.length === 0) {
		return;
	}
	const videoPlayer = document.getElementById("video");
	const videoTime = videoPlayer.currentTime;
	const videoDateTime = dateTimeFromVideoPlayerTime(videoTime);
	const chatReplayContainer = document.getElementById("chat-replay");
	chatReplayContainer.innerHTML = "";

	for (const chatMessage of globalChatData) {
		if (chatMessage.when > videoDateTime) {
			break;
		}
		handleChatMessage(chatReplayContainer, chatMessage);
	}

	globalChatPreviousRenderTime = videoTime;
	chatReplayContainer.scrollTop = chatReplayContainer.scrollHeight;
}

function updateChatRender() {
	if (!globalChatData || globalChatData.length === 0) {
		return;
	}
	if (!hasSegmentList()) {
		// The update is due to a stream refresh, so we'll wait for the initial render instead
		return;
	}
	const videoPlayer = document.getElementById("video");
	const videoTime = videoPlayer.currentTime;
	const chatReplayContainer = document.getElementById("chat-replay");
	const wasScrolledToBottom =
		chatReplayContainer.scrollTop + chatReplayContainer.offsetHeight >=
		chatReplayContainer.scrollHeight;

	if (videoTime < globalChatPreviousRenderTime) {
		initialChatRender();
	} else {
		const videoDateTime = dateTimeFromVideoPlayerTime(videoTime);
		const lastAddedTime = dateTimeFromVideoPlayerTime(globalChatPreviousRenderTime);

		let rangeMin = 0;
		let rangeMax = globalChatData.length;
		let lastChatIndex = Math.floor((rangeMin + rangeMax) / 2);
		while (rangeMax - rangeMin > 1) {
			if (globalChatData[lastChatIndex].when === lastAddedTime) {
				break;
			}
			if (globalChatData[lastChatIndex].when < lastAddedTime) {
				rangeMin = lastChatIndex;
			} else {
				rangeMax = lastChatIndex;
			}
			lastChatIndex = Math.floor((rangeMin + rangeMax) / 2);
		}

		if (lastChatIndex === 0 && globalChatData[0].when > lastAddedTime) {
			lastChatIndex = -1;
		}

		for (let chatIndex = lastChatIndex + 1; chatIndex < globalChatData.length; chatIndex++) {
			const chatMessage = globalChatData[chatIndex];
			if (chatMessage.when > videoDateTime) {
				break;
			}
			handleChatMessage(chatReplayContainer, chatMessage);
		}
	}
	globalChatPreviousRenderTime = videoTime;
	if (wasScrolledToBottom) {
		chatReplayContainer.scrollTop = chatReplayContainer.scrollHeight;
	}
}

function handleChatMessage(chatReplayContainer, chatMessage) {
	if (chatMessage.message.command === "PRIVMSG") {
		const chatDOM = renderChatMessage(chatMessage);
		if (chatDOM) {
			chatReplayContainer.appendChild(chatDOM);
		}
	} else if (chatMessage.message.command === "CLEARMSG") {
		const removedID = chatMessage.message.tags["target-msg-id"];
		const targetMessageElem = document.getElementById(`chat-replay-message-${removedID}`);
		if (targetMessageElem) {
			targetMessageElem.classList.add("chat-replay-message-cleared");
		}
	} else if (chatMessage.message.command === "CLEARCHAT") {
		if (chatMessage.message.params.length > 1) {
			const removedSender = chatMessage.message.params[1];
			for (const messageElem of chatReplayContainer.children) {
				if (messageElem.dataset.sender === removedSender) {
					messageElem.classList.add("chat-replay-message-cleared");
				}
			}
		} else {
			for (const messageElem of chatReplayContainer.children) {
				messageElem.classList.add("chat-replay-message-cleared");
			}
		}
	} else if (chatMessage.message.command === "USERNOTICE") {
		const chatDOMList = renderSystemMessages(chatMessage);
		for (const chatDOM of chatDOMList) {
			chatReplayContainer.appendChild(chatDOM);
		}
	}
}
