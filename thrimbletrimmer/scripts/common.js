var DateTime = luxon.DateTime;
var Interval = luxon.Interval;
luxon.Settings.defaultZone = "utc";

var globalBusStartTime = DateTime.fromISO("1970-01-01T00:00:00");
var globalStreamName = "";
var globalStartTimeString = "";
var globalEndTimeString = "";

var globalPlayer = null;
var globalSetUpControls = false;
var globalSeekTimer = null;

var globalChatData = [];

Hls.DefaultConfig.maxBufferHole = 600;

const VIDEO_FRAMES_PER_SECOND = 30;

const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

function commonPageSetup() {
	if (!Hls.isSupported()) {
		addError(
			"Your browser doesn't support MediaSource extensions. Video playback and editing won't work."
		);
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

	videoElement.addEventListener("loadedmetadata", (_event) => {
		setUpVideoControls();
	});

	videoElement.addEventListener("loadeddata", (_event) => {
		const qualitySelector = document.getElementById("video-controls-quality");
		globalPlayer.currentLevel = +qualitySelector.value;
	});

	globalPlayer = new Hls();
	globalPlayer.attachMedia(video);
	return new Promise((resolve, _reject) => {
		globalPlayer.on(Hls.Events.MEDIA_ATTACHED, () => {
			const startTime = getStartTime();
			const endTime = getEndTime();
			if (endTime && endTime.diff(startTime).milliseconds < 0) {
				addError(
					"End time is before the start time. This will prevent video loading and cause other problems."
				);
			}
			globalPlayer.loadSource(rangedPlaylistURL);

			globalPlayer.on(Hls.Events.ERROR, (_event, data) => {
				if (data.fatal) {
					switch (data.type) {
						case Hls.ErrorTypes.NETWORK_ERROR:
							if (data.reason === "no level found in manifest") {
								addError(
									"There is no video data between the specified start and end times. Change the times so that there is video content to play."
								);
							} else {
								console.log("A fatal network error occurred; retrying", data);
								globalPlayer.startLoad();
							}
							break;
						case Hls.ErrorTypes.MEDIA_ERROR:
							console.log("A fatal media error occurred; retrying", data);
							globalPlayer.recoverMediaError();
							break;
						default:
							console.log("A fatal error occurred; resetting video player", data);
							addError(
								"Some sort of video player error occurred. Thrimbletrimmer is resetting the video player."
							);
							resetVideoPlayer();
					}
				} else {
					console.log("A non-fatal video player error occurred; HLS.js will retry", data);
				}
			});

			resolve();
		});
	});
}

async function loadVideoPlayerFromDefaultPlaylist() {
	const playlistURL = `/playlist/${globalStreamName}.m3u8`;
	await loadVideoPlayer(playlistURL);
}

function resetVideoPlayer() {
	updateSegmentPlaylist();
}

function updateSegmentPlaylist() {
	const videoElement = document.getElementById("video");
	const currentPlaybackRate = videoElement.playbackRate;
	globalPlayer.destroy();
	loadVideoPlayerFromDefaultPlaylist();
	// The playback rate isn't maintained when destroying and reattaching hls.js
	videoElement.playbackRate = currentPlaybackRate;
}

function setUpVideoControls() {
	// Setting this up so it's removed from the event doesn't work; loadedmetadata fires twice anyway.
	// We still need to prevent double-setup, so here we are.
	if (globalSetUpControls) {
		return;
	}
	globalSetUpControls = true;

	const videoElement = document.getElementById("video");

	const playPauseButton = document.getElementById("video-controls-play-pause");
	if (videoElement.paused) {
		playPauseButton.src = "images/video-controls/play.png";
	} else {
		playPauseButton.src = "images/video-controls/pause.png";
	}

	const togglePlayState = (_event) => {
		if (videoElement.paused) {
			videoElement.play();
		} else {
			videoElement.pause();
		}
	};
	playPauseButton.addEventListener("click", togglePlayState);
	videoElement.addEventListener("click", (event) => {
		if (!videoElement.controls) {
			togglePlayState(event);
		}
	});

	videoElement.addEventListener("play", (_event) => {
		playPauseButton.src = "images/video-controls/pause.png";
	});
	videoElement.addEventListener("pause", (_event) => {
		playPauseButton.src = "images/video-controls/play.png";
	});

	const currentTime = document.getElementById("video-controls-current-time");
	currentTime.innerText = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	videoElement.addEventListener("timeupdate", (_event) => {
		currentTime.innerText = videoHumanTimeFromVideoPlayerTime(videoElement.currentTime);
	});

	const duration = document.getElementById("video-controls-duration");
	duration.innerText = videoHumanTimeFromVideoPlayerTime(videoElement.duration);
	videoElement.addEventListener("durationchange", (_event) => {
		duration.innerText = videoHumanTimeFromVideoPlayerTime(videoElement.duration);
	});

	const volumeMuted = document.getElementById("video-controls-volume-mute");
	if (videoElement.muted) {
		volumeMuted.src = "images/video-controls/volume-mute.png";
	} else {
		volumeMuted.src = "images/video-controls/volume.png";
	}
	const volumeLevel = document.getElementById("video-controls-volume-level");
	const defaultVolume = +(localStorage.getItem("volume") ?? 0.5);
	if (isNaN(defaultVolume)) {
		defaultVolume = 0.5;
	} else if (defaultVolume < 0) {
		defaultVolume = 0;
	} else if (defaultVolume > 1) {
		defaultVolume = 1;
	}
	videoElement.volume = defaultVolume;
	volumeLevel.value = videoElement.volume;

	volumeMuted.addEventListener("click", (_event) => {
		videoElement.muted = !videoElement.muted;
	});
	volumeLevel.addEventListener("click", (event) => {
		videoElement.volume = event.offsetX / event.target.offsetWidth;
		videoElement.muted = false;
	});
	videoElement.addEventListener("volumechange", (_event) => {
		if (videoElement.muted) {
			volumeMuted.src = "images/video-controls/volume-mute.png";
		} else {
			volumeMuted.src = "images/video-controls/volume.png";
		}
		volumeLevel.value = videoElement.volume;
		localStorage.setItem("volume", videoElement.volume);
	});

	const playbackSpeed = document.getElementById("video-controls-playback-speed");
	for (const speed of PLAYBACK_RATES) {
		const speedOption = document.createElement("option");
		speedOption.value = speed;
		speedOption.innerText = `${speed}x`;
		if (speed === 1) {
			speedOption.selected = true;
		}
		playbackSpeed.appendChild(speedOption);
	}
	playbackSpeed.addEventListener("change", (_event) => {
		const speed = +playbackSpeed.value;
		videoElement.playbackRate = speed;
	});

	const quality = document.getElementById("video-controls-quality");
	const defaultQuality = localStorage.getItem("quality");
	for (const [qualityIndex, qualityLevel] of globalPlayer.levels.entries()) {
		const qualityOption = document.createElement("option");
		qualityOption.value = qualityIndex;
		qualityOption.innerText = qualityLevel.name;
		if (qualityLevel.name === defaultQuality) {
			qualityOption.selected = true;
		}
		quality.appendChild(qualityOption);
	}
	localStorage.setItem("quality", quality.options[quality.options.selectedIndex].innerText);
	quality.addEventListener("change", (_event) => {
		globalPlayer.currentLevel = +quality.value;
		localStorage.setItem("quality", quality.options[quality.options.selectedIndex].innerText);
	});

	const fullscreen = document.getElementById("video-controls-fullscreen");
	fullscreen.addEventListener("click", (_event) => {
		if (document.fullscreenElement) {
			document.exitFullscreen();
		} else {
			videoElement.requestFullscreen();
		}
	});
	videoElement.addEventListener("fullscreenchange", (_event) => {
		if (document.fullscreenElement) {
			videoElement.controls = true;
		} else {
			videoElement.controls = false;
		}
	});

	const playbackPosition = document.getElementById("video-controls-playback-position");
	playbackPosition.max = videoElement.duration;
	playbackPosition.value = videoElement.currentTime;
	videoElement.addEventListener("durationchange", (_event) => {
		playbackPosition.max = videoElement.duration;
	});
	videoElement.addEventListener("timeupdate", (_event) => {
		playbackPosition.value = videoElement.currentTime;
	});
	playbackPosition.addEventListener("click", (event) => {
		const newPosition = (event.offsetX / event.target.offsetWidth) * videoElement.duration;
		videoElement.currentTime = newPosition;
		playbackPosition.value = newPosition;
	});

	/* Sometimes a mysterious issue occurs loading segments of the video when seeking.
	 * When this happens, twiddling the qualities tends to fix it. Here, we attempt to
	 * detect this situation and fix it automatically.
	 */
	videoElement.addEventListener("seeking", (_event) => {
		// If we don't get a "seeked" event soon after the "seeking" event, we assume there's
		// a loading error.
		// To handle this, we set up a timed handler to pick this up.
		if (globalSeekTimer !== null) {
			clearTimeout(globalSeekTimer);
			globalSeekTimer = null;
		}
		globalSeekTimer = setTimeout(() => {
			const currentLevel = globalPlayer.currentLevel;
			globalPlayer.currentLevel = -1;
			globalPlayer.currentLevel = currentLevel;
		}, 500);
	});
	videoElement.addEventListener("seeked", (_event) => {
		// Since we got the seek, cancel the timed twiddling of qualities
		if (globalSeekTimer !== null) {
			clearTimeout(globalSeekTimer);
			globalSeekTimer = null;
		}
	});
}

function dateTimeMathObjectFromBusTime(busTime) {
	// We need to handle inputs like "-0:10:15" in a way that consistently makes the time negative.
	// Since we can't assign the negative sign to any particular part, we'll check for the whole thing here.
	let direction = 1;
	if (busTime.startsWith("-")) {
		busTime = busTime.slice(1);
		direction = -1;
	}

	const parts = busTime.split(":", 3);
	const hours = parseInt(parts[0]) * direction;
	const minutes = (parts[1] || 0) * direction;
	const seconds = (parts[2] || 0) * direction;
	return { hours: hours, minutes: minutes, seconds: seconds };
}

function dateTimeFromBusTime(busTime) {
	return globalBusStartTime.plus(dateTimeMathObjectFromBusTime(busTime));
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
	if (wubloaderTime === "") {
		return "";
	}
	const dt = dateTimeFromWubloaderTime(wubloaderTime);
	return busTimeFromDateTime(dt);
}

function videoHumanTimeFromVideoPlayerTime(videoPlayerTime) {
	const hours = Math.floor(videoPlayerTime / 3600);
	let minutes = Math.floor((videoPlayerTime % 3600) / 60);
	let seconds = Math.floor(videoPlayerTime % 60);
	let milliseconds = Math.floor((videoPlayerTime * 1000) % 1000);

	while (minutes.toString().length < 2) {
		minutes = `0${minutes}`;
	}
	while (seconds.toString().length < 2) {
		seconds = `0${seconds}`;
	}
	while (milliseconds.toString().length < 3) {
		milliseconds = `0${milliseconds}`;
	}

	if (hours > 0) {
		return `${hours}:${minutes}:${seconds}.${milliseconds}`;
	}
	return `${minutes}:${seconds}.${milliseconds}`;
}

function videoPlayerTimeFromVideoHumanTime(videoHumanTime) {
	let timeParts = videoHumanTime.split(":", 3);
	let hours;
	let minutes;
	let seconds;

	if (timeParts.length < 2) {
		hours = 0;
		minutes = 0;
		seconds = +timeParts[0];
	} else if (timeParts.length < 3) {
		hours = 0;
		minutes = parseInt(timeParts[0]);
		seconds = +timeParts[1];
	} else {
		hours = parseInt(timeParts[0]);
		minutes = parseInt(timeParts[1]);
		seconds = +timeParts[2];
	}
	if (isNaN(hours) || isNaN(minutes) || isNaN(seconds)) {
		return null;
	}

	return hours * 3600 + minutes * 60 + seconds;
}

function dateTimeFromVideoPlayerTime(videoPlayerTime) {
	const segmentList = getSegmentList();
	let segmentStartTime;
	let segmentStartISOTime;
	for (const segment of segmentList) {
		const segmentEndTime = segment.start + segment.duration;
		if (videoPlayerTime >= segment.start && videoPlayerTime < segmentEndTime) {
			segmentStartTime = segment.start;
			segmentStartISOTime = segment.rawProgramDateTime;
			break;
		}
	}
	if (segmentStartISOTime === undefined) {
		return null;
	}
	const wubloaderDateTime = DateTime.fromISO(segmentStartISOTime);
	const offset = videoPlayerTime - segmentStartTime;
	return wubloaderDateTime.plus({ seconds: offset });
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

function videoHumanTimeFromDateTime(dateTime) {
	const videoPlayerTime = videoPlayerTimeFromDateTime(dateTime);
	if (videoPlayerTime === null) {
		return null;
	}
	return videoHumanTimeFromVideoPlayerTime(videoPlayerTime);
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

function getSegmentList() {
	return globalPlayer.latencyController.levelDetails.fragments;
}

function hasSegmentList() {
	if (
		globalPlayer &&
		globalPlayer.latencyController &&
		globalPlayer.latencyController.levelDetails &&
		globalPlayer.latencyController.levelDetails.fragments
	) {
		return true;
	}
	return false;
}

function downloadFrame() {
	const videoElement = document.getElementById("video");
	const dateTime = dateTimeFromVideoPlayerTime(videoElement.currentTime);
	const url = `/frame/${globalStreamName}/source.png?timestamp=${wubloaderTimeFromDateTime(
		dateTime
	)}`;
	// Avoid : as it causes problems on Windows
	const filename = `${dateTime.toFormat("yyyy-LL-dd'T'HH-mm-ss.SSS")}.png`;
	triggerDownload(url, filename);
}

function triggerDownload(url, filename) {
	// URL must be same-origin.
	const link = document.createElement("a");
	link.setAttribute("download", filename);
	link.href = url;
	link.setAttribute("target", "_blank");
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
}

async function getChatLog(startWubloaderTime, endWubloaderTime) {
	globalChatData = [];
	const url = `/${globalStreamName}/chat.json?start=${startWubloaderTime}&end=${endWubloaderTime}`;
	const response = await fetch(url);
	if (!response.ok) {
		return;
	}
	const chatLogData = await response.json();
	for (const chatLine of chatLogData) {
		if (
			chatLine.command !== "PRIVMSG" &&
			chatLine.command !== "CLEARMSG" &&
			chatLine.command !== "CLEARCHAT"
		) {
			continue;
		}
		const when = DateTime.fromSeconds(chatLine.time);
		// Here, we just push each line successively into the list. This assumes data is provided to us in chronological order.
		globalChatData.push({ message: chatLine, when: when });
	}
}

function renderChatMessage(chatMessageData) {
	const chatMessage = chatMessageData.message;
	if (chatMessage.command !== "PRIVMSG" || chatMessage.params[0] !== `#${globalStreamName}`) {
		return null;
	}

	const sendTimeElement = document.createElement("div");
	sendTimeElement.classList.add("chat-replay-message-time");
	const messageTime = videoHumanTimeFromDateTime(chatMessageData.when);
	sendTimeElement.innerText = messageTime;

	var displayName = "";
	if (chatMessage.tags.hasOwnProperty("display-name")) {
		displayName = chatMessage.tags["display-name"];
	} else {
		displayName = chatMessage.sender;
	}

	const senderNameElement = document.createElement("div");
	senderNameElement.classList.add("chat-replay-message-sender");
	if (chatMessage.tags.hasOwnProperty("color")) {
		senderNameElement.style.color = chatMessage.tags.color;
	}
	senderNameElement.innerText = displayName;

	const messageTextElement = document.createElement("div");
	messageTextElement.classList.add("chat-replay-message-text");

	if (chatMessage.tags.hasOwnProperty("reply-parent-msg-id")) {
		const replyParentID = chatMessage.tags["reply-parent-msg-id"];
		const replyParentSender = chatMessage.tags["reply-parent-display-name"];
		let replyParentMessageText = chatMessage.tags["reply-parent-msg-body"];
		const replyContainer = document.createElement("div");
		const replyTextContainer = document.createElement("a");

		if (replyParentMessageText.startsWith("\u0001ACTION")) {
			replyContainer.classList.add("chat-replay-message-text-action");
			const substringEnd = (replyParentMessageText.endsWith("\u0001") ? replyParentMessageText.length - 1 : replyParentMessageText);
			replyParentMessageText = replyParentMessageText.substring(7, substringEnd);
		}

		replyTextContainer.href = `#chat-replay-message-${replyParentID}`;
		replyTextContainer.innerText = `Replying to ${replyParentSender}: ${replyParentMessageText}`;
		replyContainer.appendChild(replyTextContainer);
		replyContainer.classList.add("chat-replay-message-reply");
		messageTextElement.appendChild(replyContainer);
	}

	let chatMessageText = chatMessage.params[1];
	if (chatMessageText.startsWith("\u0001ACTION")) {
		messageTextElement.classList.add("chat-replay-message-text-action");
		const substringEnd = (chatMessageText.endsWith("\u0001") ? chatMessageText.length - 1 : chatMessageText.length);
		chatMessageText = chatMessageText.substring(7, substringEnd);
	}

	if (chatMessage.tags.emotes) {
		const emoteDataStrings = chatMessage.tags.emotes.split("/");
		let emotePositions = [];
		for (const emoteDataString of emoteDataStrings) {
			const emoteData = emoteDataString.split(":", 2);
			const emoteID = emoteData[0];
			const emotePositionList = emoteData[1].split(",").map((val) => {
				const positions = val.split("-");
				return { emote: emoteID, start: +positions[0], end: +positions[1] };
			});
			emotePositions = emotePositions.concat(emotePositionList);
		}
		emotePositions.sort((a, b) => a.start - b.start);

		let messageText = [chatMessageText];
		while (emotePositions.length > 0) {
			const emoteData = emotePositions.pop(); // Pop the highest-index element from the array
			let text = messageText.shift();
			const textAndEmote = [text.substring(0, emoteData.start)];

			const emoteImg = document.createElement("img");
			emoteImg.src = `https://static-cdn.jtvnw.net/emoticons/v2/${emoteData.emote}/default/dark/1.0`;
			emoteImg.classList.add("chat-replay-message-emote");
			const emoteText = text.substring(emoteData.start, emoteData.end + 1);
			emoteImg.alt = emoteText;
			emoteImg.title = emoteText;
			textAndEmote.push(emoteImg);

			const remainingText = text.substring(emoteData.end + 1);
			if (remainingText !== "") {
				textAndEmote.push(remainingText);
			}
			messageText = textAndEmote.concat(messageText);
		}

		for (const messagePart of messageText) {
			if (typeof messagePart === "string") {
				const node = document.createTextNode(messagePart);
				messageTextElement.appendChild(node);
			} else {
				messageTextElement.appendChild(messagePart);
			}
		}
	} else {
		messageTextElement.appendChild(document.createTextNode(chatMessageText));
	}

	const messageContainer = document.createElement("div");
	messageContainer.classList.add("chat-replay-message");
	if (chatMessage.tags.hasOwnProperty("id")) {
		messageContainer.id = `chat-replay-message-${chatMessage.tags.id}`;
	}
	messageContainer.dataset.sender = chatMessage.sender;
	messageContainer.appendChild(sendTimeElement);
	messageContainer.appendChild(senderNameElement);
	messageContainer.appendChild(messageTextElement);
	return messageContainer;
}
