import {
	Accessor,
	Component,
	createEffect,
	createSignal,
	For,
	Index,
	Setter,
	Show,
} from "solid-js";
import styles from "./RangeSelection.module.scss";
import {
	dateTimeFromVideoPlayerTime,
	defaultRangeData,
	displayTimeForVideoPlayerTime,
	FragmentTimes,
	RangeData,
	TransitionDefinition,
	videoPlayerTimeForDisplayTime,
	videoPlayerTimeFromDateTime,
} from "./common";
import { bindingInputOnChange } from "../common/binding";
import { wubloaderTimeFromDateTime } from "../common/convertTime";
import { StreamVideoInfo } from "../common/streamInfo";
import { VideoPlayer } from "../common/video";
import { MediaPlayerElement } from "vidstack/elements";
import { DateTime } from "luxon";

import AddIcon from "../assets/plus.png";
import ArrowIcon from "../assets/arrow.png";
import PencilIcon from "../assets/pencil.png";
import PlayToIcon from "../assets/play_to.png";
import RemoveIcon from "../assets/minus.png";

interface RangeSelectionProps {
	rangeData: Accessor<RangeData[]>;
	setRangeData: Setter<RangeData[]>;
	allTransitions: TransitionDefinition[];
	activeKeyboardIndex: Accessor<number>;
	streamInfo: Accessor<StreamVideoInfo>;
	allowHoles: Accessor<boolean>;
	videoPlayerTime: Accessor<number>;
	videoFragments: Accessor<FragmentTimes[]>;
	videoPlayer: Accessor<MediaPlayerElement>;
}

