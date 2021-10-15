var globalBusStartTime = new Date("1970-01-01T00:00:00Z");
var globalStreamName = "";
var globalStartTimeString = 0;
var globalEndTimeString = 0;

const VIDEO_FRAMES_PER_SECOND = 30;

const PLAYBACK_RATES = [0.5, 1, 1.25, 1.5, 2];

function commonPageSetup() {
	const helpLink = document.getElementById("editor-help-link");
	helpLink.addEventListener("click", toggleHelpDisplay);
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

function getVideoJS() {
	return videojs.getPlayer("video");
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

	let defaultOptions = {
		sources: [{ src: rangedPlaylistURL }],
		liveui: false,
		controls: true,
		autoplay: false,
		playbackRates: PLAYBACK_RATES,
		inactivityTimeout: 0,
		controlBar: {
			fullscreenToggle: true,
			volumePanel: {
				inline: false,
			},
		},
	};

	const player = videojs("video", defaultOptions);
	return new Promise((resolve, reject) => {
		player.ready(() => {
			player.volume(0.5); // Initialize to half volume
			resolve();
		});
	});
}

async function loadVideoPlayerFromDefaultPlaylist() {
	const playlistURL = `/playlist/${globalStreamName}.m3u8`;
	await loadVideoPlayer(playlistURL);
}

function updateVideoPlayer(newPlaylistURL) {
	let rangedPlaylistURL = assembleVideoPlaylistURL(newPlaylistURL);
	const player = getVideoJS();
	player.src({ src: rangedPlaylistURL });
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

function getWubloaderTimeFromDate(date) {
	if (!date) {
		return null;
	}
	return date.toISOString().substring(0, 19); // Trim milliseconds and "Z" marker
}

function getWubloaderTimeFromDateWithMilliseconds(date) {
	if (!date) {
		return null;
	}
	return date.toISOString().substring(0, 23); // Trim "Z" marker and smaller than milliseconds
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
		queryStringParts.push(`start=${getWubloaderTimeFromDate(startTime)}`);
	}
	if (endTime) {
		queryStringParts.push(`end=${getWubloaderTimeFromDate(endTime)}`);
	}
	return queryStringParts;
}

function generateDownloadURL(startTime, endTime, downloadType, allowHoles, quality) {
	const startURLTime = getWubloaderTimeFromDate(startTime);
	const endURLTime = getWubloaderTimeFromDate(endTime);

	const queryParts = [
		`start=${startURLTime}`,
		`end=${endURLTime}`,
		`type=${downloadType}`,
		`allow_holes=${allowHoles}`,
	];

	const downloadURL = `/cut/${globalStreamName}/${quality}.ts?${queryParts.join("&")}`;
	return downloadURL;
}
