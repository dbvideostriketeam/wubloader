function changeSpeed(direction) {
	const speeds = [0.5, 1, 1.25, 1.5, 2];
	const currentIndex = speeds.indexOf(player.playbackRate());
	if (currentIndex < 0) {
		// not present
		return;
	}
	const newIndex = currentIndex + direction;
	if (newIndex < 0 || newIndex >= speeds.length) {
		// out of range
		return;
	}
	player.playbackRate(speeds[newIndex]);
}

document.addEventListener("keypress", event => {
	//if(event.target.nodeName == "BODY") {
	if (event.target.nodeName !== "INPUT" && event.target.nodeName !== "TEXTAREA") {
		switch (event.key) {
			case "j":
				player.currentTime(player.currentTime() - 10);
				break;
			case "k":
			case " ": // also pause on space
				player.paused() ? player.play() : player.pause();
				break;
			case "l":
				player.currentTime(player.currentTime() + 10);
				break;
			case ",":
				player.currentTime(player.currentTime() - 0.1);
				break;
			case ".":
				player.currentTime(player.currentTime() + 0.1);
				break;
			case "i":
				player
					.trimmingControls()
					.updateTrimTimes(player.currentTime(), player.trimmingControls().options.endTrim);
				break;
			case "o":
				player
					.trimmingControls()
					.updateTrimTimes(player.trimmingControls().options.startTrim, player.currentTime());
				break;
			case "=":
				changeSpeed(1);
				break;
			case "-":
				changeSpeed(-1);
				break;
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
		}
	}

	// const keyName = event.key;
	// console.log('keypress event\n\n' + 'key: ' + keyName);
	// console.log(event.target.nodeName);
});

//Arrow keys only detected on keydown, keypress only works in "some" browsers
document.addEventListener("keydown", event => {
	if (event.target.nodeName !== "INPUT" && event.target.nodeName !== "TEXTAREA") {
		switch (event.keyCode) {
			case 37:
				player.currentTime(player.currentTime() - 5);
				break;
			case 39:
				player.currentTime(player.currentTime() + 5);
				break;
		}
	}
});
