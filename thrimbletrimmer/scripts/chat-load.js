self.importScripts("luxon.min.js", "common-worker.js");

var DateTime = luxon.DateTime;
luxon.Settings.defaultZone = "utc";

self.onmessage = async (event) => {
	const chatLoadData = event.data;

	const segmentMetadata = chatLoadData.segmentMetadata;
	for (const segmentData of segmentMetadata) {
		segmentData.rawStart = DateTime.fromMillis(segmentData.rawStart);
		segmentData.rawEnd = DateTime.fromMillis(segmentData.rawEnd);
	}

	const fetchURL = `/${chatLoadData.stream}/chat.json?start=${chatLoadData.start}&end=${chatLoadData.end}`;
	const chatResponse = await fetch(fetchURL);
	if (!chatResponse.ok) {
		return;
	}
	const chatRawData = await chatResponse.json();

	const chatData = [];
	for (const chatLine of chatRawData) {
		if (
			chatLine.command !== "PRIVMSG" &&
			chatLine.command !== "CLEARMSG" &&
			chatLine.command !== "CLEARCHAT" &&
			chatLine.command !== "USERNOTICE"
		) {
			continue;
		}
		const when = DateTime.fromSeconds(chatLine.time);
		const displayWhen = videoHumanTimeFromDateTimeWithFragments(segmentMetadata, when);
		// Here, we just push each line successively into the list. This assumes data is provided to us in chronological order.
		chatData.push({ message: chatLine, when: when.toMillis(), displayWhen: displayWhen });
	}
	self.postMessage(chatData);
};

function videoHumanTimeFromDateTimeWithFragments(fragmentMetadata, dateTime) {
	for (const segmentData of fragmentMetadata) {
		if (dateTime >= segmentData.rawStart && dateTime <= segmentData.rawEnd) {
			const playerTime =
				segmentData.playerStart + dateTime.diff(segmentData.rawStart).as("seconds");
			return videoHumanTimeFromVideoPlayerTime(playerTime);
		}
	}
	return null;
}
