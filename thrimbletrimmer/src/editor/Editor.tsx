import {
	Accessor,
	Component,
	createEffect,
	createResource,
	createSignal,
	For,
	Index,
	onMount,
	Setter,
	Show,
	Suspense,
} from "solid-js";
import { leadingAndTrailing, throttle } from "@solid-primitives/scheduled";
import { DateTime } from "luxon";
import { MediaPlayerElement } from "vidstack/elements";
import styles from "./Editor.module.scss";
import { bindingInputOnChange } from "../common/binding";
import { StreamVideoInfo } from "../common/streamInfo";
import { dateTimeFromWubloaderTime, wubloaderTimeFromDateTime } from "../common/convertTime";
import { KeyboardShortcuts, StreamTimeSettings, VideoPlayer } from "../common/video";
import AddIcon from "../assets/plus.png";
import ArrowIcon from "../assets/arrow.png";
import PencilIcon from "../assets/pencil.png";
import PlayToIcon from "../assets/play_to.png";
import RemoveIcon from "../assets/minus.png";

const CHAPTER_MARKER_DELIMITER = "\n==========\n";
const CHAPTER_MARKER_DELIMITER_PARTIAL = "==========";

export interface VideoData {
	id: string;
	sheet_name: string;
	event_start: string | null;
	event_end: string | null;
	category: string;
	description: string;
	submitter_winner: string;
	poster_moment: boolean;
	image_links: string[];
	notes: string;
	tags: string[];
	allow_holes: boolean;
	uploader_whitelist: string[] | null;
	upload_location: string | null;
	public: boolean;
	video_ranges: [string, string][] | null;
	video_transitions: ([string, number] | null)[] | null;
	video_title: string | null;
	video_description: string | null;
	video_tags: string[] | null;
	video_channel: string;
	video_quality: string;
	thumbnail_mode: string;
	thumbnail_time: string;
	thumbnail_template: string | null; // Can be null if no templates are set up
	thumbnail_image: string | null; // Base64 of the thumbnail data
	thumbnail_last_written: string | null;
	thumbnail_crop: [number, number, number, number] | null;
	thumbnail_location: [number, number, number, number] | null;
	state: string;
	uploader: string | null;
	error: string | null;
	video_id: string | null;
	video_link: string | null;
	editor: string | null;
	edit_time: string | null;
	upload_time: string | null;
	last_modified: string | null;
	title_prefix: string;
	title_max_length: number;
	bustime_start: string;
	upload_locations: string[];
	category_notes?: string;
}

class RangeData {
	startTime: Accessor<DateTime | null>;
	setStartTime: Setter<DateTime | null>;
	endTime: Accessor<DateTime | null>;
	setEndTime: Setter<DateTime | null>;
	transitionType: Accessor<string>;
	setTransitionType: Setter<string>;
	transitionSeconds: Accessor<number>;
	setTransitionSeconds: Setter<number>;
	chapters: Accessor<ChapterData[]>;
	setChapters: Setter<ChapterData[]>;
}

class ChapterData {
	time: DateTime | null;
	description: string;
}

class FragmentTimes {
	rawStart: DateTime;
	rawEnd: DateTime;
	playerStart: number;
	duration: number;
}

class TransitionDefinition {
	name: string;
	description: string;
}

function defaultRangeData(): RangeData {
	const data = new RangeData();
	[data.startTime, data.setStartTime] = createSignal<DateTime | null>(null);
	[data.endTime, data.setEndTime] = createSignal<DateTime | null>(null);
	[data.transitionType, data.setTransitionType] = createSignal("");
	[data.transitionSeconds, data.setTransitionSeconds] = createSignal(0);
	[data.chapters, data.setChapters] = createSignal<ChapterData[]>([]);
	return data;
}

function videoPlayerTimeFromDateTime(
	datetime: DateTime,
	fragments: FragmentTimes[],
): number | null {
	for (const fragmentTimes of fragments) {
		if (datetime >= fragmentTimes.rawStart && datetime <= fragmentTimes.rawEnd) {
			return fragmentTimes.playerStart + datetime.diff(fragmentTimes.rawStart).as("seconds");
		}
	}
	return null;
}

