import { StreamVideoInfo } from "./streamInfo";
import { HLSProvider } from "vidstack";
import { DateTime } from "luxon";
import { Fragment } from "hls.js";
import { wubloaderTimeFromDateTime } from "./convertTime";

export interface ChatMessage {
	command: string;
	host: string;
	params: string[];
	receivers: { [node: string]: number };
	sender: string;
	tags: { [key: string]: string };
	time: number;
	time_range: number;
	user: string;
}

export interface ChatMessageData {
	message: ChatMessage;
	when: DateTime;
	whenSeconds: number;
	whenDisplay: string;
}

export async function chatData(
	streamInfo: StreamVideoInfo,
	fragments: Fragment[],
): Promise<ChatMessageData[]> {
	const streamName = streamInfo.streamName;
	const streamStartTime = streamInfo.streamStartTime;
	const streamEndTime = streamInfo.streamEndTime;
	if (!streamEndTime) {
		return [];
	}
	const startWubloaderTime = wubloaderTimeFromDateTime(streamStartTime);
	const endWubloaderTime = wubloaderTimeFromDateTime(streamEndTime);
	const params = new URLSearchParams({ start: startWubloaderTime, end: endWubloaderTime });

	const chatResponse = await fetch(`/${streamName}/chat.json?${params}`);
	if (!chatResponse.ok) {
		return [];
	}
	const chatMessages: ChatMessage[] = await chatResponse.json();

	if (!fragments || fragments.length === 0) {
		return [];
	}

	let currentFragmentIndex = 0;
	let currentFragmentStartTime = DateTime.fromISO(fragments[0].rawProgramDateTime!)!;
	const chatData: ChatMessageData[] = [];
	for (const chatMessage of chatMessages) {
		if (
			chatMessage.command !== "PRIVMSG" &&
			chatMessage.command !== "CLEARMSG" &&
			chatMessage.command !== "CLEARCHAT" &&
			chatMessage.command !== "USERNOTICE"
		) {
			continue;
		}
		const when = DateTime.fromSeconds(chatMessage.time);
		while (
			currentFragmentIndex < fragments.length - 1 &&
			currentFragmentStartTime.plus({ seconds: fragments[currentFragmentIndex].duration }) <= when
		) {
			currentFragmentIndex += 1;
			currentFragmentStartTime = DateTime.fromISO(
				fragments[currentFragmentIndex].rawProgramDateTime!,
			);
		}
		const messageTimeOffset = when.diff(currentFragmentStartTime).seconds;
		const messageVideoTime = fragments[currentFragmentIndex].start + messageTimeOffset;
		chatData.push({
			message: chatMessage,
			when: when,
			whenSeconds: messageVideoTime,
			whenDisplay: formatDisplayTime(messageVideoTime),
		});
	}
	return chatData;
}

function formatDisplayTime(timeSeconds: number): string {
	const hours = Math.floor(timeSeconds / 3600);
	const minutes = (Math.floor(timeSeconds / 60) % 60).toString().padStart(2, "0");
	const seconds = Math.floor(timeSeconds % 60)
		.toString()
		.padStart(2, "0");
	const milliseconds = Math.floor(timeSeconds * 1000)
		.toString()
		.padStart(3, "0");

	return `${hours}:${minutes}:${seconds}.${milliseconds}`;
}
