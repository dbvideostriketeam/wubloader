import {
	Accessor,
	Component,
	createEffect,
	createSignal,
	For,
	Index,
	Setter,
	Show,
	untrack,
} from "solid-js";
import styles from "./RangeSelection.module.scss";
import {
	ChapterData,
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

import "vidstack/icons";

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
	enableChapterEntry: Accessor<boolean>;
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

						if (enteredStartTime === "") {
							untrack(props.rangeData)[index].setStartTime(null);
							return;
						}

						const playerTime = videoPlayerTimeForDisplayTime(enteredStartTime);
						const startTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
						if (startTime !== null) {
							untrack(props.rangeData)[index].setStartTime(startTime);
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

						if (enteredEndTime === "") {
							untrack(props.rangeData)[index].setEndTime(null);
							return;
						}

						const playerTime = videoPlayerTimeForDisplayTime(enteredEndTime);
						const endTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
						if (endTime !== null) {
							untrack(props.rangeData)[index].setEndTime(endTime);
						}
					});

					const setStartPoint = () => {
						const currentTime = props.videoPlayerTime();
						const fragments = props.videoFragments();
						const time = dateTimeFromVideoPlayerTime(currentTime, fragments);
						if (time === null) {
							return;
						}
						untrack(props.rangeData)[index].setStartTime(time);
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

					const addChapter = (event) => {
						currentRangeData().setChapters([...currentRangeData().chapters(), new ChapterData()]);
					};

					return (
						<>
							<Show when={index > 0}>
								<div>
									<span class={styles.transitionLabel}>Transition:</span>
									<select onChange={setTransitionType}>
										<option value="" title="Hard cut between the time ranges">
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
										<span class={styles.transitionText}>over</span>
										<input
											class={styles.transitionDuration}
											type="number"
											min={0}
											step={1}
											value={currentRangeData().transitionSeconds()}
											onChange={setTransitionSeconds}
										/>
										<span class={styles.transitionText}>seconds</span>
										<button
											type="button"
											class={styles.transitionPreviewToggle}
											onClick={togglePreview}
										>
											<Show when={showPreview()} fallback="Show Preview">
												Hide Preview
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
							<Show when={props.enableChapterEntry()}>
								<div>
									<Index each={currentRangeData().chapters()}>
										{(currentChapter: Accessor<ChapterData>, index: number) => {
											const [enteredChapterTime, setEnteredChapterTime] = createSignal("");
											const [enteredDescription, setEnteredDescription] = createSignal("");

											createEffect(() => {
												const chapterTime = currentChapter().time;
												const fragments = props.videoFragments();
												if (chapterTime === null) {
													return;
												}
												const videoPlayerChapter = videoPlayerTimeFromDateTime(
													chapterTime,
													fragments,
												);
												if (videoPlayerChapter === null) {
													return;
												}
												setEnteredChapterTime(displayTimeForVideoPlayerTime(videoPlayerChapter));
											});

											createEffect(() => {
												const chapterTimeString = enteredChapterTime();
												const fragments = props.videoFragments();
												if (chapterTimeString === "") {
													const chapterData = untrack(currentChapter);
													chapterData.time = null;

													const rangeChapters = untrack(untrack(currentRangeData).chapters).slice();
													rangeChapters[index] = chapterData;
													untrack(currentRangeData).setChapters(rangeChapters);
													return;
												}

												const playerTime = videoPlayerTimeForDisplayTime(chapterTimeString);
												const chapterTime = dateTimeFromVideoPlayerTime(playerTime, fragments);

												const chapterData = untrack(currentChapter);
												chapterData.time = chapterTime;

												const rangeChapters = untrack(untrack(currentRangeData).chapters).slice();
												rangeChapters[index] = chapterData;
												untrack(currentRangeData).setChapters(rangeChapters);
											});

											const setChapterTime = () => {
												const currentTime = props.videoPlayerTime();
												const fragments = props.videoFragments();
												const time = dateTimeFromVideoPlayerTime(currentTime, fragments);
												if (time === null) {
													return;
												}

												const chapterData = currentChapter();
												chapterData.time = time;

												const rangeChapters = currentRangeData().chapters().slice();
												rangeChapters[index] = chapterData;
												currentRangeData().setChapters(rangeChapters);
											};

											const playFromChapterTime = () => {
												const currentTime = currentChapter().time;
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

											createEffect(() => {
												const chapterDescription = currentChapter().description;
												setEnteredDescription(chapterDescription);
											});

											createEffect(() => {
												const chapterDescription = enteredDescription();
												const chapterData = currentChapter();
												chapterData.description = chapterDescription;

												const rangeChapters = untrack(untrack(currentRangeData).chapters).slice();
												rangeChapters[index] = chapterData;
												untrack(currentRangeData).setChapters(rangeChapters);
											});

											const removeChapter = (event) => {
												const chapters = currentRangeData().chapters().slice();
												chapters.splice(index, 1);
												currentRangeData().setChapters(chapters);
											};

											return (
												<div class={styles.timeRangeEntryRow}>
													<div class={styles.timeRangeIcon}>
														<media-icon type="chapters" />
													</div>
													<div class={styles.timeRangeSelect}>
														<input
															type="text"
															use:bindingInputOnChange={[enteredChapterTime, setEnteredChapterTime]}
														/>
													</div>
													<div class={styles.timeRangeIcon}>
														<img
															class={styles.clickable}
															src={PencilIcon}
															alt="Set chapter time to current video time"
															title="Set chapter time to current video time"
															onClick={setChapterTime}
														/>
													</div>
													<div class={styles.timeRangeIcon}>
														<img
															class={styles.clickable}
															src={PlayToIcon}
															alt="Play from chapter marker"
															title="Play from chapter marker"
															onClick={playFromChapterTime}
														/>
													</div>
													<div class={styles.timeRangeDescription}>
														<input
															type="text"
															placeholder="Description"
															use:bindingInputOnChange={[enteredDescription, setEnteredDescription]}
														/>
													</div>
													<div class={styles.timeRangeIcon}>
														<img
															class={styles.clickable}
															src={RemoveIcon}
															alt="Remove this chapter"
															title="Remove this chapter"
															onClick={removeChapter}
														/>
													</div>
												</div>
											);
										}}
									</Index>
									<img
										class={`${styles.clickable} ${styles.addChapter}`}
										src={AddIcon}
										alt="Add chapter"
										title="Add chapter"
										onClick={addChapter}
									/>
								</div>
							</Show>
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