function dateTimeFromVideoPlayerTime(time: number, fragments: FragmentTimes[]): DateTime | null {
	for (const fragmentTimes of fragments) {
		const fragmentStart = fragmentTimes.playerStart;
		const fragmentEnd = fragmentStart + fragmentTimes.duration;
		if (time >= fragmentStart && time <= fragmentEnd) {
			const offset = time - fragmentStart;
			return fragmentTimes.rawStart.plus({ seconds: offset });
		}
	}
	return null;
}

function displayTimeForVideoPlayerTime(time: number): string {
	const minutes = Math.trunc(time / 60);
	const secondsRaw = Math.trunc(time % 60);
	const seconds = secondsRaw < 10 ? `0${secondsRaw}` : secondsRaw;
	const millisecondsRaw = Math.round((time % 1) * 1000);
	let milliseconds: string | number;
	if (millisecondsRaw < 10) {
		milliseconds = `00${millisecondsRaw}`;
	} else if (millisecondsRaw < 100) {
		milliseconds = `0${millisecondsRaw}`;
	} else {
		milliseconds = millisecondsRaw;
	}

	return `${minutes}:${seconds}.${milliseconds}`;
}

function videoPlayerTimeForDisplayTime(time: string): number {
	const parts = time.split(":");
	if (parts.length === 1) {
		return +time;
	}

	let hours = 0;
	let minutes = 0;
	let seconds = 0;
	if (parts.length < 3) {
		minutes = +parts[0];
		seconds = +parts[1];
	} else {
		hours = +parts[0];
		minutes = +parts[1];
		seconds = +parts[2];
	}

	return hours * 3600 + minutes * 60 + seconds;
}

export const Editor: Component = () => {
	const currentURL = new URL(location.href);
	const videoID = currentURL.searchParams.get("id");

	if (!videoID) {
		return (
			<div class={styles.fullPageError}>
				No video ID was provided. As fun as it might be, you can't edit none video.
			</div>
		);
	}

	if (
		videoID === "defaults" ||
		videoID === "transitions" ||
		videoID === "templates" ||
		videoID === "challenges"
	) {
		return (
			<div class={styles.fullPageError}>
				Silly, you thought you could break this by passing an "ID" that can return data in a
				different format? Hah! You can't!
			</div>
		);
	}

	const [pageErrors, setPageErrors] = createSignal<string[]>([]);
	const [videoData] = createResource<VideoData | null>(async (source, { value, refetching }) => {
		const response = await fetch(`/thrimshim/${videoID}`);
		if (!response.ok) {
			return null;
		}
		return await response.json();
	});
	return (
		<Suspense>
			<Show when={videoData() !== undefined}>
				<EditorContent data={videoData()} />
			</Show>
		</Suspense>
	);
};

interface ContentProps {
	data: VideoData | null | undefined;
}

