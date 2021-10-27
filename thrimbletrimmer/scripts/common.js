var globalBusStartTime = new Date("1970-01-01T00:00:00Z");
var globalStreamName = "";
var globalStartTimeString = "";
var globalEndTimeString = "";

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
		liveui: true,
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

function updateSegmentPlaylist() {
	const playlistURL = `/playlist/${globalStreamName}.m3u8`;
	updateVideoPlayer(playlistURL);
}

function updateVideoPlayer(newPlaylistURL) {
	let rangedPlaylistURL = assembleVideoPlaylistURL(newPlaylistURL);
	const player = getVideoJS();
	player.src({ src: rangedPlaylistURL });
}

function dateObjFromBusTime(busTime) {
	// We need to handle inputs like "-0:10:15" in a way that consistently makes the time negative.
	// Since we can't assign the negative sign to any particular part, we'll check for the whole thing here.
	let direction = 1;
	if (busTime.startsWith("-")) {
		busTime = busTime.slice(1);
		direction = -1;
	}

	const parts = busTime.split(":", 3);
	const hours = (parts[0] || 0) * direction;
	const minutes = (parts[1] || 0) * direction;
	const seconds = (parts[2] || 0) * direction;
	const time = new Date(globalBusStartTime);
	time.setHours(time.getHours() + hours);
	time.setMinutes(time.getMinutes() + minutes);
	time.setSeconds(time.getSeconds() + seconds);
	return time;
}

function dateObjFromWubloaderTime(wubloaderTime) {
	return new Date(`${wubloaderTime}Z`);
}

function wubloaderTimeFromDateObj(date) {
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
		queryStringParts.push(`start=${wubloaderTimeFromDateObj(startTime)}`);
	}
	if (endTime) {
		queryStringParts.push(`end=${wubloaderTimeFromDateObj(endTime)}`);
	}
	return queryStringParts;
}
