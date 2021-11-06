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
	videoElement.playbackRate = PLAYBACK_RATES[currentIndex];
}

function increaseSpeed() {
	moveSpeed(1);
}

function decreaseSpeed() {
	moveSpeed(-1);
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
		case " ":
			if (videoElement.paused) {
				videoElement.play();
			} else {
				videoElement.pause();
			}
			break;
		case "l":
			videoElement.currentTime += 10;
			break;
		case "ArrowLeft":
			videoElement.currentTime -= 5;
			break;
		case "ArrowRight":
			videoElement.currentTime += 5;
			break;
		case ",":
			videoElement.currentTime -= 1 / VIDEO_FRAMES_PER_SECOND;
			break;
		case ".":
			videoElement.currentTime += 1 / VIDEO_FRAMES_PER_SECOND;
			break;
		case "=":
			increaseSpeed();
			break;
		case "-":
			decreaseSpeed();
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

	const videoElement = document.getElementById("video");
	switch (event.key) {
		case "ArrowLeft":
			videoElement.currentTime -= 5;
			break;
		case "ArrowRight":
			videoElement.currentTime += 5;
			break;
		default:
			break;
	}
});
