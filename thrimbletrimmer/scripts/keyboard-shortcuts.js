function moveSpeed(amount) {
	const videoElement = document.getElementById("video");
	let currentIndex = PLAYBACK_RATES.indexOf(videoElement.playbackRate);
	if (currentIndex === -1) {
		addError("The playback rate has somehow gone very wrong.");
		return;
	}
	currentIndex += amount;
	if (currentIndex < 0 || currentIndex >= PLAYBACK_RATES.length) {
		return; // We've reached/exceeded the edge
	}
	setSpeed(videoElement, PLAYBACK_RATES[currentIndex]);
}

function increaseSpeed() {
	moveSpeed(1);
}

function decreaseSpeed() {
	moveSpeed(-1);
}

function setSpeed(videoElement, speed) {
	videoElement.playbackRate = speed;
	const playbackSelector = document.getElementById("video-controls-playback-speed");
	playbackSelector.value = speed;
}

document.addEventListener("keypress", (event) => {
	if (event.target.nodeName === "INPUT" || event.target.nodeName === "TEXTAREA") {
		return;
	}

	const videoElement = document.getElementById("video");
	switch (event.key) {
		case "0":
			videoElement.currentTime = 0;
			break;
		case "1":
			videoElement.currentTime = videoElement.duration * 0.1;
			break;
		case "2":
			videoElement.currentTime = videoElement.duration * 0.2;
			break;
		case "3":
			videoElement.currentTime = videoElement.duration * 0.3;
			break;
		case "4":
			videoElement.currentTime = videoElement.duration * 0.4;
			break;
		case "5":
			videoElement.currentTime = videoElement.duration * 0.5;
			break;
		case "6":
			videoElement.currentTime = videoElement.duration * 0.6;
			break;
		case "7":
			videoElement.currentTime = videoElement.duration * 0.7;
			break;
		case "8":
			videoElement.currentTime = videoElement.duration * 0.8;
			break;
		case "9":
			videoElement.currentTime = videoElement.duration * 0.9;
			break;
		case "j":
			videoElement.currentTime -= 10;
			break;
		case "k":
		case "K":
		case " ":
			if (videoElement.paused) {
				videoElement.play();
			} else {
				videoElement.pause();
			}
			event.preventDefault();
			break;
		case "l":
			videoElement.currentTime += 10;
			break;
		case "J":
			videoElement.currentTime -= 1;
			break;
		case "L":
			videoElement.currentTime += 1;
			break;
		case "m":
			videoElement.muted = !videoElement.muted;
			break;
		case ",":
		case "<":
			videoElement.currentTime -= 1 / VIDEO_FRAMES_PER_SECOND;
			break;
		case ".":
		case ">":
			videoElement.currentTime += 1 / VIDEO_FRAMES_PER_SECOND;
			break;
		case "=":
			increaseSpeed();
			break;
		case "+":
			const playbackRate = videoElement.playbackRate;
			if (playbackRate < 2) {
				setSpeed(videoElement, 2);
			} else {
				setSpeed(videoElement, PLAYBACK_RATES[PLAYBACK_RATES.length - 1]);
			}
			break;
		case "-":
			decreaseSpeed();
			break;
		case "_":
			setSpeed(videoElement, PLAYBACK_RATES[0]);
			break;
		case "[":
			if (typeof setCurrentRangeStartToVideoTime === "function") {
				setCurrentRangeStartToVideoTime();
			}
			break;
		case "]":
			if (typeof setCurrentRangeEndToVideoTime === "function") {
				setCurrentRangeEndToVideoTime();
			}
			break;
		case "o":
			if (typeof moveToPreviousRange === "function") {
				moveToPreviousRange();
			}
			break;
		case "p":
			if (typeof moveToNextRange === "function") {
				moveToNextRange();
			}
			break;
		default:
			break;
	}
});

// For whatever reason, arrow keys don't work for keypress. We can use keydown for them.
document.addEventListener("keydown", (event) => {
	if (event.target.nodeName === "INPUT" || event.target.nodeName === "TEXTAREA") {
		return;
	}

	if (event.target.classList.contains("jcrop-widget") && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
		return;
	}

	const videoElement = document.getElementById("video");
	switch (event.key) {
		case "ArrowLeft":
			if (event.shiftKey) {
				videoElement.currentTime -= 60;
			} else {
				videoElement.currentTime -= 5;
			}
			break;
		case "ArrowRight":
			if (event.shiftKey) {
				videoElement.currentTime += 60;
			} else {
				videoElement.currentTime += 5;
			}
			break;
		case "Backspace":
			event.preventDefault();
			videoElement.playbackRate = 1;
			document.getElementById("video-controls-playback-speed").value = 1;
			break;
		default:
			break;
	}
});
