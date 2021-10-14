function moveSpeed(player, amount) {
	let currentIndex = PLAYBACK_RATES.indexOf(player.playbackRate());
	if (currentIndex === -1) {
		addError("The playback rate has somehow gone very wrong.");
		return;
	}
	currentIndex += amount;
	if (currentIndex < 0 || currentIndex >= PLAYBACK_RATES.length) {
		return; // We've reached/exceeded the edge
	}
	player.playbackRate(PLAYBACK_RATES[currentIndex]);
}

function increaseSpeed(player) {
	moveSpeed(player, 1);
}

function decreaseSpeed(player) {
	moveSpeed(player, -1);
}

document.addEventListener("keypress", (event) => {
	if (event.target.nodeName === "INPUT" || event.target.nodeName === "TEXTAREA") {
		return;
	}

	const player = getVideoJS();
	switch (event.key) {
		case "0":
			player.currentTime(0);
			break;
		case "1":
			player.currentTime(player.duration() * 0.1);
			break;
		case "2":
			player.currentTime(player.duration() * 0.2);
			break;
		case "3":
			player.currentTime(player.duration() * 0.3);
			break;
		case "4":
			player.currentTime(player.duration() * 0.4);
			break;
		case "5":
			player.currentTime(player.duration() * 0.5);
			break;
		case "6":
			player.currentTime(player.duration() * 0.6);
			break;
		case "7":
			player.currentTime(player.duration() * 0.7);
			break;
		case "8":
			player.currentTime(player.duration() * 0.8);
			break;
		case "9":
			player.currentTime(player.duration() * 0.9);
			break;
		case "j":
			player.currentTime(player.currentTime() - 10);
			break;
		case "k":
		case " ":
			if (player.paused()) {
				player.play();
			} else {
				player.pause();
			}
			break;
		case "l":
			player.currentTime(player.currentTime() + 10);
			break;
		case "ArrowLeft":
			player.currentTime(player.currentTime() - 5);
			break;
		case "ArrowRight":
			player.currentTime(player.currentTime() + 5);
			break;
		case ",":
			player.currentTime(player.currentTime() - (1 / VIDEO_FRAMES_PER_SECOND));
			break;
		case ".":
			player.currentTime(player.currentTime() + (1 / VIDEO_FRAMES_PER_SECOND));
			break;
		case "=":
			increaseSpeed(player);
			break;
		case "-":
			decreaseSpeed(player);
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

	const player = getVideoJS();
	switch (event.key) {
		case "ArrowLeft":
			player.currentTime(player.currentTime() - 5);
			break;
		case "ArrowRight":
			player.currentTime(player.currentTime() + 5);
			break;
		default:
			break;
	}
});