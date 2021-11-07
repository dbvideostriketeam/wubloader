const TIME_FRAME_UTC = 1;
const TIME_FRAME_BUS = 2;
const TIME_FRAME_AGO = 3;

var globalLoadedVideoPlayer = false;
var globalVideoTimeReference = TIME_FRAME_AGO;

window.addEventListener("DOMContentLoaded", async (event) => {
	commonPageSetup();
	await loadDefaults();

	const timeSettingsForm = document.getElementById("stream-time-settings");
	timeSettingsForm.addEventListener("submit", (event) => {
		event.preventDefault();
		updateTimeSettings();
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

	updateTimeSettings();
});

async function loadDefaults() {
	const defaultDataResponse = await fetch("/thrimshim/defaults");
	if (!defaultDataResponse.ok) {
		addError(
			"Failed to load Thrimbletrimmer data. This probably means that everything is broken (or, possibly, just that the Wubloader host is down). Please sound the alarm."
		);
		return;
	}
	const defaultData = await defaultDataResponse.json();

	const streamNameField = document.getElementById("stream-time-setting-stream");
	streamNameField.value = defaultData.video_channel;

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

function updateTimeSettings() {
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
	if (endTime && endTime.diff(startTime).milliseconds < 0) {
		addError(
			"End time is before the start time. This will prevent video loading and cause other problems."
		);
	}
}

function generateDownloadURL(startTime, endTime, downloadType, allowHoles, quality) {
	const startURLTime = wubloaderTimeFromDateTime(startTime);
	const endURLTime = wubloaderTimeFromDateTime(endTime);

	const queryParts = [`type=${downloadType}`, `allow_holes=${allowHoles}`];
	if (startURLTime) {
		queryParts.push(`start=${startURLTime}`);
	}
	if (endURLTime) {
		queryParts.push(`end=${endURLTime}`);
	}

	const downloadURL = `/cut/${globalStreamName}/${quality}.ts?${queryParts.join("&")}`;
	return downloadURL;
}

function updateDownloadLink() {
	const downloadLink = document.getElementById("download");
	const downloadURL = generateDownloadURL(getStartTime(), getEndTime(), "rough", true, "source");
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
		"#time-converter input[name=time-converter-from]"
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
		"#time-converter input[name=time-converter-to]"
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
				`Failed to parse the time '${enteredTime}' as a value of the selected "convert from" time format.`
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
