import {
	Accessor,
	Component,
	createEffect,
	createResource,
	createSignal,
	For,
	Setter,
	Show,
	Suspense,
} from "solid-js";
import { DateTime } from "luxon";
import { HLSProvider } from "vidstack";
import { MediaPlayerElement } from "vidstack/elements";
import styles from "./Restreamer.module.scss";
import {
	dateTimeFromVideoPlayerTime,
	dateTimeFromWubloaderTime,
	wubloaderTimeFromDateTime,
} from "../common/convertTime";
import {
	KeyboardShortcuts,
	StreamTimeSettings,
	StreamVideoInfo,
	VideoPlayer,
} from "../common/video";

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

	const busStartTime = () => {
		const defaults = defaultsData();
		if (defaults && defaults.hasOwnProperty("bustime_start")) {
			return dateTimeFromWubloaderTime(defaults.bustime_start);
		}
		return null;
	};

	const now = DateTime.utc();

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
			<div class={styles.keyboardShortcutHelp}>
				<KeyboardShortcuts includeEditorShortcuts={false} />
			</div>
			<Suspense>
				<Show when={defaultsData()}>
					<RestreamerWithDefaults
						defaults={defaultsData()}
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
	const [busStartTime, setBusStartTime] = createSignal<DateTime>(
		dateTimeFromWubloaderTime(props.defaults.bustime_start),
	);
	const [streamVideoInfo, setStreamVideoInfo] = createSignal<StreamVideoInfo>({
		streamName: props.defaults.video_channel,
		streamStartTime: DateTime.utc().minus({ minutes: 10 }),
		streamEndTime: null,
	});
	const [playerTime, setPlayerTime] = createSignal<number>(0);
	const [mediaPlayer, setMediaPlayer] = createSignal<MediaPlayerElement>();

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
		const params = new URLSearchParams({ type: "smart", start: encodeURIComponent(startTime) });
		if (streamInfo.streamEndTime) {
			const endTime = wubloaderTimeFromDateTime(streamInfo.streamEndTime);
			params.append("end", endTime);
		}
		return `/cut/${streamInfo.streamName}/source.ts?${params}`;
	};

	const downloadFrameURL = () => {
		const streamInfo = streamVideoInfo();
		const player = mediaPlayer();
		const videoTime = playerTime();
		const provider = player.provider as HLSProvider;
		if (!provider) {
			return "";
		}
		const currentTime = dateTimeFromVideoPlayerTime(provider, videoTime);
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
				showTimeRangeLink={false}
				errorList={props.errorList}
				setErrorList={props.setErrorList}
			/>
			<VideoPlayer
				src={videoURL}
				setPlayerTime={setPlayerTime}
				mediaPlayer={mediaPlayer}
				setMediaPlayer={setMediaPlayer}
			/>
			<div class={styles.videoLinks}>
				<a href={downloadVideoURL()}>Download Video</a>
				<a href={downloadFrameURL()}>Download Current Frame as Image</a>
			</div>
		</>
	);
};