const EditorContent: Component<ContentProps> = (props) => {
	if (props.data === undefined) {
		throw new Error("Video data should have a value through Suspense");
	}
	if (props.data === null) {
		return (
			<div class={styles.fullPageError}>
				The video you tried to load is not a real video (it could not be found in the database). Are
				you sure this was a valid link?
			</div>
		);
	}

	const [pageErrors, setPageErrors] = createSignal<string[]>([]);

	const initialVideoRanges: [DateTime, DateTime][] = [];
	if (props.data.video_ranges) {
		for (const range of props.data.video_ranges) {
			const rangeStart = dateTimeFromWubloaderTime(range[0])!;
			const rangeEnd = dateTimeFromWubloaderTime(range[1])!;
			initialVideoRanges.push([rangeStart, rangeEnd]);
		}
	}

	const streamInfo = new StreamVideoInfo();
	if (props.data.upload_location) {
		streamInfo.streamName = props.data.upload_location;
	} else {
		streamInfo.streamName = props.data.video_channel;
	}
	let streamStart = dateTimeFromWubloaderTime(props.data.event_start);
	if (!streamStart) {
		return (
			<div class={styles.fullPageError}>
				The video you tried to load has an invalid start time. Please ensure a start time has been
				set for this entry.
			</div>
		);
	}
	let streamEnd = dateTimeFromWubloaderTime(props.data.event_end);

	for (const range of initialVideoRanges) {
		if (range[0] < streamStart) {
			streamStart = range[0];
		}
		if (!streamEnd || range[1] > streamEnd) {
			streamEnd = range[1];
		}
	}

	// To allow for things starting slightly before the logged time, pad the start by a minute
	streamStart = streamStart.minus({ minutes: 1 });
	// To allow for late ends and for the end of the minute that was written, pad the end by two minutes
	if (streamEnd) {
		streamEnd = streamEnd.plus({ minutes: 2 });
	}

	streamInfo.streamStartTime = streamStart;
	streamInfo.streamEndTime = streamEnd;

	const [streamVideoInfo, setStreamVideoInfo] = createSignal(streamInfo);
	const [busStartTime, setBusStartTime] = createSignal(
		dateTimeFromWubloaderTime(props.data.bustime_start)!,
	);
	const [chaptersEnabled, setChaptersEnabled] = createSignal(
		(props.data.video_description ?? "").indexOf(CHAPTER_MARKER_DELIMITER) !== -1,
	);

	const descriptionParts = (props.data.video_description ?? "").split(CHAPTER_MARKER_DELIMITER, 2);
	const description = descriptionParts[0];
	const chaptersRawString = descriptionParts.length > 1 ? descriptionParts[1] : "";
	const chaptersRawLines = chaptersRawString === "" ? [] : chaptersRawString.split("\n");
	const chaptersByRange: ChapterData[][] = [];
	for (const chapterLine of chaptersRawLines) {
		const parts = chapterLine.split(" - ");
		const timeData = parts.shift();
		if (!timeData) {
			continue;
		}
		const description = parts.join(" - ");

		const timeParts = timeData.split(";");
		const rangeIndex = +timeParts[0];
		const time = dateTimeFromWubloaderTime(timeParts[1]);

		const chapterDefinition = {
			time: time,
			description: description,
		};

		while (chaptersByRange.length <= rangeIndex) {
			chaptersByRange.push([]);
		}
		chaptersByRange[rangeIndex].push(chapterDefinition);
	}
	for (const rangeChapters of chaptersByRange) {
		rangeChapters.sort((a, b) => {
			if (a.time === null && b.time === null) {
				return 0;
			}
			// Sort null last so blank values appear at the end in the UI
			if (a.time === null) {
				return 1;
			}
			if (b.time === null) {
				return -1;
			}
			return a.time.toMillis() - b.time.toMillis();
		});
	}

	const initialVideoData: RangeData[] = [];
	const transitions = props.data.video_transitions;
	if (transitions !== null) {
		transitions.unshift(null);
	}
	for (let index = 0; index < initialVideoRanges.length; index++) {
		const rangeStart = initialVideoRanges[index][0];
		const rangeEnd = initialVideoRanges[index][1];

		let transitionType = "cut";
		let transitionSeconds = 0;
		if (transitions && index < transitions.length) {
			const thisTransition = transitions[index];
			if (thisTransition) {
				transitionType = thisTransition[0];
				transitionSeconds = thisTransition[1];
			}
		}

		const rangeData = new RangeData();
		[rangeData.startTime, rangeData.setStartTime] = createSignal<DateTime | null>(rangeStart);
		[rangeData.endTime, rangeData.setEndTime] = createSignal<DateTime | null>(rangeEnd);
		[rangeData.transitionType, rangeData.setTransitionType] = createSignal(transitionType);
		[rangeData.transitionSeconds, rangeData.setTransitionSeconds] = createSignal(transitionSeconds);
		[rangeData.chapters, rangeData.setChapters] = createSignal(chaptersByRange[index] ?? []);
		initialVideoData.push(rangeData);
	}

	const [videoData, setVideoData] = createSignal(initialVideoData);
	const [playerTime, setPlayerTime] = createSignal(0);
	const [mediaPlayer, setMediaPlayer] = createSignal<MediaPlayerElement>();
	const [downloadType, setDownloadType] = createSignal("smart");
	const [videoPlayerTime, setVideoPlayerTime] = createSignal(0);
	const [videoDuration, setVideoDuration] = createSignal(0);
	const [allFragmentTimes, setAllFragmentTimes] = createSignal<FragmentTimes[][]>([[]]);
	const [currentQualityLevel, setCurrentQualityLevel] = createSignal(0);
	const [videoDescription, setVideoDescription] = createSignal(description);
	const [allowHoles, setAllowHoles] = createSignal(false);

	const videoFragmentTimes = () => {
		return allFragmentTimes()[currentQualityLevel()];
	};

	const [allTransitions] = createResource<TransitionDefinition[]>(
		async (source, { value, refetching }) => {
			const transitionResponse = await fetch("/thrimshim/transitions");
			if (!transitionResponse.ok) {
				return [];
			}
			return await transitionResponse.json();
		},
	);
	const [activeKeyboardIndex, setActiveKeyboardIndex] = createSignal(0);

	onMount(() => {
		const player = mediaPlayer();
		if (player) {
			player.addEventListener("hls-level-loaded", (event) => {
				const times: FragmentTimes[] = [];
				for (const fragment of event.detail.details.fragments) {
					if (fragment.rawProgramDateTime === null) {
						continue;
					}
					const timeDefinition = new FragmentTimes();
					timeDefinition.rawStart = DateTime.fromISO(fragment.rawProgramDateTime, { zone: "UTC" });
					timeDefinition.rawEnd = timeDefinition.rawStart.plus({ seconds: fragment.duration });
					timeDefinition.playerStart = fragment.start;
					timeDefinition.duration = fragment.duration;
					times.push(timeDefinition);
				}
				const fragmentTimes = allFragmentTimes().slice(); // With no arguments, `slice` shallow clones the array
				while (fragmentTimes.length <= event.detail.level) {
					fragmentTimes.push([]);
				}
				fragmentTimes[event.detail.level] = times;
				setAllFragmentTimes(fragmentTimes);
			});
			player.addEventListener("hls-level-switched", (event) => {
				setCurrentQualityLevel(event.detail.level);
			});
			player.subscribe(({ currentTime, duration }) => {
				setVideoPlayerTime(currentTime);
				setVideoDuration(duration);
			});
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
		const params = new URLSearchParams({ type: downloadType(), allow_holes: "false" });
		for (const range of videoData()) {
			const rangeStartTime = range.startTime();
			const rangeEndTime = range.endTime();
			const rangeStart = rangeStartTime ? wubloaderTimeFromDateTime(rangeStartTime) : "";
			const rangeEnd = rangeEndTime ? wubloaderTimeFromDateTime(rangeEndTime) : "";
			const rangeString = `${rangeStart},${rangeEnd}`;
			params.append("range", rangeString);
		}
		return `/cut/${streamInfo.streamName}/${props.data!.video_quality}.ts?${params.toString()}`;
	};

	return (
		<>
			<ul class={styles.errorList}>
				<Index each={pageErrors()}>
					{(error: Accessor<string>, index: number) => (
						<li>
							{error()}
							<a class={styles.errorRemoveLink}>[X]</a>
						</li>
					)}
				</Index>
			</ul>
			<KeyboardShortcuts includeEditorShortcuts={true} />
			<StreamTimeSettings
				busStartTime={busStartTime}
				streamVideoInfo={streamVideoInfo}
				setStreamVideoInfo={setStreamVideoInfo}
				showTimeRangeLink={false}
				errorList={pageErrors}
				setErrorList={setPageErrors}
			/>
			<VideoPlayer
				src={videoURL}
				setPlayerTime={setPlayerTime}
				mediaPlayer={mediaPlayer as Accessor<MediaPlayerElement>}
				setMediaPlayer={setMediaPlayer as Setter<MediaPlayerElement>}
			/>
			<ClipBar
				rangeData={videoData}
				videoFragments={videoFragmentTimes}
				videoDuration={videoDuration}
			/>
			<Waveform
				videoInfo={streamVideoInfo}
				videoQuality={props.data.video_quality}
				videoTime={videoPlayerTime}
				videoDuration={videoDuration}
			/>
			<NotesToEditor notes={props.data.notes} />
			<CategoryNotes notes={props.data.category_notes} />
			<ChapterToggle chaptersEnabled={chaptersEnabled} setChaptersEnabled={setChaptersEnabled} />
			<RangeSelection
				rangeData={videoData}
				setRangeData={setVideoData}
				allTransitions={allTransitions.latest ?? []}
				activeKeyboardIndex={activeKeyboardIndex}
				streamInfo={streamVideoInfo}
				allowHoles={allowHoles}
				videoPlayerTime={videoPlayerTime}
				videoFragments={videoFragmentTimes}
				videoPlayer={mediaPlayer as Accessor<MediaPlayerElement>}
			/>
		</>
	);
};

interface ClipBarProperties {
	rangeData: Accessor<RangeData[]>;
	videoFragments: Accessor<FragmentTimes[]>;
	videoDuration: Accessor<number>;
}

const ClipBar: Component<ClipBarProperties> = (props) => {
	return (
		<div class={styles.clipBar}>
			<Show when={props.videoFragments().length > 0 && props.videoDuration() > 0} keyed>
				<For each={props.rangeData()}>
					{(range: RangeData) => {
						const styleString = () => {
							const rangeStartTime = range.startTime();
							const rangeEndTime = range.endTime();
							const fragments = props.videoFragments();
							const duration = props.videoDuration();

							if (rangeStartTime === null || rangeEndTime === null) {
								return "width: 0px";
							}
							const rangeStart = videoPlayerTimeFromDateTime(rangeStartTime, fragments);
							const rangeEnd = videoPlayerTimeFromDateTime(rangeEndTime, fragments);
							if (rangeStart === null || rangeEnd === null) {
								return "width: 0px";
							}
							const startPercentage = (rangeStart / duration) * 100;
							const endPercentage = (rangeEnd / duration) * 100;
							const widthPercentage = endPercentage - startPercentage;
							return `left: ${startPercentage}%; width: ${widthPercentage}%;`;
						};
						return <div style={styleString()}></div>;
					}}
				</For>
			</Show>
		</div>
	);
};

interface WaveformProperties {
	videoInfo: Accessor<StreamVideoInfo>;
	videoQuality: string;
	videoTime: Accessor<number>;
	videoDuration: Accessor<number>;
}

const Waveform: Component<WaveformProperties> = (props) => {
	const generateWaveformURL = () => {
		const videoInfo = props.videoInfo();
		const videoQuality = props.videoQuality;
		const videoDuration = props.videoDuration();

		const start = wubloaderTimeFromDateTime(videoInfo.streamStartTime);
		const end = videoInfo.streamEndTime ? wubloaderTimeFromDateTime(videoInfo.streamEndTime) : null;

		const query = new URLSearchParams({
			size: "1920x125",
			d: videoDuration.toString(),
			color: "#e5e5e5",
			start: start,
		});
		if (end !== null) {
			query.append("end", end);
		}

		return `/waveform/${videoInfo.streamName}/${videoQuality}.png?${query.toString()}`;
	};

	const [waveformURL, setWaveformURL] = createSignal(generateWaveformURL());

	const setWaveformURLTrigger = leadingAndTrailing(throttle, setWaveformURL, 15000);

	createEffect(() => {
		const waveformURL = generateWaveformURL();
		setWaveformURLTrigger(waveformURL);
	});

	const markerStyle = () => {
		const videoPercentage = (props.videoTime() * 100) / props.videoDuration();
		return `left: ${videoPercentage}%`;
	};

	return (
		<div class={styles.waveformContainer}>
			<img class={styles.waveform} alt="Waveform for this video" src={waveformURL()} />
			<div class={styles.waveformMarker} style={markerStyle()}></div>
		</div>
	);
};

interface NotesToEditorProps {
	notes: string;
}

const NotesToEditor: Component<NotesToEditorProps> = (props) => {
	return (
		<Show when={props.notes}>
			<div class={styles.notesToEditor}>
				<div>Notes to Editor:</div>
				<div>{props.notes}</div>
			</div>
		</Show>
	);
};

interface CategoryNotesProps {
	notes?: string;
}

const CategoryNotes: Component<CategoryNotesProps> = (props) => {
	return (
		<Show when={props.notes}>
			<div class={styles.categoryNotes}>{props.notes}</div>
		</Show>
	);
};

interface ChapterToggleProps {
	chaptersEnabled: Accessor<boolean>;
	setChaptersEnabled: Setter<boolean>;
}

const ChapterToggle: Component<ChapterToggleProps> = (props) => {
	const updateEnabled = (event: Event) => {
		const checkbox = event.currentTarget;
		if (checkbox) {
			const checkboxElement = checkbox as HTMLInputElement;
			props.setChaptersEnabled(checkboxElement.checked);
		}
	};
	return (
		<div class={styles.chaptersEnabledSelection}>
			<label>
				<input type="checkbox" checked={props.chaptersEnabled()} onChange={updateEnabled} />
				Add chapter markers to the video description
			</label>
		</div>
	);
};

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

const RangeSelection: Component<RangeSelectionProps> = (props) => {
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
									<span class={styles.transitionLabel}>
										Transition:
									</span>
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
