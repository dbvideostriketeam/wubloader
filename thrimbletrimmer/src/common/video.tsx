import { Accessor, Component, createEffect, createSignal, Setter, Show } from "solid-js";
import Hls from "hls.js";
import { DateTime } from "luxon";
import {
	TimeType,
	wubloaderTimeFromDateTime,
	busTimeFromDateTime,
	timeAgoFromDateTime,
} from "./convertTime";
import styles from "./video.module.scss";

Hls.DefaultConfig.maxBufferHole = 600;

export const VIDEO_FRAMES_PER_SECOND = 30;

export const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 4, 8];

export class StreamVideoInfo {
	streamName: string;
	streamStartTime: DateTime;
	streamEndTime: DateTime | null;
}

export interface StreamTimeSettingsProps {
	busStartTime: Accessor<DateTime>;
	streamVideoInfo: Accessor<StreamVideoInfo>;
	setStreamVideoInfo: Setter<StreamVideoInfo>;
	showTimeRangeLink: boolean;
}

export const StreamTimeSettings: Component<StreamTimeSettingsProps> = (props) => {
	const [timeType, setTimeType] = createSignal<TimeType>(TimeType.UTC);

	const submitHandler = (event: SubmitEvent) => {
		const form = event.currentTarget as HTMLFormElement;
		const formData = new FormData(form);

		// TODO
	};

	const startTimeDisplay = () => {
		const startTime = props.streamVideoInfo().streamStartTime;
		switch (timeType()) {
			case TimeType.UTC:
				return wubloaderTimeFromDateTime(startTime);
			case TimeType.BusTime:
				return busTimeFromDateTime(props.busStartTime(), startTime);
			case TimeType.TimeAgo:
				return timeAgoFromDateTime(startTime);
		}
	};

	const endTimeDisplay = () => {
		const endTime = props.streamVideoInfo().streamEndTime;
		if (endTime === null) {
			return "";
		}
		switch (timeType()) {
			case TimeType.UTC:
				return wubloaderTimeFromDateTime(endTime);
			case TimeType.BusTime:
				return busTimeFromDateTime(props.busStartTime(), endTime);
			case TimeType.TimeAgo:
				return timeAgoFromDateTime(endTime);
		}
	};

	const timeRangeLink = () => {
		const streamInfo = props.streamVideoInfo();
		const startTime = wubloaderTimeFromDateTime(streamInfo.streamStartTime);
		const query = new URLSearchParams({
			stream: streamInfo.streamName,
			start: startTime,
		});
		if (streamInfo.streamEndTime) {
			const endTime = wubloaderTimeFromDateTime(streamInfo.streamEndTime);
			query.append("end", endTime);
		}
		return `?${query}`;
	};

	return (
		<form onSubmit={submitHandler} class={styles.streamTimeSettings}>
			<label>
				<span class={styles.streamTimeSettingLabel}>Stream</span>
				<input type="text" name="stream" value={props.streamVideoInfo().streamName} />
			</label>
			<label>
				<span class={styles.streamTimeSettingLabel}>Start Time</span>
				<input type="text" name="start-time" value={startTimeDisplay()} />
			</label>
			<label>
				<span class={styles.streamTimeSettingLabel}>End Time</span>
				<input type="text" name="end-time" value={endTimeDisplay()} />
			</label>
			<div>
				<label>
					<input
						type="radio"
						name="time-type"
						value={TimeType.UTC}
						checked={timeType() === TimeType.UTC}
						onClick={(event) => setTimeType(TimeType.UTC)}
					/>
					UTC
				</label>
				<label>
					<input
						type="radio"
						name="time-type"
						value={TimeType.BusTime}
						checked={timeType() === TimeType.BusTime}
						onClick={(event) => setTimeType(TimeType.BusTime)}
					/>
					Bus Time
				</label>
				<label>
					<input
						type="radio"
						name="time-type"
						value={TimeType.TimeAgo}
						checked={timeType() === TimeType.TimeAgo}
						onClick={(event) => setTimeType(TimeType.TimeAgo)}
					/>
					Time Ago
				</label>
			</div>
			<div>
				<button type="submit">Update Time Range</button>
			</div>
			<Show when={props.showTimeRangeLink}>
				<div>
					<a href={timeRangeLink()}>Link to this time range</a>
				</div>
			</Show>
		</form>
	);
};

export interface KeyboardShortcutProps {
	includeEditorShortcuts: boolean;
}

export const KeyboardShortcuts: Component<KeyboardShortcutProps> = (
	props: KeyboardShortcutProps,
) => {
	return (
		<details>
			<summary>Keyboard Shortcuts</summary>
			<ul>
				<li>Number keys (0-9): Jump to that 10% interval of the video (0% - 90%)</li>
				<li>K or Space: Toggle pause</li>
				<li>M: Toggle mute</li>
				<li>J: Back 10 seconds</li>
				<li>L: Forward 10 seconds</li>
				<li>Left arrow: Back 5 seconds</li>
				<li>Right arrow: Forward 5 seconds</li>
				<li>Shift+J: Back 1 second</li>
				<li>Shift+L: Forward 1 second</li>
				<li>Comma (,): Back 1 frame</li>
				<li>Period (.): Forward 1 frame</li>
				<li>Equals (=): Increase playback speed 1 step</li>
				<li>Hyphen (-): Decrease playback speed 1 step</li>
				<li>Shift+=: 2x or maximum playback speed</li>
				<li>Shift+-: Minimum playback speed</li>
				<li>Backspace: Reset playback speed to 1x</li>
				<Show when={props.includeEditorShortcuts}>
					<li>
						Left bracket ([): Set start point for active range (indicated by arrow) to current video
						time
					</li>
					<li>Right bracket (]): Set end point for active range to current video time</li>
					<li>O: Set active range one above current active range</li>
					<li>
						P: Set active range one below current active range, adding a new range if the current
						range is the last one
					</li>
				</Show>
			</ul>
		</details>
	);
};

export interface VideoPlayerProps {
	videoURL: string;
	errorList: Accessor<string[]>;
	setErrorList: Setter<string[]>;
	videoPlayer: Accessor<Hls>;
}

export const VideoPlayer: Component<VideoPlayerProps> = (props) => {
	if (!Hls.isSupported()) {
		const newError =
			"Your browser doesn't support MediaSource extensions. Video playback and editing won't work.";
		props.setErrorList([...props.errorList(), newError]);
		return <></>;
	}

	let videoElement;
	createEffect(() => {
		if (videoElement) {
			props.videoPlayer().attachMedia(videoElement);
		}
	});

	return <video ref={videoElement} controls={true}></video>;
};
