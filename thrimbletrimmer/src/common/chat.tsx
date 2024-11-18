import { Accessor, Component, createResource, For, Index, JSX, Show, Suspense } from "solid-js";
import { StreamVideoInfo } from "./streamInfo";
import { DateTime } from "luxon";
import { Fragment } from "hls.js";
import { wubloaderTimeFromDateTime } from "./convertTime";
import styles from "./chat.module.scss";

export interface RawChatMessage {
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

export class ChatMessageData {
	message: RawChatMessage;
	messageID: string;
	userID: string | null;
	when: DateTime;
	whenSeconds: number;
	whenDisplay: string;
}

export class ChatLog {
	messages: ChatMessageData[];
	messagesByID: { [id: string]: ChatMessageData };
	messagesBySender: { [username: string]: ChatMessageData[] };
	clearMessages: { [messageID: string]: number };
	clearUsers: { [username: string]: number[] };

	public constructor(
		messages: ChatMessageData[],
		clearMessages: { [messageID: string]: number },
		clearUsers: { [username: string]: number[] },
	) {
		const messagesByID: { [id: string]: ChatMessageData } = {};
		const messagesBySender: { [username: string]: ChatMessageData[] } = {};

		for (const message of messages) {
			messagesByID[message.message.tags.id] = message;
			if (!messagesBySender.hasOwnProperty(message.message.sender)) {
				messagesBySender[message.message.sender] = [];
			}
			messagesBySender[message.message.sender].push(message);
		}

		return {
			messages: messages,
			messagesByID: messagesByID,
			messagesBySender: messagesBySender,
			clearMessages: clearMessages,
			clearUsers: clearUsers,
		};
	}

