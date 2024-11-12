import { Accessor, Component, createEffect, createSignal, Setter, Show } from "solid-js";
import { DateTime } from "luxon";
import {
	TimeType,
	wubloaderTimeFromDateTime,
	busTimeFromDateTime,
	timeAgoFromDateTime,
	dateTimeFromWubloaderTime,
	dateTimeFromBusTime,
	dateTimeFromTimeAgo,
} from "./convertTime";
import styles from "./video.module.scss";

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
	errorList: Accessor<string[]>;
	setErrorList: Setter<string[]>;
}

export const StreamTimeSettings: Component<StreamTimeSettingsProps> = (props) => {
	const [timeType, setTimeType] = createSignal<TimeType>(TimeType.UTC);

	const submitHandler = (event: SubmitEvent) => {
		event.preventDefault();

		const form = event.currentTarget as HTMLFormElement;
		const formData = new FormData(form);

		const streamName = formData.get("stream") as string;
		const startTimeEntered = formData.get("start-time") as string;
		const endTimeEntered = formData.get("end-time") as string;
		const timeType = +formData.get("time-type") as TimeType;

		let startTime: DateTime | null = null;
		let endTime: DateTime | null = null;
		switch (timeType) {
			case TimeType.UTC:
				startTime = dateTimeFromWubloaderTime(startTimeEntered);
				if (endTimeEntered !== "") {
					endTime = dateTimeFromWubloaderTime(endTimeEntered);
				}
				break;
			case TimeType.BusTime:
				startTime = dateTimeFromBusTime(props.busStartTime(), startTimeEntered);
				if (endTimeEntered !== "") {
					endTime = dateTimeFromBusTime(props.busStartTime(), endTimeEntered);
				}
				break;
			case TimeType.TimeAgo:
				startTime = dateTimeFromTimeAgo(startTimeEntered);
				if (endTimeEntered !== "") {
					endTime = dateTimeFromTimeAgo(endTimeEntered);
				}
				break;
		}

		if (startTime === null || (endTimeEntered !== "" && endTime === null)) {
			const error = "A load boundary time could not be parsed. Check the format of your times.";
			props.setErrorList([...props.errorList(), error]);
			return;
		}

		props.setStreamVideoInfo({
			streamName: streamName,
			streamStartTime: startTime,
			streamEndTime: endTime,
		});
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
