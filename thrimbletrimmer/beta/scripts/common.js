var globalBusStartTime = new Date("1970-01-01T00:00:00Z");
var globalStreamName = "";
var globalStartTimeString = 0;
var globalEndTimeString = 0;

const VIDEO_FRAMES_PER_SECOND = 30;

const TIME_FRAME_UTC = 1;
const TIME_FRAME_BUS = 2;
const TIME_FRAME_AGO = 3;

const PLAYBACK_RATES = [0.5, 1, 1.25, 1.5, 2];

function getVideoJS() {
	return videojs("video");
}

function addError(errorText) {
	const errorElement = document.createElement("div");
	errorElement.innerText = errorText;

	const dismissElement = document.createElement("a");
	dismissElement.classList.add("error-dismiss");
	dismissElement.innerText = "[X]";
	errorElement.appendChild(dismissElement);
	dismissElement.addEventListener("click", (event) => {
		const errorHost = document.getElementById("errors");
		errorHost.removeChild(errorElement);
	});

	const errorHost = document.getElementById("errors");
	errorHost.appendChild(errorElement);
}

function loadVideoPlayer(playlistURL) {
	let rangedPlaylistURL = assembleVideoPlaylistURL(playlistURL);

	let defaultOptions = {
		sources: [{ src: rangedPlaylistURL }],
		liveui: true,
		controls: true,
		autoplay: false,
		playbackRates: PLAYBACK_RATES,
		inactivityTimeout: 0,
		controlBar: {
			fullscreenToggle: true,
			volumePanel: {
				inline: false
			}
		}
	};

	const player = videojs("video", defaultOptions);
	player.ready(() => {
		player.volume(0.5); // Initialize to half volume
	});
}

function updateVideoPlayer(newPlaylistURL) {
	let rangedPlaylistURL = assembleVideoPlaylistURL(newPlaylistURL);
	const player = getVideoJS();
	player.src({ src: rangedPlaylistURL });
}

function updateStoredTimeSettings() {
	globalStreamName = document.getElementById("stream-time-setting-stream").value;
	globalStartTimeString = document.getElementById("stream-time-setting-start").value;
	globalEndTimeString = document.getElementById("stream-time-setting-end").value;
}

function parseInputTimeAsNumberOfSeconds(inputTime) {
	// We need to handle inputs like "-0:10:15" in a way that consistently makes the time negative.
	// Since we can't assign the negative sign to any particular part, we'll check for the whole thing here.
	let direction = 1;
	if (inputTime.startsWith("-")) {
		inputTime = inputTime.slice(1);
		direction = -1;
	}

	const parts = inputTime.split(":", 3);
	return (parseInt(parts[0]) + (parts[1] || 0) / 60 + (parts[2] || 0) / 3600) * 60 * 60 * direction;
}

function getSelectedTimeConversion() {
	const radioSelection = document.querySelectorAll("#stream-time-frame-of-reference > input");
	for (radioItem of radioSelection) {
		if (radioItem.checked) {
			return +radioItem.value;
		}
	}
	// This selection shouldn't ever become fully unchecked. We'll return the bus time by default
	// if it does because why not?
	return TIME_FRAME_BUS;
}

// Gets the start time of the video from settings. Returns an invalid date object if the user entered bad data.
function getStartTime() {
	switch (getSelectedTimeConversion()) {
		case 1:
			return new Date(globalStartTimeString + "Z");
		case 2:
			return new Date(globalBusStartTime.getTime() + (1000 * parseInputTimeAsNumberOfSeconds(globalStartTimeString)));
		case 3:
			return new Date(new Date().getTime() - (1000 * parseInputTimeAsNumberOfSeconds(globalStartTimeString)));
	}
}

// Gets the end time of the video from settings. Returns null if there's no end time. Returns an invalid date object if the user entered bad data.
function getEndTime() {
	if (globalEndTimeString === "") {
		return null;
	}
	switch (getSelectedTimeConversion()) {
		case 1:
			return new Date(globalEndTimeString + "Z");
		case 2:
			return new Date(globalBusStartTime.getTime() + (1000 * parseInputTimeAsNumberOfSeconds(globalEndTimeString)));
		case 3:
			return new Date(new Date().getTime() - (1000 * parseInputTimeAsNumberOfSeconds(globalEndTimeString)));
	}
}

function getWubloaderTimeFromDate(date) {
	if (!date) {
		return null;
	}
	return date.toISOString().substring(0, 19); // Trim milliseconds and "Z" marker
}

function assembleVideoPlaylistURL(basePlaylistURL) {
	let playlistURL = basePlaylistURL;
	
	let startTime = getStartTime();
	let endTime = getEndTime();

	let queryStringParts = [];
	if (startTime) {
		queryStringParts.push("start=" + getWubloaderTimeFromDate(startTime));
	}
	if (endTime) {
		queryStringParts.push("end=" + getWubloaderTimeFromDate(endTime));
	}
	if (queryStringParts) {
		playlistURL += "?" + queryStringParts.join("&");
	}
	return playlistURL;
}

function generateDownloadURL(startTime, endTime, downloadType, allowHoles) {
	const startURLTime = getWubloaderTimeFromDate(startTime);
	const endURLTime = getWubloaderTimeFromDate(endTime);

	const queryParts = ["start=" + startURLTime, "end=" + endURLTime, "type=" + downloadType, "allow_holes=" + allowHoles];

	const downloadURL = "/cut/" + globalStreamName + "/source.ts?" + queryParts.join("&");
	return downloadURL;
}
