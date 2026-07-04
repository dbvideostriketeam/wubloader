import {
	Accessor,
	Component,
	createEffect,
	createResource,
	createSignal,
	For,
	onCleanup,
	onMount,
	Setter,
	Show,
	Suspense,
	untrack,
} from "solid-js";
import { DateTime } from "luxon";
import { Fragment } from "hls.js";
import { useKeyDownEvent } from "@solid-primitives/keyboard";
import { MediaPlayerElement } from "vidstack/elements";
import styles from "./Restreamer.module.scss";
import {
	dateTimeFromVideoPlayerTime,
	dateTimeFromWubloaderTime,
	wubloaderTimeFromDateTime,
} from "../common/convertTime";
import { StreamVideoInfo } from "../common/streamInfo";
import {
	KeyboardShortcuts,
	StreamTimeSettings,
	VIDEO_FRAMES_PER_SECOND,
	VideoPlayer,
} from "../common/video";
import { ChatDisplay } from "../common/chat";

export interface DefaultsData {
	video_channel: string;
	bustime_start: string;
	title_prefix: string;
	title_max_length: string;
	upload_locations: string[];
}

export const Restreamer: Component = () => {
	const [pageErrors, setPageErrors] = createSignal<string[]>([]);
	const [defaultsData] = createResource<DefaultsData | null>(
		async (source, { value, refetching }) => {
			const response = await fetch("/thrimshim/defaults");
			if (!response.ok) {
				return null;
			}
			return await response.json();
		},
	);

	return (
		<>
			<ul class={styles.errorList}>
				<For each={pageErrors()}>
					{(error: string, index: Accessor<number>) => (
						<li>
							{error}
							<a class={styles.errorRemoveLink}>[X]</a>
						</li>
					)}
				</For>
			</ul>
			<KeyboardShortcuts includeEditorShortcuts={false} />
			<Suspense>
				<Show when={defaultsData()}>
					<RestreamerWithDefaults
						defaults={defaultsData()!}
						errorList={pageErrors}
						setErrorList={setPageErrors}
					/>
				</Show>
			</Suspense>
		</>
	);
};

interface RestreamerDefaultProps {
	defaults: DefaultsData;
	errorList: Accessor<string[]>;
	setErrorList: Setter<string[]>;
}