export const RangeSelection: Component<RangeSelectionProps> = (props) => {
	const addNewRange = (event) => {
		props.setRangeData([...props.rangeData(), defaultRangeData()]);
	};

	return (
		<div class={styles.rangeRegion}>
			<Index each={props.rangeData()}>
				{(currentRangeData: Accessor<RangeData>, index: number) => {
					const setTransitionType = (event) => {
						const sourceSelection: HTMLSelectElement = event.currentTarget;
						props.rangeData()[index].setTransitionType(sourceSelection.value);
					};
					const setTransitionSeconds = (event) => {
						const sourceSelection: HTMLInputElement = event.currentTarget;
						props.rangeData()[index].setTransitionSeconds(+sourceSelection.value);
					};

					const [previewPlayerTime, setPreviewPlayerTime] = createSignal(0);
					const [previewMediaPlayerElement, setPreviewMediaPlayerElement] =
						createSignal<MediaPlayerElement>();
					const [showPreview, setShowPreview] = createSignal(false);

					const togglePreview = () => {
						setShowPreview(!showPreview());
					};

					const previewVideoURL = () => {
						if (index === 0) {
							return "";
						}

						const previousRange = props.rangeData()[index - 1];
						const durationAndPadding = currentRangeData().transitionSeconds() + 5;
						const currentStart = currentRangeData().startTime();
						const currentEnd = currentRangeData().endTime();
						const previousStart = previousRange.startTime();
						const previousEnd = previousRange.endTime();
						if (
							previousStart === null ||
							previousEnd === null ||
							currentStart === null ||
							currentEnd === null
						) {
							return "";
						}

						const previousRangeStart = DateTime.max(
							previousStart,
							previousEnd.minus({ seconds: durationAndPadding }),
						);
						const currentRangeEnd = DateTime.min(
							currentEnd,
							currentStart.plus({ seconds: durationAndPadding }),
						);
						const previousRangeString = `${wubloaderTimeFromDateTime(previousRangeStart)},${wubloaderTimeFromDateTime(previousEnd)}`;
						const currentRangeString = `${wubloaderTimeFromDateTime(currentStart)},${wubloaderTimeFromDateTime(currentRangeEnd)}`;
						const transitionString =
							currentRangeData().transitionType() === ""
								? ""
								: `${currentRangeData().transitionType()},${currentRangeData().transitionSeconds()}`;

						const urlParams = new URLSearchParams({
							type: "webm",
							allow_holes: props.allowHoles().toString(),
							transition: transitionString,
						});
						urlParams.append("range", previousRangeString);
						urlParams.append("range", currentRangeString);

						return `/cut/${props.streamInfo().streamName}/480p.ts?${urlParams.toString()}`;
					};

					const [startTimeFieldValue, setStartTimeFieldValue] = createSignal("");
					const [endTimeFieldValue, setEndTimeFieldValue] = createSignal("");

					// Synchronize the field values with store values
					createEffect(() => {
						const rangeStartTime = currentRangeData().startTime();
						const fragments = props.videoFragments();
						if (rangeStartTime === null) {
							return;
						}
						const videoPlayerStart = videoPlayerTimeFromDateTime(rangeStartTime, fragments);
						if (videoPlayerStart === null) {
							return;
						}
						setStartTimeFieldValue(displayTimeForVideoPlayerTime(videoPlayerStart));
					});

					createEffect(() => {
						const enteredStartTime = startTimeFieldValue();
						const fragments = props.videoFragments();

						const playerTime = videoPlayerTimeForDisplayTime(enteredStartTime);
						const startTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
						if (startTime !== null) {
							props.rangeData()[index].setStartTime(startTime);
						}
					});

					createEffect(() => {
						const rangeEndTime = currentRangeData().endTime();
						const fragments = props.videoFragments();
						if (rangeEndTime === null) {
							return;
						}
						const videoPlayerEnd = videoPlayerTimeFromDateTime(rangeEndTime, fragments);
						if (videoPlayerEnd === null) {
							return;
						}
						setEndTimeFieldValue(displayTimeForVideoPlayerTime(videoPlayerEnd));
					});

					createEffect(() => {
						const enteredEndTime = endTimeFieldValue();
						const fragments = props.videoFragments();

						const playerTime = videoPlayerTimeForDisplayTime(enteredEndTime);
						const endTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
						if (endTime !== null) {
							props.rangeData()[index].setEndTime(endTime);
						}
					});

					const setStartPoint = () => {
						const currentTime = props.videoPlayerTime();
						const fragments = props.videoFragments();
						const time = dateTimeFromVideoPlayerTime(currentTime, fragments);
						if (time === null) {
							return;
						}
						props.rangeData()[index].setStartTime(time);
					};

					const playFromStartTime = () => {
						const currentTime = currentRangeData().startTime();
						const fragments = props.videoFragments();
						if (currentTime === null) {
							return;
						}
						const time = videoPlayerTimeFromDateTime(currentTime, fragments);
						if (time === null) {
							return;
						}
						props.videoPlayer().currentTime = time;
					};

					const setEndPoint = () => {
						const currentTime = props.videoPlayerTime();
						const fragments = props.videoFragments();
						const time = dateTimeFromVideoPlayerTime(currentTime, fragments);
						if (time === null) {
							return;
						}
						props.rangeData()[index].setEndTime(time);
					};

					const playFromEndTime = () => {
						const currentTime = currentRangeData().endTime();
						const fragments = props.videoFragments();
						if (currentTime === null) {
							return;
						}
						const time = videoPlayerTimeFromDateTime(currentTime, fragments);
						if (time === null) {
							return;
						}
						props.videoPlayer().currentTime = time;
					};

					const removeHandler = () => {
						const ranges = props.rangeData();
						const newRanges = ranges.slice();
						newRanges.splice(index, 1);
						props.setRangeData(newRanges);
					};

					return (
						<>
							<Show when={index > 0}>
								<div>
									<span class={styles.transitionLabel}>Transition:</span>
									<select onSelect={setTransitionType}>
										<option value="cut" title="Hard cut between the time ranges">
											cut
										</option>
										<For each={props.allTransitions}>
											{(item: TransitionDefinition, index: Accessor<number>) => {
												return (
													<option value={item.name} title={item.description}>
														{item.name}
													</option>
												);
											}}
										</For>
									</select>
									<Show when={currentRangeData().transitionType() !== ""}>
										over
										<input
											type="number"
											value={currentRangeData().transitionSeconds()}
											onChange={setTransitionSeconds}
										/>
										seconds
										<button type="button" onClick={togglePreview}>
											<Show when={showPreview()} fallback="Hide Preview">
												Show Preview
											</Show>
										</button>
									</Show>
									<Show when={showPreview()}>
										<div class={styles.previewVideoPlayer}>
											<VideoPlayer
												src={previewVideoURL}
												setPlayerTime={setPreviewPlayerTime}
												mediaPlayer={previewMediaPlayerElement as Accessor<MediaPlayerElement>}
												setMediaPlayer={setPreviewMediaPlayerElement as Setter<MediaPlayerElement>}
											/>
										</div>
									</Show>
								</div>
							</Show>
							<div class={styles.timeRangeEntryRow}>
								<div class={styles.timeRangeSelect}>
									<input
										type="text"
										class={styles.timeField}
										use:bindingInputOnChange={[startTimeFieldValue, setStartTimeFieldValue]}
									/>
								</div>
								<div class={styles.timeRangeIcon}>
									<img
										class={styles.clickable}
										src={PencilIcon}
										alt="Set range start point to current video time"
										title="Set range start point to current video time"
										onClick={setStartPoint}
									/>
								</div>
								<div class={styles.timeRangeIcon}>
									<img
										class={styles.clickable}
										src={PlayToIcon}
										alt="Play from the start point"
										title="Play from the start point"
										onClick={playFromStartTime}
									/>
								</div>
								<div class={styles.timeRangeSelect}>
									<input
										type="text"
										class={styles.timeField}
										use:bindingInputOnChange={[endTimeFieldValue, setEndTimeFieldValue]}
									/>
								</div>
								<div class={styles.timeRangeIcon}>
									<img
										class={styles.clickable}
										src={PencilIcon}
										alt="Set range end point to current video time"
										title="Set range end point to current video time"
										onClick={setEndPoint}
									/>
								</div>
								<div class={styles.timeRangeIcon}>
									<img
										class={styles.clickable}
										src={PlayToIcon}
										alt="Play from the end point"
										title="Play from the end point"
										onClick={playFromEndTime}
									/>
								</div>
								<div class={styles.timeRangeIcon}>
									<img
										class={styles.clickable}
										src={RemoveIcon}
										alt="Remove this time range"
										title="Remove this time range"
										onClick={removeHandler}
									/>
								</div>
								<div class={styles.timeRangeIcon}>
									<Show when={props.activeKeyboardIndex() === index}>
										<img
											src={ArrowIcon}
											alt="This is the active range for keyboard shortcuts."
											title="This is the active range for keyboard shortcuts."
										/>
									</Show>
								</div>
							</div>
						</>
					);
				}}
			</Index>
			<div>
				<img
					class={styles.clickable}
					src={AddIcon}
					alt="Add another time range"
					title="Add another time range"
					onClick={addNewRange}
				/>
			</div>
		</div>
	);
};
