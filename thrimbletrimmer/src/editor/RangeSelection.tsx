import {
	Accessor,
	Component,
	createEffect,
	createSignal,
	createUniqueId,
	For,
	Setter,
	Show,
	untrack,
} from "solid-js";
import { FragmentTimes } from "../common/common";
import styles from "./RangeSelection.module.scss";
import {
	ChapterData,
	displayTimeForVideoPlayerTime,
	RangeData,
	TransitionDefinition,
	videoPlayerTimeForDisplayTime,
	videoPlayerTimeFromDateTime,
} from "./common";
import { bindingInputOnChange } from "../common/binding";
import { dateTimeFromVideoPlayerTime, wubloaderTimeFromDateTime } from "../common/convertTime";
import { StreamVideoInfo } from "../common/streamInfo";
import { VideoPlayer } from "../common/video";
import { MediaPlayerElement } from "vidstack/elements";
import { DateTime } from "luxon";
import {
	DragDropProvider,
	DragOverlay,
	DragDropEventHandlers,
	useDraggable,
	useDroppable,
} from "@dnd-kit/solid";

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
	setActiveKeyboardIndex: Setter<number>;
	streamInfo: Accessor<StreamVideoInfo>;
	allowHoles: Accessor<boolean>;
	videoPlayerTime: Accessor<number>;
	videoFragments: Accessor<FragmentTimes[]>;
	videoPlayer: Accessor<MediaPlayerElement>;
}

