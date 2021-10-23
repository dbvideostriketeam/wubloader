const TIME_FRAME_UTC = 1;
const TIME_FRAME_BUS = 2;
const TIME_FRAME_AGO = 3;

var globalLoadedVideoPlayer = false;
var globalVideoTimeReference = TIME_FRAME_AGO;

window.addEventListener("DOMContentLoaded", async (event) => {
	commonPageSetup();
	const timeSettingsForm = document.getElementById("stream-time-settings");
	timeSettingsForm.addEventListener("submit", (event) => {
		event.preventDefault();
		updateTimeSettings();
	});
	await loadDefaults();
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

	globalBusStartTime = new Date(defaultData.bustime_start);
}

// Gets the start time of the video from settings. Returns an invalid date object if the user entered bad data.
function getStartTime() {
	switch (globalVideoTimeReference) {
		case 1:
			return dateObjFromWubloaderTime(globalStartTimeString);
		case 2:
			return new Date(
				globalBusStartTime.getTime() + 1000 * parseInputTimeAsNumberOfSeconds(globalStartTimeString)
			);
		case 3:
			return new Date(
				new Date().getTime() - 1000 * parseInputTimeAsNumberOfSeconds(globalStartTimeString)
			);
	}
}

// Gets the end time of the video from settings. Returns null if there's no end time. Returns an invalid date object if the user entered bad data.
function getEndTime() {
	if (globalEndTimeString === "") {
		return null;
	}
	switch (globalVideoTimeReference) {
		case 1:
			return dateObjFromWubloaderTime(globalEndTimeString);
		case 2:
			return new Date(
				globalBusStartTime.getTime() + 1000 * parseInputTimeAsNumberOfSeconds(globalEndTimeString)
			);
		case 3:
			return new Date(
				new Date().getTime() - 1000 * parseInputTimeAsNumberOfSeconds(globalEndTimeString)
			);
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
	if (endTime && endTime < startTime) {
		addError(
			"End time is before the start time. This will prevent video loading and cause other problems."
		);
	}
}

function generateDownloadURL(startTime, endTime, downloadType, allowHoles, quality) {
	const startURLTime = getWubloaderTimeFromDate(startTime);
	const endURLTime = getWubloaderTimeFromDate(endTime);

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
