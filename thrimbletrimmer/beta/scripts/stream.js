var globalLoadedVideoPlayer = false;

// Here's all the stuff that runs immediately when the page is loaded.
window.addEventListener("DOMContentLoaded", async (event) => {
	const timeSettingsForm = document.getElementById("stream-time-settings");
	timeSettingsForm.addEventListener("submit", (event) => {
		event.preventDefault();
		updateTimeSettings();
	});
	await loadDefaults();
	updateTimeSettings();

	const helpLink = document.getElementById("keyboard-help");
	helpLink.addEventListener("click", toggleHelpDisplay);
});

async function loadDefaults() {
	// TODO: Remove this comment from this file. For a particular video, /thrimshim/<video-id>
	const defaultDataResponse = await fetch("/thrimshim/defaults");
	if (!defaultDataResponse.ok) {
		addError("Failed to load Thrimbletrimmer data. This probably means that everything is broken (or, possibly, just that the Wubloader host is down). Please sound the alarm.");
		return;
	}
	const defaultData = await defaultDataResponse.json();

	const streamNameField = document.getElementById("stream-time-setting-stream");
	streamNameField.value = defaultData.video_channel;

	globalBusStartTime = new Date(defaultData.bustime_start);
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
}

function loadVideoPlayerFromDefaultPlaylist() {
	const playlistURL = "/playlist/" + globalStreamName + ".m3u8";
	loadVideoPlayer(playlistURL);
}

function updateSegmentPlaylist() {
	const playlistURL = "/playlist/" + globalStreamName + ".m3u8";
	updateVideoPlayer(playlistURL);
}

function toggleHelpDisplay() {
	const helpBox = document.getElementById("keyboard-help-box");
	if (helpBox.classList.contains("hidden")) {
		const helpLink = document.getElementById("keyboard-help");
		helpBox.style.top = (helpLink.offsetTop + helpLink.offsetHeight) + "px";
		helpBox.classList.remove("hidden");
	} else {
		helpBox.classList.add("hidden");
	}
}

function updateDownloadLink() {
	const downloadLink = document.getElementById("download");
	const downloadURL = generateDownloadURL(getStartTime(), getEndTime(), "rough", true);
	downloadLink.href = downloadURL;
}