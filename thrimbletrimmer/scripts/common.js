var DateTime = luxon.DateTime;
var Interval = luxon.Interval;
luxon.Settings.defaultZone = "utc";

var globalBusStartTime = DateTime.fromISO("1970-01-01T00:00:00");
var globalStreamName = "";
var globalStartTimeString = "";
var globalEndTimeString = "";

var globalPlayer = null;

Hls.DefaultConfig.maxBufferHole = 600;
Hls.DefaultConfig.debug = true;

const VIDEO_FRAMES_PER_SECOND = 30;

const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

function commonPageSetup() {
	if (!Hls.isSupported()) {
		addError(
			"Your browser doesn't support MediaSource extensions. Video playback and editing won't work."
		);
	}

	const helpLink = document.getElementById("editor-help-link");
	helpLink.addEventListener("click", toggleHelpDisplay);

	const closeHelp = document.getElementById("editor-help-box-close");
	closeHelp.addEventListener("click", (_event) => {
		const helpBox = document.getElementById("editor-help-box");
		helpBox.classList.add("hidden");
	});
}

function toggleHelpDisplay() {
	const helpBox = document.getElementById("editor-help-box");
	if (helpBox.classList.contains("hidden")) {
		const helpLink = document.getElementById("editor-help-link");
		helpBox.style.top = `${helpLink.offsetTop + helpLink.offsetHeight}px`;
		helpBox.classList.remove("hidden");
	} else {
		helpBox.classList.add("hidden");
	}
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

async function loadVideoPlayer(playlistURL) {
	let rangedPlaylistURL = assembleVideoPlaylistURL(playlistURL);
	const videoElement = document.getElementById("video");

	const volume = +(localStorage.getItem("volume") ?? 0.5);
	if (isNaN(volume)) {
		volume = 0.5;
	} else if (volume < 0) {
		volume = 0;
	} else if (volume > 1) {
		volume = 1;
	}
	videoElement.volume = volume;
	videoElement.addEventListener("volumechange", (_event) => {
		const newVolume = videoElement.volume;
		localStorage.setItem("volume", newVolume);
	});

	globalPlayer = new Hls();
	globalPlayer.attachMedia(video);
	return new Promise((resolve, _reject) => {
		globalPlayer.on(Hls.Events.MEDIA_ATTACHED, () => {
			globalPlayer.loadSource(rangedPlaylistURL);
			resolve();
		});
	});
}

async function loadVideoPlayerFromDefaultPlaylist() {
	const playlistURL = `/playlist/${globalStreamName}.m3u8`;
	await loadVideoPlayer(playlistURL);
}

function updateSegmentPlaylist() {
	globalPlayer.destroy();
	loadVideoPlayerFromDefaultPlaylist();
}

function parseHumanTimeStringAsDateTime(inputTime) {
	// We need to handle inputs like "-0:10:15" in a way that consistently makes the time negative.
	// Since we can't assign the negative sign to any particular part, we'll check for the whole thing here.
	let direction = 1;
	if (inputTime.startsWith("-")) {
		inputTime = inputTime.slice(1);
		direction = -1;
	}

	const parts = inputTime.split(":", 3);
	const hours = parseInt(parts[0]) * direction;
	const minutes = (parts[1] || 0) * direction;
	const seconds = (parts[2] || 0) * direction;
	return { hours: hours, minutes: minutes, seconds: seconds };
}

function dateTimeFromBusTime(busTime) {
	return globalBusStartTime.plus(parseHumanTimeStringAsDateTime(busTime));
}

function busTimeFromDateTime(dateTime) {
	const diff = dateTime.diff(globalBusStartTime);
	return formatIntervalForDisplay(diff);
}

function formatIntervalForDisplay(interval) {
	if (interval.milliseconds < 0) {
		const negativeInterval = interval.negate();
		return `-${negativeInterval.toFormat("hh:mm:ss.SSS")}`;
	}
	return interval.toFormat("hh:mm:ss.SSS");
}

function dateTimeFromWubloaderTime(wubloaderTime) {
	return DateTime.fromISO(wubloaderTime);
}

function wubloaderTimeFromDateTime(dateTime) {
	if (!dateTime) {
		return null;
	}
	// Not using ISO here because Luxon doesn't give us a quick way to print an ISO8601 string with no offset.
	return dateTime.toFormat("yyyy-LL-dd'T'HH:mm:ss.SSS");
}

function busTimeFromWubloaderTime(wubloaderTime) {
	const dt = dateTimeFromWubloaderTime(wubloaderTime);
	return busTimeFromDateTime(dt);
}

function assembleVideoPlaylistURL(basePlaylistURL) {
	let playlistURL = basePlaylistURL;

	const queryStringParts = startAndEndTimeQueryStringParts();
	if (queryStringParts) {
		playlistURL += "?" + queryStringParts.join("&");
	}
	return playlistURL;
}

function startAndEndTimeQueryStringParts() {
	const startTime = getStartTime();
	const endTime = getEndTime();

	let queryStringParts = [];
	if (startTime) {
		queryStringParts.push(`start=${wubloaderTimeFromDateTime(startTime)}`);
	}
	if (endTime) {
		queryStringParts.push(`end=${wubloaderTimeFromDateTime(endTime)}`);
	}
	return queryStringParts;
}