export const RangeSelection: Component<RangeSelectionProps> = (props) => {
	const addNewRange = (event: MouseEvent) => {
		props.setRangeData([...props.rangeData(), new RangeData()]);
	};

	const onDragEnd: DragDropEventHandlers["onDragEnd"] = (event) => {
		for (const element of document.getElementsByClassName(styles.dropTargetHover)) {
			element.classList.remove(styles.dropTargetHover);
		}

		const dragSource = event.operation.source;
		const dropTarget = event.operation.target;

		if (!dragSource || !dropTarget || !dragSource.element || !dropTarget.element) {
			return;
		}

		const dragSourceRangeIndexStr = (dragSource.element as HTMLDivElement).dataset.rangeindex;
		const dropTargetRangeIndexStr = (dropTarget.element as HTMLDivElement).dataset.rangeindex;

		if (!dragSourceRangeIndexStr || !dropTargetRangeIndexStr) {
			return;
		}
		const dragSourceRangeIndex = +dragSourceRangeIndexStr;
		const dropTargetRangeIndex = +dropTargetRangeIndexStr;

		if (dragSource.type === "range") {
			const rangeData = props.rangeData();
			const range = rangeData[dragSourceRangeIndex];
			const newRangeData = rangeData.toSpliced(dropTargetRangeIndex, 0, range);
			newRangeData.splice(
				dragSourceRangeIndex > dropTargetRangeIndex
					? dragSourceRangeIndex + 1
					: dragSourceRangeIndex,
				1,
			);
			props.setRangeData(newRangeData);
		} else if (dragSource.type === "chapter") {
			const dragSourceChapterIndexStr = (dragSource.element as HTMLDivElement).dataset.chapterindex;
			const dropTargetChapterIndexStr = (dropTarget.element as HTMLDivElement).dataset.chapterindex;

			if (!dragSourceChapterIndexStr || !dropTargetChapterIndexStr) {
				return;
			}
			const dragSourceChapterIndex = +dragSourceChapterIndexStr;
			const dropTargetChapterIndex = +dropTargetChapterIndexStr;

			const rangeData = props.rangeData();

			if (dragSourceRangeIndex === dropTargetRangeIndex) {
				const range = rangeData[dragSourceRangeIndex];
				const rangeChapters = range.chapters();
				const chapter = rangeChapters[dragSourceChapterIndex];
				const newChapters = rangeChapters.toSpliced(dropTargetChapterIndex, 0, chapter);
				newChapters.splice(
					dragSourceChapterIndex > dropTargetChapterIndex
						? dragSourceChapterIndex + 1
						: dragSourceChapterIndex,
					1,
				);
				range.setChapters(newChapters);
			} else {
				const draggableRange = rangeData[dragSourceRangeIndex];
				const droppableRange = rangeData[dropTargetRangeIndex];

				const draggableChapters = draggableRange.chapters();
				const droppableChapters = droppableRange.chapters();

				const chapter = draggableChapters[dragSourceChapterIndex];

				const newDroppableChapters = droppableChapters.toSpliced(
					dropTargetChapterIndex,
					0,
					chapter,
				);
				const newDraggableChapters = draggableChapters.toSpliced(dragSourceChapterIndex, 1);

				draggableRange.setChapters(newDraggableChapters);
				droppableRange.setChapters(newDroppableChapters);
			}
		}
	};

	const onDragOver: DragDropEventHandlers["onDragOver"] = (event) => {
		const droppableElement = event.operation.target?.element ?? null;
		if (droppableElement) {
			droppableElement.classList.add(styles.dropTargetHover);
		}
		for (const element of document.getElementsByClassName(styles.dropTargetHover)) {
			if (element !== droppableElement) {
				element.classList.remove(styles.dropTargetHover);
			}
		}
	};

	return (
		<DragDropProvider onDragEnd={onDragEnd} onDragOver={onDragOver}>
			<div class={styles.rangeRegion}>
				<For each={props.rangeData()}>
					{(range: RangeData, rangeIndex: Accessor<number>) => {
						const currentRangeData = () => range;
						const rangeId = createUniqueId();
						const setTransitionType = (event: Event) => {
							const sourceSelection = event.currentTarget as HTMLSelectElement;
							props.rangeData()[rangeIndex()].setTransitionType(sourceSelection.value);
						};
						const setTransitionSeconds = (event: Event) => {
							const sourceSelection = event.currentTarget as HTMLInputElement;
							props.rangeData()[rangeIndex()].setTransitionSeconds(+sourceSelection.value);
						};

						const [previewPlayerTime, setPreviewPlayerTime] = createSignal(0);
						const [previewMediaPlayerElement, setPreviewMediaPlayerElement] =
							createSignal<MediaPlayerElement>();
						const [showPreview, setShowPreview] = createSignal(false);

						const togglePreview = () => {
							setShowPreview(!showPreview());
						};

						const previewVideoURL = () => {
							if (rangeIndex() === 0) {
								return "";
							}

							const previousRange = props.rangeData()[rangeIndex() - 1];
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
							if (fragments.length === 0) {
								return;
							}
							if (rangeStartTime === null) {
								setStartTimeFieldValue("");
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

							if (fragments.length === 0) {
								// If the fragments haven't loaded yet, we shouldn't start setting the start time.
								return;
							}

							if (enteredStartTime === "") {
								untrack(props.rangeData)[rangeIndex()].setStartTime(null);
								return;
							}

							const playerTime = videoPlayerTimeForDisplayTime(enteredStartTime);
							const startTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
							if (startTime !== null) {
								untrack(props.rangeData)[rangeIndex()].setStartTime(startTime);
							}
						});

						createEffect(() => {
							const rangeEndTime = currentRangeData().endTime();
							const fragments = props.videoFragments();
							if (fragments.length === 0) {
								return;
							}
							if (rangeEndTime === null) {
								setEndTimeFieldValue("");
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

							if (fragments.length === 0) {
								// If the fragments haven't loaded yet, we shouldn't start setting the end time.
								return;
							}

							if (enteredEndTime === "") {
								untrack(props.rangeData)[rangeIndex()].setEndTime(null);
								return;
							}

							const playerTime = videoPlayerTimeForDisplayTime(enteredEndTime);
							const endTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
							if (endTime !== null) {
								untrack(props.rangeData)[rangeIndex()].setEndTime(endTime);
							}
						});

						const setStartPoint = () => {
							const currentTime = props.videoPlayerTime();
							const fragments = props.videoFragments();
							const time = dateTimeFromVideoPlayerTime(currentTime, fragments);
							if (time === null) {
								return;
							}
							untrack(props.rangeData)[rangeIndex()].setStartTime(time);
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
							props.rangeData()[rangeIndex()].setEndTime(time);
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
							if (ranges.length <= 1) {
								return;
							}
							const newRanges = ranges.slice();
							newRanges.splice(rangeIndex(), 1);
							newRanges[0].setTransitionType("");
							props.setRangeData(newRanges);
							props.setActiveKeyboardIndex((activeIndex) =>
								activeIndex >= rangeIndex() ? Math.max(0, activeIndex - 1) : activeIndex,
							);
						};

						const addChapter = (event: MouseEvent) => {
							currentRangeData().setChapters([...currentRangeData().chapters(), new ChapterData()]);
						};

						const rangeDraggable = useDraggable({ id: rangeId, type: "range" });
						const rangeDraggableRef = rangeDraggable.ref;

						const rangeDroppable = useDroppable({ id: rangeId, accept: "range" });
						const rangeDroppableRef = rangeDroppable.ref;

						const chapterDroppableEnd = useDroppable({
							id: `${rangeId}-chapter-end`,
							accept: "chapter",
						});
						const chapterDroppableEndRef = chapterDroppableEnd.ref;

						return (
							<>
								<div
									ref={rangeDroppableRef}
									class={styles.rangeDropTarget}
									data-rangeindex={rangeIndex()}
								></div>
								<div ref={rangeDraggableRef} data-rangeindex={rangeIndex()}>
									<Show when={rangeIndex() > 0}>
										<div>
											<span class={styles.transitionLabel}>Transition:</span>
											<select onChange={setTransitionType}>
												<option
													value=""
													title="Hard cut between the time ranges"
													selected={currentRangeData().transitionType() === ""}
												>
													cut
												</option>
												<For each={props.allTransitions}>
													{(item: TransitionDefinition, index: Accessor<number>) => {
														return (
															<option
																value={item.name}
																title={item.description}
																selected={currentRangeData().transitionType() === item.name}
															>
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
														setMediaPlayer={
															setPreviewMediaPlayerElement as Setter<MediaPlayerElement>
														}
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
											<Show when={props.rangeData().length > 1}>
												<img
													class={styles.clickable}
													src={RemoveIcon}
													alt="Remove this time range"
													title="Remove this time range"
													onClick={removeHandler}
												/>
											</Show>
										</div>
										<div class={styles.timeRangeIcon}>
											<Show when={props.activeKeyboardIndex() === rangeIndex()}>
												<img
													src={ArrowIcon}
													alt="This is the active range for keyboard shortcuts."
													title="This is the active range for keyboard shortcuts."
												/>
											</Show>
										</div>
									</div>
									<div>
										<For each={currentRangeData().chapters()}>
											{(chapter: ChapterData, chapterIndex: Accessor<number>) => {
												const currentChapter = () => chapter;
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
													if (fragments.length === 0) {
														// If there are no fragments, we haven't loaded any video yet, which doesn't mean that we should throw away all the chapter times.
														return;
													}
													if (chapterTimeString === "") {
														const chapterData = untrack(currentChapter);
														chapterData.time = null;

														const rangeChapters = untrack(
															untrack(currentRangeData).chapters,
														).slice();
														rangeChapters[chapterIndex()] = chapterData;
														untrack(currentRangeData).setChapters(rangeChapters);
														return;
													}

													const playerTime = videoPlayerTimeForDisplayTime(chapterTimeString);
													const chapterTime = dateTimeFromVideoPlayerTime(playerTime, fragments);

													const chapterData = untrack(currentChapter);
													chapterData.time = chapterTime;

													const rangeChapters = untrack(untrack(currentRangeData).chapters).slice();
													rangeChapters[chapterIndex()] = chapterData;
													untrack(currentRangeData).setChapters(rangeChapters);
												});

												const setChapterTime = () => {
													const currentTime = props.videoPlayerTime();
													const fragments = props.videoFragments();
													const time = dateTimeFromVideoPlayerTime(currentTime, fragments);
													if (time === null) {
														return;
													}

													const chapterData = structuredClone(currentChapter());
													chapterData.time = time;

													const rangeChapters = currentRangeData().chapters().slice();
													rangeChapters[chapterIndex()] = chapterData;
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
													rangeChapters[chapterIndex()] = chapterData;
													untrack(currentRangeData).setChapters(rangeChapters);
												});

												const removeChapter = (event: MouseEvent) => {
													const chapters = currentRangeData().chapters().slice();
													chapters.splice(chapterIndex(), 1);
													currentRangeData().setChapters(chapters);
												};

												const chapterDraggable = useDraggable({
													id: chapter.id,
													type: "chapter",
												});
												const chapterDraggableRef = chapterDraggable.ref;

												const chapterDroppable = useDroppable({
													id: chapter.id,
													accept: "chapter",
												});
												const chapterDroppableRef = chapterDroppable.ref;

												return (
													<>
														<div
															class={styles.chapterDropTarget}
															ref={chapterDroppableRef}
															data-rangeindex={rangeIndex()}
															data-chapterindex={chapterIndex()}
														></div>
														<div
															class={`${styles.timeRangeEntryRow} ${styles.chapterDropTarget}`}
															ref={chapterDraggableRef}
															style={{ visibility: chapterDraggable.isDragSource() ? "hidden" : undefined }}
															data-rangeindex={rangeIndex()}
															data-chapterindex={chapterIndex()}
														>
															<div class={styles.timeRangeIcon}>
																<media-icon type="chapters" />
															</div>
															<div class={styles.timeRangeSelect}>
																<input
																	type="text"
																	use:bindingInputOnChange={[
																		enteredChapterTime,
																		setEnteredChapterTime,
																	]}
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
																	use:bindingInputOnChange={[
																		enteredDescription,
																		setEnteredDescription,
																	]}
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
													</>
												);
											}}
										</For>
										<div
											ref={chapterDroppableEndRef}
											class={styles.chapterDropTarget}
											data-rangeindex={rangeIndex()}
											data-chapterindex={currentRangeData().chapters().length}
										>
											<img
												class={`${styles.clickable} ${styles.addChapter}`}
												src={AddIcon}
												alt="Add chapter"
												title="Add chapter"
												onClick={addChapter}
											/>
										</div>
									</div>
								</div>
							</>
						);
					}}
				</For>
				{(() => {
					const droppableEnd = useDroppable({ id: "range-end", accept: "range" });
					const droppableEndRef = droppableEnd.ref;

					return (
						<div
							ref={droppableEndRef}
							class={styles.rangeDropTarget}
							data-rangeindex={props.rangeData().length.toString()}
						>
							<img
								class={styles.clickable}
								src={AddIcon}
								alt="Add another time range"
								title="Add another time range"
								onClick={addNewRange}
							/>
						</div>
					);
				})()}
			</div>
			<DragOverlay
				disabled={(source) => source?.type !== "chapter"}
			>
				{(source) => {
					const preview = source.element!.cloneNode(true) as HTMLElement;
					preview.style.visibility = "visible";
					return preview;
				}}
			</DragOverlay>
		</DragDropProvider>
	);
};
