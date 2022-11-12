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
