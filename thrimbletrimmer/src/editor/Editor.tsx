import {
	Accessor,
	Component,
	createEffect,
	createResource,
	createSignal,
	Index,
	onMount,
	Setter,
	Show,
	Suspense,
} from "solid-js";
import { Fragment } from "hls.js";
import { DateTime } from "luxon";
import { makeEventListener } from "@solid-primitives/event-listener";
import { MediaPlayerElement } from "vidstack/elements";
import styles from "./Editor.module.scss";
import {
	CHAPTER_MARKER_DELIMITER,
	ChapterData,
	EditorState,
	FragmentTimes,
	RangeData,
	ThumbnailData,
	ThumbnailTemplateDefinition,
	ThumbnailType,
	TransitionDefinition,
	VideoData,
} from "./common";
import { CategoryNotes } from "./CategoryNotes";
import { ChapterToggle } from "./ChapterToggle";
import { ClipBar } from "./ClipBar";
import { DataCorrection } from "./DataCorrection";
import { Download } from "./Download";
import { NotesToEditor } from "./NotesToEditor";
import { RangeSelection } from "./RangeSelection";
import { Submission } from "./Submission";
import { ThumbnailSettings } from "./ThumbnailSettings";
import { VideoMetadata } from "./VideoMetadata";
import { Waveform } from "./Waveform";
import { ChatDisplay } from "../common/chat";
import { dateTimeFromWubloaderTime, wubloaderTimeFromDateTime } from "../common/convertTime";
import { StreamVideoInfo } from "../common/streamInfo";
import { KeyboardShortcuts, StreamTimeSettings, VideoPlayer } from "../common/video";

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

	let initialTitle = props.data.video_title;
	if (props.data.category === "RDP" && !initialTitle) {
		initialTitle = props.data.description;
	}

	const [videoData, setVideoData] = createSignal(initialVideoData);
	const [playerTime, setPlayerTime] = createSignal(0);
	const [mediaPlayer, setMediaPlayer] = createSignal<MediaPlayerElement>();
	const [videoPlayerTime, setVideoPlayerTime] = createSignal(0);
	const [videoDuration, setVideoDuration] = createSignal(0);
	const [allFragments, setAllFragments] = createSignal<Fragment[]>([]);
	const [allFragmentTimes, setAllFragmentTimes] = createSignal<FragmentTimes[][]>([[]]);
	const [currentQualityLevel, setCurrentQualityLevel] = createSignal(0);
	const [videoTitle, setVideoTitle] = createSignal(initialTitle ?? "");
	const [videoDescription, setVideoDescription] = createSignal(description);
	const [videoTags, setVideoTags] = createSignal(props.data.video_tags ?? props.data.tags ?? []);
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

	const initialThumbnailData = new ThumbnailData();
	[initialThumbnailData.type, initialThumbnailData.setType] = createSignal(
		props.data.thumbnail_mode,
	);
	[initialThumbnailData.time, initialThumbnailData.setTime] = createSignal(
		props.data.thumbnail_time ? dateTimeFromWubloaderTime(props.data.thumbnail_time) : null,
	);
	[initialThumbnailData.template, initialThumbnailData.setTemplate] = createSignal(
		props.data.thumbnail_template,
	);
	[initialThumbnailData.image, initialThumbnailData.setImage] = createSignal(
		props.data.thumbnail_image,
	);
	[initialThumbnailData.crop, initialThumbnailData.setCrop] = createSignal(
		props.data.thumbnail_crop,
	);
	[initialThumbnailData.location, initialThumbnailData.setLocation] = createSignal(
		props.data.thumbnail_location,
	);
	const [thumbnail, setThumbnail] = createSignal(initialThumbnailData);

	const [allThumbnailTemplates] = createResource<ThumbnailTemplateDefinition[]>(
		async (source, { value, refetching }) => {
			const thumbnailResponse = await fetch("/thrimshim/templates");
			if (!thumbnailResponse.ok) {
				return [];
			}
			return await thumbnailResponse.json();
		},
	);

	createEffect(() => {
		const thumbnailData = thumbnail();
		const templateName = thumbnailData.template();
		const allTemplates = allThumbnailTemplates();
		if (
			templateName === null &&
			allThumbnailTemplates.latest !== undefined &&
			allThumbnailTemplates.latest.length > 0
		) {
			thumbnailData.setTemplate(allThumbnailTemplates.latest[0].name);
		}
	});

	createEffect(() => {
		const thumbnailData = thumbnail();
		const templateName = thumbnailData.template();
		const crop = thumbnailData.crop();
		const location = thumbnailData.location();

		if (templateName === null) {
			return;
		}
		if (crop !== null && location !== null) {
			return;
		}

		let templateData: ThumbnailTemplateDefinition | null = null;
		if (allThumbnailTemplates.latest) {
			for (const template of allThumbnailTemplates.latest) {
				if (template.name === templateName) {
					templateData = template;
					break;
				}
			}
		}
		if (!templateData) {
			return;
		}

		if (crop === null) {
			thumbnailData.setCrop(templateData.crop);
		}
		if (location === null) {
			thumbnailData.setLocation(templateData.location);
		}
	});

	const [activeKeyboardIndex, setActiveKeyboardIndex] = createSignal(0);

	onMount(() => {
		const player = mediaPlayer();
		if (player) {
			player.addEventListener("hls-level-loaded", (event) => {
				setAllFragments(event.detail.details.fragments);

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

	const dataChanged = () => {
		const videoRangeData = videoData();
		if (videoData.length != (props.data?.video_ranges?.length ?? 0)) {
			return true;
		}
		for (let rangeIndex = 0; rangeIndex < videoData.length; rangeIndex++) {
			const origRangeStart = dateTimeFromWubloaderTime(props.data!.video_ranges![rangeIndex][0]);
			const rangeStart = videoRangeData[rangeIndex].startTime();
			if (rangeStart !== origRangeStart) {
				return true;
			}

			const origRangeEnd = dateTimeFromWubloaderTime(props.data!.video_ranges![rangeIndex][1]);
			const rangeEnd = videoRangeData[rangeIndex].endTime();
			if (rangeEnd !== origRangeEnd) {
				return true;
			}

			if (rangeIndex > 0) {
				const transitionIndex = rangeIndex - 1;
				const origTransitionData = props.data!.video_transitions![transitionIndex];
				const transitionType = videoRangeData[rangeIndex].transitionType();
				const transitionSeconds = videoRangeData[rangeIndex].transitionSeconds();
				if ((origTransitionData === null && transitionType !== "") || (origTransitionData !== null && (origTransitionData[0] !== transitionType || origTransitionData[1] !== transitionSeconds))) {
					return true;
				}
			}

			// TODO: When chapter markers are in the database, compare those, too
		}

		if (videoTitle() !== (props.data?.video_title ?? props.data?.description ?? "")) {
			return true;
		}

		// TODO: When chapter markers are in the database, stop comparing the description this way (compare them directly instead)
		let origDescription = props.data?.video_description ?? "";
		if (origDescription.indexOf(CHAPTER_MARKER_DELIMITER) !== -1) {
			origDescription = origDescription.split(CHAPTER_MARKER_DELIMITER, 1)[0];
		}

		const tags = videoTags();
		const origTags = props.data?.video_tags ?? props.data?.tags ?? [];
		if (tags.length !== origTags.length) {
			return true;
		}
		for (let tagIndex = 0; tagIndex < tags.length; tagIndex++) {
			if (tags[tagIndex] !== origTags[tagIndex]) {
				return true;
			}
		}

		const origThumbnailType = props.data?.thumbnail_mode ?? initialThumbnailData.type();
		const thumbnailType = thumbnail().type();
		if (origThumbnailType !== thumbnailType) {
			return true;
		}
		if (thumbnailType === ThumbnailType.Template) {
			const origThumbnailTemplate = props.data?.thumbnail_template ?? initialThumbnailData.template();
			const thumbnailTemplate = thumbnail().template();
			if (origThumbnailTemplate !== thumbnailTemplate) {
				return true;
			}
		}
		if (thumbnailType === ThumbnailType.Frame || thumbnailType === ThumbnailType.Template || thumbnailType === ThumbnailType.CustomTemplate) {
			const origThumbnailTime = dateTimeFromWubloaderTime(props.data?.thumbnail_time ?? null) ?? initialThumbnailData.time();
			const thumbnailTime = thumbnail().time();
			if ((thumbnailTime === null) !== (origThumbnailTime === null)) {
				return true;
			}
			if (thumbnailTime !== null && origThumbnailTime !== null && !thumbnailTime.equals(origThumbnailTime)) {
				return true;
			}
		}
		if (thumbnailType === ThumbnailType.Template || thumbnailType === ThumbnailType.CustomTemplate) {
			const origThumbnailCrop = props.data?.thumbnail_crop ?? initialThumbnailData.crop();;
			const thumbnailCrop = thumbnail().crop();
			let cropMatches = origThumbnailCrop === null && thumbnailCrop === null;
			if (!cropMatches) {
				if (origThumbnailCrop === null) {
					return true;
				}
				if (thumbnailCrop === null) {
					return true;
				}
				cropMatches = origThumbnailCrop[0] === thumbnailCrop[0] && origThumbnailCrop[1] === thumbnailCrop[1] && origThumbnailCrop[2] === thumbnailCrop[2] && origThumbnailCrop[3] === thumbnailCrop[3];
			}
			if (!cropMatches) {
				return true;
			}
			const origThumbnailLocation = props.data?.thumbnail_location ?? initialThumbnailData.location();
			const thumbnailLocation = thumbnail().location();
			let locationMatches = origThumbnailLocation === null && thumbnailLocation === null;
			if (!locationMatches) {
				if (origThumbnailLocation === null) {
					return true;
				}
				if (thumbnailLocation === null) {
					return true;
				}
				locationMatches = origThumbnailLocation[0] === thumbnailLocation[0] && origThumbnailLocation[1] === thumbnailLocation[1] && origThumbnailLocation[2] === thumbnailLocation[2] && origThumbnailLocation[3] === thumbnailLocation[3];
			}
			if (!locationMatches) {
				return true;
			}
		}
		if (thumbnailType === ThumbnailType.CustomTemplate || thumbnailType === ThumbnailType.CustomThumbnail) {
			const origThumbnailImage = props.data?.thumbnail_image ?? initialThumbnailData.image();
			const thumbnailImage = thumbnail().image();
			if (origThumbnailImage !== thumbnailImage) {
				return true;
			}
		}

		return false;
	};

	const [editorState, setEditorState] = createSignal(EditorState.Entry);

	const allFieldsDisabled = () => editorState() === EditorState.Submitting;
	makeEventListener(window, "beforeunload", (event) => {
		if (editorState() === EditorState.Entry && dataChanged()) {
			event.preventDefault();
		}
	});

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
			<ChapterToggle
				chaptersEnabled={chaptersEnabled}
				setChaptersEnabled={setChaptersEnabled}
				allFieldsDisabled={allFieldsDisabled}
			/>
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
				enableChapterEntry={chaptersEnabled}
			/>
			<VideoMetadata
				titlePrefix={props.data.title_prefix}
				titleMaxLength={props.data.title_max_length}
				title={videoTitle}
				setTitle={setVideoTitle}
				description={videoDescription}
				setDescription={setVideoDescription}
				tags={videoTags}
				setTags={setVideoTags}
			/>
			<ThumbnailSettings
				allThumbnailTemplates={allThumbnailTemplates() ?? []}
				thumbnailData={thumbnail()}
				streamInfo={streamVideoInfo}
				videoFragments={videoFragmentTimes}
				videoPlayerTime={videoPlayerTime}
				videoPlayer={mediaPlayer as Accessor<MediaPlayerElement>}
			/>
			<Submission
				streamVideoInfo={streamVideoInfo}
				videoData={videoData}
				videoTitle={videoTitle}
				videoDescription={videoDescription}
				videoTags={videoTags}
				chaptersEnabled={chaptersEnabled}
				uploadLocations={props.data.upload_locations}
				editorState={editorState}
				setEditorState={setEditorState}
				allowHoles={allowHoles}
				setAllowHoles={setAllowHoles}
				thumbnailData={thumbnail()}
				originalVideoData={props.data}
				videoFragmentTimes={videoFragmentTimes}
			/>
			<Download
				streamVideoInfo={streamVideoInfo}
				rangeData={videoData}
				allowHoles={allowHoles}
				videoPlayerTime={videoPlayerTime}
				videoQuality={props.data.video_quality}
				videoFragments={videoFragmentTimes}
			/>
			<DataCorrection videoID={props.data.id} />
			<ChatDisplay streamInfo={streamVideoInfo()} fragments={allFragments} />
		</>
	);
};