const RestreamerWithDefaults: Component<RestreamerDefaultProps> = (props) => {
	const busStartTimeDefault = dateTimeFromWubloaderTime(props.defaults.bustime_start);
	if (!busStartTimeDefault) {
		return <></>;
	}
	const [busStartTime, setBusStartTime] = createSignal<DateTime>(busStartTimeDefault);
	let defaultStreamInfo = StreamVideoInfo.defaultFromURL();
	if (defaultStreamInfo === null) {
		defaultStreamInfo = new StreamVideoInfo();
		defaultStreamInfo.streamName = props.defaults.video_channel;
		defaultStreamInfo.streamStartTime = DateTime.utc().minus({ minutes: 10 });
		defaultStreamInfo.streamEndTime = null;
	}
	const [streamVideoInfo, setStreamVideoInfo] = createSignal<StreamVideoInfo>(defaultStreamInfo);
	const [playerTime, setPlayerTime] = createSignal<number>(0);
	const [mediaPlayer, setMediaPlayer] = createSignal<MediaPlayerElement>();
	const [videoFragments, setVideoFragments] = createSignal<Fragment[]>([]);
	const [chatContainerElement, setChatContainerElement] = createSignal<HTMLDivElement>();
	const [chatScrolledToBottom, setChatScrolledToBottom] = createSignal(true);

	onMount(() => {
		const player = mediaPlayer();
		if (player) {
			player.addEventListener("hls-level-loaded", (event) => {
				setVideoFragments(event.detail.details.fragments);
			});
		}
	});

	const chatScrollTimer = setInterval(() => {
		const chatContainer = chatContainerElement();
		if (!chatContainer) {
			return;
		}
		const autoscroll = chatScrolledToBottom();
		if (autoscroll) {
			chatContainer.scrollTop = chatContainer.scrollHeight;
		}
	}, 100);
	onCleanup(() => clearInterval(chatScrollTimer));

	const keyDownEvent = useKeyDownEvent();
	createEffect(() => {
		const event = keyDownEvent();
		if (!event) {
			return;
		}

		if (
			(event.target as Node).nodeName === "INPUT" ||
			(event.target as Node).nodeName === "TEXTAREA"
		) {
			return;
		}

		const player = untrack(mediaPlayer);
		if (!player) {
			return;
		}
		switch (event.key) {
			case "0":
				player.currentTime = 0;
				break;
			case "1":
				player.currentTime = player.duration * 0.1;
				break;
			case "2":
				player.currentTime = player.duration * 0.2;
				break;
			case "3":
				player.currentTime = player.duration * 0.3;
				break;
			case "4":
				player.currentTime = player.duration * 0.4;
				break;
			case "5":
				player.currentTime = player.duration * 0.5;
				break;
			case "6":
				player.currentTime = player.duration * 0.6;
				break;
			case "7":
				player.currentTime = player.duration * 0.7;
				break;
			case "8":
				player.currentTime = player.duration * 0.8;
				break;
			case "9":
				player.currentTime = player.duration * 0.9;
				break;
			case "j":
				player.currentTime -= 10;
				break;
			case "J":
				player.currentTime -= 1;
				break;
			case "k":
			case "K":
			case " ":
				if (player.paused) {
					player.play();
				} else {
					player.pause();
				}
				event.preventDefault();
				break;
			case "l":
				player.currentTime += 10;
				break;
			case "L":
				player.currentTime += 1;
				break;
			case "m":
				player.muted = !player.muted;
				break;
			case ",":
			case "<":
				player.currentTime -= 1 / VIDEO_FRAMES_PER_SECOND;
				break;
			case ".":
			case ">":
				player.currentTime += 1 / VIDEO_FRAMES_PER_SECOND;
				break;
			case "=":
				if (player.playbackRate < 8) {
					player.playbackRate += 0.25;
				}
				break;
			case "+":
				if (player.playbackRate < 2) {
					player.playbackRate = 2;
				} else {
					player.playbackRate = 8;
				}
				break;
			case "-":
				if (player.playbackRate > 0.25) {
					player.playbackRate -= 0.25;
				}
				break;
			case "_":
				player.playbackRate = 0.25;
				break;
			case "ArrowLeft":
				if (event.shiftKey) {
					player.currentTime -= 60;
				} else {
					player.currentTime -= 5;
				}
				break;
			case "ArrowRight":
				if (event.shiftKey) {
					player.currentTime += 60;
				} else {
					player.currentTime += 5;
				}
				break;
			case "Backspace":
				event.preventDefault();
				player.playbackRate = 1;
				break;
		}
	});

	const videoURL = () => {
		const streamInfo = streamVideoInfo();
		const startTime = wubloaderTimeFromDateTime(streamInfo.streamStartTime);
		const query = new URLSearchParams({ start: startTime });
		if (streamInfo.streamEndTime) {
			const endTime = wubloaderTimeFromDateTime(streamInfo.streamEndTime);
			query.append("end", endTime);
		}
		const queryString = query.toString();
		let url = `/playlist/${streamInfo.streamName}.m3u8`;
		if (queryString !== "") {
			url += `?${queryString}`;
		}
		return url;
	};

	const downloadVideoURL = () => {
		const streamInfo = streamVideoInfo();
		const startTime = wubloaderTimeFromDateTime(streamInfo.streamStartTime);
		const params = new URLSearchParams({ type: "smart", start: startTime });
		if (streamInfo.streamEndTime) {
			const endTime = wubloaderTimeFromDateTime(streamInfo.streamEndTime);
			params.append("end", endTime);
		}
		return `/cut/${streamInfo.streamName}/source.ts?${params}`;
	};

	const downloadFrameURL = () => {
		const streamInfo = streamVideoInfo();
		const fragments = videoFragments();
		const videoTime = playerTime();
		if (!fragments || fragments.length === 0) {
			return "";
		}
		const currentTime = dateTimeFromVideoPlayerTime(fragments, videoTime);
		if (currentTime === null) {
			return "";
		}
		const wubloaderTime = wubloaderTimeFromDateTime(currentTime);
		return `/frame/${streamInfo.streamName}/source.png?timestamp=${wubloaderTime}`;
	};

	return (
		<>
			<StreamTimeSettings
				busStartTime={busStartTime}
				streamVideoInfo={streamVideoInfo}
				setStreamVideoInfo={setStreamVideoInfo}
				showTimeRangeLink={true}
				errorList={props.errorList}
				setErrorList={props.setErrorList}
			/>
			<VideoPlayer
				src={videoURL}
				setPlayerTime={setPlayerTime}
				mediaPlayer={mediaPlayer as Accessor<MediaPlayerElement>}
				setMediaPlayer={setMediaPlayer as Setter<MediaPlayerElement>}
			/>
			<div class={styles.videoLinks}>
				<a href={downloadVideoURL()}>Download Video</a>
				<a href={downloadFrameURL()}>Download Current Frame as Image</a>
			</div>
			<div
				class={styles.chatContainer}
				ref={setChatContainerElement}
				onScroll={(event) => {
					const chatContainer = event.currentTarget;
					// Allow a 20 pixel buffer at the bottom of the element
					setChatScrolledToBottom(
						chatContainer.scrollTop + chatContainer.offsetHeight + 20 >= chatContainer.scrollHeight,
					);
				}}
			>
				<ChatDisplay
					streamInfo={streamVideoInfo()}
					fragments={videoFragments}
					videoTime={playerTime}
				/>
			</div>
		</>
	);
};