	static default = () => new ChatLog([], {}, {});
}

export async function chatData(
	streamInfo: StreamVideoInfo,
	fragments: Fragment[],
): Promise<ChatLog> {
	const streamName = streamInfo.streamName;
	const streamStartTime = streamInfo.streamStartTime;
	const streamEndTime = streamInfo.streamEndTime;
	if (!streamEndTime) {
		return ChatLog.default();
	}
	const startWubloaderTime = wubloaderTimeFromDateTime(streamStartTime);
	const endWubloaderTime = wubloaderTimeFromDateTime(streamEndTime);
	const params = new URLSearchParams({ start: startWubloaderTime, end: endWubloaderTime });

	const chatResponse = await fetch(`/${streamName}/chat.json?${params}`);
	if (!chatResponse.ok) {
		return ChatLog.default();
	}
	const chatMessages: RawChatMessage[] = await chatResponse.json();

	if (!fragments || fragments.length === 0) {
		return ChatLog.default();
	}

	let currentFragmentIndex = 0;
	let currentFragmentStartTime = DateTime.fromISO(fragments[0].rawProgramDateTime!)!;
	const chatData: ChatMessageData[] = [];
	const clearMessages: { [messageID: string]: number } = {};
	const clearUsers: { [userID: string]: number[] } = {};
	for (const chatMessage of chatMessages) {
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
		const messageTimeOffset = when.diff(currentFragmentStartTime).milliseconds / 1000;
		const messageVideoTime = fragments[currentFragmentIndex].start + messageTimeOffset;
		if (chatMessage.command === "PRIVMSG") {
			chatData.push({
				message: chatMessage,
				messageID: chatMessage.tags["id"],
				userID: chatMessage.tags["user-id"],
				when: when,
				whenSeconds: messageVideoTime,
				whenDisplay: formatDisplayTime(messageVideoTime),
			});
		} else if (chatMessage.command === "USERNOTICE") {
			chatData.push({
				message: chatMessage,
				messageID: chatMessage.tags["id"],
				userID: null,
				when: when,
				whenSeconds: messageVideoTime,
				whenDisplay: formatDisplayTime(messageVideoTime),
			});
		} else if (chatMessage.command === "CLEARMSG") {
			const messageID = chatMessage.tags["target-msg-id"];
			clearMessages[messageID] = messageVideoTime;
		} else if (chatMessage.command === "CLEARCHAT") {
			const userID = chatMessage.tags["target-user-id"];
			if (!clearUsers.hasOwnProperty(userID)) {
				clearUsers[userID] = [];
			}
			clearUsers[userID].push(messageVideoTime);
		}
	}
	return new ChatLog(chatData, clearMessages, clearUsers);
}

function formatDisplayTime(timeSeconds: number): string {
	const hours = Math.floor(timeSeconds / 3600);
	const minutes = (Math.floor(timeSeconds / 60) % 60).toString().padStart(2, "0");
	const seconds = Math.floor(timeSeconds % 60)
		.toString()
		.padStart(2, "0");
	const milliseconds = Math.floor((timeSeconds % 1) * 1000)
		.toString()
		.padStart(3, "0");

	return `${hours}:${minutes}:${seconds}.${milliseconds}`;
}

export interface ChatDisplayProps {
	streamInfo: StreamVideoInfo;
	fragments: Accessor<Fragment[]>;
	videoTime: Accessor<number>;
}

export const ChatDisplay: Component<ChatDisplayProps> = (props) => {
	const streamDataAndFragments = () => {
		const fragments = props.fragments();
		if (!fragments || fragments.length === 0) {
			return null;
		}
		return {
			streamInfo: props.streamInfo,
			fragments: fragments,
		};
	};
	const [possibleChatLog] = createResource(streamDataAndFragments, async () => {
		const { streamInfo, fragments } = streamDataAndFragments()!;
		return await chatData(streamInfo, fragments);
	});

	const chatLog = () => {
		const chatLogData = possibleChatLog();
		if (chatLogData) {
			return chatLogData;
		}
		return ChatLog.default();
	};

	return (
		<Suspense>
			<Index each={chatLog().messages}>
				{(item: Accessor<ChatMessageData>, index: number) => {
					const chatCommand = item().message.command;
					if (chatCommand === "PRIVMSG") {
						return (
							<ChatMessage chatMessage={item()} chatLog={chatLog()} videoTime={props.videoTime} />
						);
					} else if (chatCommand === "USERNOTICE") {
						return <SystemMessage chatMessage={item()} videoTime={props.videoTime} />;
					} else {
						return <></>;
					}
				}}
			</Index>
		</Suspense>
	);
};

export interface ChatMessageProps {
	chatMessage: ChatMessageData;
	chatLog: ChatLog;
	videoTime: Accessor<number>;
}

export const ChatMessage: Component<ChatMessageProps> = (props) => {
	const message = props.chatMessage;

	const displayChatMessage = () => props.videoTime() >= message.whenSeconds;

	const mayClearMessage = props.chatLog.clearMessages.hasOwnProperty(message.messageID);
	const mayClearUser =
		message.userID &&
		props.chatLog.clearUsers.hasOwnProperty(message.userID.toString()) &&
		props.chatLog.clearUsers[message.userID].some((clearTime) => clearTime > message.whenSeconds);

	const messageCleared = () => {
		const messageClearTime = props.chatLog.clearMessages[message.messageID];
		const videoTime = props.videoTime();
		return videoTime >= messageClearTime;
	};
	const userCleared = () => {
		if (message.userID) {
			let userClearTime = 0;
			for (const clearTime of props.chatLog.clearUsers[message.userID]) {
				if (clearTime >= message.whenSeconds) {
					userClearTime = clearTime;
					break;
				}
			}
			const videoTime = props.videoTime();
			return videoTime >= userClearTime;
		}
		return false;
	};
	let clearMessageCheck = () => false;
	if (mayClearMessage && mayClearUser) {
		clearMessageCheck = () => messageCleared() || userCleared();
	} else if (mayClearMessage) {
		clearMessageCheck = messageCleared;
	} else if (mayClearUser) {
		clearMessageCheck = userCleared;
	}

	return (
		<Show when={displayChatMessage()}>
			<div
				id={`chat-replay-message-${message.message.tags.id}`}
				classList={(() => {
					const classList: any = {};
					classList[styles.chatReplayMessage] = true;
					classList[styles.chatReplayMessageCleared] = clearMessageCheck();
					return classList;
				})()}
			>
				<div class={styles.chatReplayMessageTime}>{message.whenDisplay}</div>
				<MessageSender chatMessage={message} />
				<MessageText chatMessage={message} />
			</div>
		</Show>
	);
};

export interface SystemMessageProps {
	chatMessage: ChatMessageData;
	videoTime: Accessor<number>;
}

export const SystemMessage: Component<SystemMessageProps> = (props) => {
	const message = props.chatMessage;

	const displaySystemMessage = () => props.videoTime() >= message.whenSeconds;

	const systemMessage = () => {
		const systemMsg = message.message.tags["system-msg"];
		if (!systemMsg && message.message.tags["msg-id"] === "announcement") {
			return "Announcement";
		}
		return systemMsg;
	};

	return (
		<Show when={displaySystemMessage()}>
			<div
				id={`chat-replay-message-system-${message.message.tags.id}`}
				class={styles.chatReplayMessage}
			>
				<div class={styles.chatReplayMessageTime}>{message.whenDisplay}</div>
				<MessageSender chatMessage={message} />
				<div class={`${styles.chatReplayMessageText} ${styles.chatReplayMessageSystem}`}>
					{systemMessage()}
				</div>
			</div>
			<Show when={message.message.params.length > 1}>
				<div id={`chat-replay-message-${message.message.tags.id}`}>
					<div class={styles.chatReplayMessageTime}></div>
					<MessageSender chatMessage={message} />
					<MessageText chatMessage={message} />
				</div>
			</Show>
		</Show>
	);
};

interface MessageSenderProps {
	chatMessage: ChatMessageData;
}

const MessageSender: Component<MessageSenderProps> = (props) => {
	const message = props.chatMessage.message;
	const color = message.tags.hasOwnProperty("color") ? message.tags.color : "inherit";
	return (
		<div class={styles.chatReplayMessageSender} style={`color: ${color}`}>
			{message.tags["display-name"]}
		</div>
	);
};

interface MessageTextProps {
	chatMessage: ChatMessageData;
}

const MessageText: Component<MessageTextProps> = (props) => {
	let chatMessageText = props.chatMessage.message.params[1];
	const messageParts: JSX.Element[] = [];

	let replyData: { id: string; user: string; message: string; isAction: boolean } | null = null;
	if (props.chatMessage.message.tags.hasOwnProperty("reply-parent-msg-id")) {
		const messageTags = props.chatMessage.message.tags;
		let messageText = messageTags["reply-parent-msg-body"];
		const isAction = messageText.startsWith("\u0001ACTION");
		if (isAction) {
			const substringEnd = messageText.endsWith("\u0001")
				? messageText.length - 1
				: messageText.length;
			messageText = messageText.substring(7, substringEnd);
		}
		replyData = {
			id: messageTags["reply-parent-msg-id"],
			user: messageTags["reply-parent-display-name"],
			message: messageText,
			isAction: isAction,
		};
	}

	const isAction = chatMessageText.startsWith("\u0001ACTION");
	if (isAction) {
		const substringEnd = chatMessageText.endsWith("\u0001")
			? chatMessageText.length - 1
			: chatMessageText.length;
		chatMessageText = chatMessageText.substring(7, substringEnd);
	}

	if (props.chatMessage.message.tags.emotes) {
		const emoteDataStrings = props.chatMessage.message.tags.emotes.split("/");
		let emotePositions: { emote: string; start: number; end: number }[] = [];
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

		let messageTextStart = 0;
		while (emotePositions.length > 0) {
			const emoteData = emotePositions.shift()!;
			const text = chatMessageText.substring(0, emoteData.start - messageTextStart);
			if (text !== "") {
				messageParts.push(<>{text}</>);
			}
			const emoteImageURL = `/segments/emotes/${emoteData.emote}/dark-1.0`;
			const emoteText = chatMessageText.substring(
				emoteData.start - messageTextStart,
				emoteData.end + 1 - messageTextStart,
			);
			chatMessageText = chatMessageText.substring(emoteData.end + 1);
			messageTextStart = emoteData.end + 1;
			messageParts.push(
				<img
					src={emoteImageURL}
					alt={emoteText}
					title={emoteText}
					class={styles.chatReplayMessageEmote}
				/>,
			);
		}
		if (chatMessageText !== "") {
			messageParts.push(<>{chatMessageText}</>);
		}
	} else {
		messageParts.push(<>{chatMessageText}</>);
	}

	return (
		<div
			classList={(() => {
				const classList: { [className: string]: boolean } = {};
				classList[styles.chatReplayMessageText] = true;
				classList[styles.chatReplayMessageTextAction] = isAction;
				return classList;
			})()}
		>
			<Show when={replyData}>
				<div
					classList={(() => {
						const classList: any = {};
						classList[styles.chatReplayMessageReply] = true;
						classList[styles.chatReplayMessageTextAction] = replyData!.isAction;
						return classList;
					})()}
				>
					<a href={`#chat-replay-message-${replyData!.id}`}>
						Replying to {replyData!.user}: {replyData!.message}
					</a>
				</div>
			</Show>
			<For each={messageParts}>{(item, index) => item}</For>
		</div>
	);
};
