import { Accessor, Component, createSignal, For, Match, Setter, Show, Switch } from "solid-js";
import {
	EditorState,
	RangeData,
	ThumbnailData,
	ThumbnailType,
	VideoData,
	videoPlayerTimeFromDateTime,
} from "./common";
import { FragmentTimes } from "../common/common";
import { bindingInputChecked, bindingInputOnChange } from "../common/binding";
import { wubloaderTimeFromDateTime } from "../common/convertTime";
import { StreamVideoInfo } from "../common/streamInfo";
import { DateTime } from "luxon";

import styles from "./Submission.module.scss";

interface SubmissionProps {
	streamVideoInfo: Accessor<StreamVideoInfo>;
	videoData: Accessor<RangeData[]>;
	videoTitle: Accessor<string>;
	videoDescription: Accessor<string>;
	videoTags: Accessor<string[]>;
	subtitles: Accessor<string>;
	uploadLocations: string[];
	editorState: Accessor<EditorState>;
	setEditorState: Setter<EditorState>;
	allowHoles: Accessor<boolean>;
	setAllowHoles: Setter<boolean>;
	thumbnailData: ThumbnailData;
	originalVideoData: VideoData;
	videoFragmentTimes: Accessor<FragmentTimes[]>;
	editingCompletedVideo: Accessor<boolean>;
	accountToken: Accessor<string | null>;
}

interface ThumbnailInfo {
	type: ThumbnailType;
	template: string | null;
	time: DateTime | null;
	image: string | null;
	crop: [number, number, number, number] | null;
	location: [number, number, number, number] | null;
}

export const Submission: Component<SubmissionProps> = (props) => {
	const [showAdvancedSubmissionOptions, setShowAdvancedSubmissionOptions] = createSignal(false);
	const [makeUnlisted, setMakeUnlisted] = createSignal(props.originalVideoData.public === false);
	const [uploadLocation, setUploadLocation] = createSignal(
		props.uploadLocations.length > 0 ? props.uploadLocations[0] : "",
	);
	const [uploaderAllowlist, setUploaderAllowlist] = createSignal("");
	const [submissionSuccessMessage, setSubmissionSuccessMessage] = createSignal("");
	const [submissionError, setSubmissionError] = createSignal("");
	const [needsOverrideMessage, setNeedsOverrideMessage] = createSignal("");

	const toggleAdvancedSubmissionOptions = (event: MouseEvent) => {
		setShowAdvancedSubmissionOptions(!showAdvancedSubmissionOptions());
	};

	const updateUploadLocation = (event: Event) => {
		const value = (event.currentTarget as HTMLSelectElement).value;
		setUploadLocation(value);
	};

	const getThumbnailInfo = async (): Promise<ThumbnailInfo | null> => {
		let thumbnailType = props.thumbnailData.type();
		let thumbnailTemplate: string | null = null;
		let thumbnailTime: DateTime | null = null;
		let thumbnailImage: string | null = null;
		let thumbnailCrop: [number, number, number, number] | null = null;
		let thumbnailLocation: [number, number, number, number] | null = null;

		if (thumbnailType === ThumbnailType.Frame || thumbnailType === ThumbnailType.Template) {
			thumbnailTime = props.thumbnailData.time();
			if (thumbnailTime === null) {
				setSubmissionError("The thumbnail time is invalid");
				props.setEditorState(EditorState.Entry);
				return null;
			}
		}

		if (thumbnailType === ThumbnailType.Template) {
			thumbnailTemplate = props.thumbnailData.template();
			if (thumbnailTemplate === null) {
				setSubmissionError("Thumbnail template is missing");
				props.setEditorState(EditorState.Entry);
				return null;
			}

			thumbnailCrop = props.thumbnailData.crop();
			thumbnailLocation = props.thumbnailData.location();
			if (thumbnailCrop === null || thumbnailLocation === null) {
				setSubmissionError("The thumbnail crop/location options are invalid");
				props.setEditorState(EditorState.Entry);
				return null;
			}
		}

		if (thumbnailType === ThumbnailType.CustomThumbnail) {
			thumbnailImage = props.thumbnailData.image();
			if (thumbnailImage === null) {
				setSubmissionError("The thumbnail image was invalid or not uploaded");
				props.setEditorState(EditorState.Entry);
				return null;
			}
		}

		if (thumbnailType === ThumbnailType.CustomTemplate) {
			const customTime = props.thumbnailData.time();
			if (customTime === null) {
				setSubmissionError("The thumbnail time is invalid");
				props.setEditorState(EditorState.Entry);
				return null;
			}

			const customCrop = props.thumbnailData.crop();
			const customLocation = props.thumbnailData.location();
			if (customCrop === null || customLocation === null) {
				setSubmissionError("The thumbnail crop/location options are invalid");
				props.setEditorState(EditorState.Entry);
				return null;
			}

			const query = new URLSearchParams({
				timestamp: wubloaderTimeFromDateTime(customTime),
				crop: customCrop.join(","),
				location: customLocation.join(","),
			});

			const customTemplate = props.thumbnailData.image();
			if (customTemplate === null) {
				setSubmissionError("The template image was not uploaded or invalid");
				props.setEditorState(EditorState.Entry);
				return null;
			}

			// Client-side javascript makes it shockingly hard to correctly decode base64.
			// See https://developer.mozilla.org/en-US/docs/Glossary/Base64#the_unicode_problem
			// The "cleanest" solution is to "fetch" the data URL containing base64 data.
			const templateResponse = await fetch(
				`data:application/octet-stream;base64,${customTemplate}`,
			);
			const templateBody = new Uint8Array(await templateResponse.arrayBuffer());
			const thumbnailResponse = await fetch(
				`/thumbnail/${props.streamVideoInfo().streamName}/source.png?${query}`,
				{ method: "POST", body: templateBody },
			);
			if (!thumbnailResponse.ok) {
				setSubmissionError(
					`Rendering thumbnail failed with ${thumbnailResponse.status} ${thumbnailResponse.statusText}`,
				);
				props.setEditorState(EditorState.Entry);
				return null;
			}

			const thumbnailBlob = await thumbnailResponse.blob();
			const thumbnailData: string = await new Promise((resolve) => {
				const reader = new FileReader();
				reader.onload = () => resolve(reader.result as string);
				reader.readAsDataURL(thumbnailBlob);
			});
			if (thumbnailData.substring(0, 22) !== "data:image/png;base64,") {
				setSubmissionError("An error occurred converting the generated thumbnail to base64");
				props.setEditorState(EditorState.Entry);
				return null;
			}

			thumbnailImage = thumbnailData.substring(22);
			thumbnailType = ThumbnailType.CustomThumbnail;
		}

		return {
			type: thumbnailType,
			template: thumbnailTemplate,
			time: thumbnailTime,
			image: thumbnailImage,
			crop: thumbnailCrop,
			location: thumbnailLocation,
		};
	};

	const submitVideo = async (event: MouseEvent) => {
		props.setEditorState(EditorState.Submitting);
		setSubmissionSuccessMessage("");
		setSubmissionError("");

		const editingCompletedVideoWithoutVideo =
			props.videoFragmentTimes().length === 0 && props.editingCompletedVideo();

		const videoTitle = props.videoTitle();
		let videoDescription = props.videoDescription();
		if (videoTitle === "" || videoDescription === "") {
			setSubmissionError("The video title and/or description must be filled in");
			props.setEditorState(EditorState.Entry);
			return;
		}

		const videoRanges: [string, string][] = [];
		const transitions: ([string, number] | null)[] = [];
		const chapterMarkers: [number, string | null, string][] = [];
		let currentRangeStartSecs = 0;
		let currentRangeEndSecs = 0;
		let checkedFirstChapter = false;
		let lastChapterTime: number | null = null;
		for (const [rangeDataIndex, rangeData] of props.videoData().entries()) {
			const rangeStartDate = rangeData.startTime();
			const rangeEndDate = rangeData.endTime();
			if (rangeStartDate === null || rangeEndDate === null) {
				setSubmissionError("There are missing times for ranges");
				props.setEditorState(EditorState.Entry);
				return;
			}
			if (rangeStartDate > rangeEndDate) {
				setSubmissionError("The end time of a range is before its start time");
				props.setEditorState(EditorState.Entry);
				return;
			}
			const rangeStart = wubloaderTimeFromDateTime(rangeStartDate);
			const rangeEnd = wubloaderTimeFromDateTime(rangeEndDate);
			videoRanges.push([rangeStart, rangeEnd]);

			const transitionType = rangeData.transitionType();
			const transitionSeconds = rangeData.transitionSeconds();
			if (transitionType === "") {
				transitions.push(null);
			} else {
				transitions.push([transitionType, transitionSeconds]);
			}

			if (!editingCompletedVideoWithoutVideo) {
				const rangePlayerStart = videoPlayerTimeFromDateTime(
					rangeStartDate,
					props.videoFragmentTimes(),
				);
				const rangePlayerEnd = videoPlayerTimeFromDateTime(
					rangeEndDate,
					props.videoFragmentTimes(),
				);
				if (rangePlayerStart === null || rangePlayerEnd === null) {
					setSubmissionError("The start and/or end time of a range don't resolve to video times.");
					props.setEditorState(EditorState.Entry);
					return;
				}

				// These are the timestamps in the edited video that this segment starts and ends at.
				currentRangeStartSecs = currentRangeEndSecs - transitionSeconds;
				currentRangeEndSecs = currentRangeStartSecs + rangePlayerEnd - rangePlayerStart;

				// This check prevents negative currentRangeEndSecs, but is also stronger than that condition.
				// This condition ensures that we don't try to transition with not enough video after the transition.
				if (transitionSeconds > rangePlayerEnd - rangePlayerStart) {
					setSubmissionError(
						"A transition cannot be longer than the range that the transition fades into",
					);
					props.setEditorState(EditorState.Entry);
					return;
				}

				// Handle cases when a long transition after some short segments can take us beyond the beginning of the video
				if (currentRangeStartSecs < 0) {
					setSubmissionError(
						"A transition cannot be longer than the total amount of edited video before that transition",
					);
					props.setEditorState(EditorState.Entry);
					return;
				}

				const sortedChapters = rangeData
					.chapters()
					.filter((data) => data.time !== null)
					.toSorted((a, b) => a.time!.toMillis() - b.time!.toMillis());
				for (const chapterData of sortedChapters) {
					const chapterTime = videoPlayerTimeFromDateTime(
						chapterData.time!,
						props.videoFragmentTimes(),
					);
					if (chapterTime === null) {
						setSubmissionError("A chapter time doesn't resolve to video times");
						props.setEditorState(EditorState.Entry);
						return;
					}

					if (!chapterData.description) {
						setSubmissionError("A chapter is missing a description");
						props.setEditorState(EditorState.Entry);
						return;
					}

					const chapterTimeMillis = chapterData.time!.toMillis();
					if (
						chapterTimeMillis < rangeStartDate.toMillis() ||
						chapterTimeMillis > rangeEndDate.toMillis()
					) {
						setSubmissionError("A chapter marker is outside of its time range");
						props.setEditorState(EditorState.Entry);
						return;
					}

					const outputVideoTimeSeconds = chapterTime - rangePlayerStart + currentRangeStartSecs;
					if (!checkedFirstChapter) {
						checkedFirstChapter = true;
						if (outputVideoTimeSeconds !== 0) {
							setSubmissionError("The first chapter must start at the beginning of the video");
							props.setEditorState(EditorState.Entry);
							return;
						}
					}
					if (lastChapterTime !== null && outputVideoTimeSeconds - lastChapterTime < 10) {
						setSubmissionError("Chapters must be at least 10 seconds apart");
						props.setEditorState(EditorState.Entry);
						return;
					}
					lastChapterTime = outputVideoTimeSeconds;

					chapterMarkers.push([
						rangeDataIndex,
						wubloaderTimeFromDateTime(chapterData.time!),
						chapterData.description,
					]);
				}
			}
		}
		transitions.shift();

		const thumbnailInfo = await getThumbnailInfo();
		if (thumbnailInfo === null) {
			// An error was already set by getThumbnailInfo.
			return;
		}

		const subtitleData = props.subtitles();

		let allowedUploaders: string[] | null = uploaderAllowlist()
			.split(",")
			.filter((name) => name !== "");
		if (allowedUploaders.length === 0) {
			allowedUploaders = null;
		}

		const editData = {
			video_ranges: videoRanges.length === 0 ? null : videoRanges,
			video_transitions: transitions,
			video_title: videoTitle,
			video_description: videoDescription,
			video_tags: props.videoTags(),
			subtitle_data: subtitleData ? subtitleData : null,
			chapter_markers: chapterMarkers.length === 0 ? null : chapterMarkers,
			allow_holes: props.allowHoles(),
			upload_location: uploadLocation(),
			public: !makeUnlisted(),
			video_channel: props.streamVideoInfo().streamName,
			video_quality: props.originalVideoData.video_quality,
			uploader_whitelist: allowedUploaders,
			state: props.originalVideoData.uploader === null ? "EDITED" : "MODIFIED",
			thumbnail_mode: thumbnailInfo.type.toString(),
			thumbnail_template: thumbnailInfo.template,
			thumbnail_crop: thumbnailInfo.crop,
			thumbnail_location: thumbnailInfo.location,
			thumbnail_time: thumbnailInfo.time,
			thumbnail_image: thumbnailInfo.image,
			override_changes: needsOverrideMessage() !== "",

			// We also provide some information to verify data hasn't changed.
			sheet_name: props.originalVideoData.sheet_name,
			event_start: props.originalVideoData.event_start,
			event_end: props.originalVideoData.event_end,
			category: props.originalVideoData.category,
			description: props.originalVideoData.description,
			notes: props.originalVideoData.notes,
			tags: props.originalVideoData.tags,

			// These are added optionally below
			token: undefined as string | undefined,
		};
		const userAccountToken = props.accountToken();
		if (userAccountToken) {
			editData.token = userAccountToken;
		} else {
			delete editData.token;
		}

		const submitResponse = await fetch(`/thrimshim/${props.originalVideoData.id}`, {
			method: "POST",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
			},
			body: JSON.stringify(editData),
		});

		if (submitResponse.ok) {
			props.setEditorState(EditorState.Submitted);
			setNeedsOverrideMessage("");
			setSubmissionSuccessMessage("Video submitted.");
		} else {
			props.setEditorState(EditorState.Entry);
			if (submitResponse.status === 409) {
				setNeedsOverrideMessage(await submitResponse.text());
			} else if (submitResponse.status === 401) {
				setSubmissionError("Unauthorized. Did you remember to sign in?");
			} else {
				setSubmissionError(`${submitResponse.statusText}: ${await submitResponse.text()}`);
			}
		}
	};

	const saveVideoDraft = async (event: MouseEvent) => {
		props.setEditorState(EditorState.Submitting);
		setSubmissionSuccessMessage("");
		setSubmissionError("");

		let videoDescription = props.videoDescription();

		const videoRanges: [string | null, string | null][] = [];
		const transitions: ([string, number] | null)[] = [];
		const chapterMarkers: [number, string | null, string][] = [];
		for (const [rangeDataIndex, rangeData] of props.videoData().entries()) {
			const rangeStartDate = rangeData.startTime();
			const rangeEndDate = rangeData.endTime();
			const rangeStart = rangeStartDate ? wubloaderTimeFromDateTime(rangeStartDate) : null;
			const rangeEnd = rangeEndDate ? wubloaderTimeFromDateTime(rangeEndDate) : null;
			videoRanges.push([rangeStart, rangeEnd]);

			for (const chapterData of rangeData.chapters()) {
				const chapterTime = chapterData.time ? wubloaderTimeFromDateTime(chapterData.time) : null;
				chapterMarkers.push([rangeDataIndex, chapterTime, chapterData.description]);
			}

			const transitionType = rangeData.transitionType();
			if (transitionType === "") {
				transitions.push(null);
			} else {
				transitions.push([transitionType, rangeData.transitionSeconds()]);
			}
		}
		transitions.shift();

		const thumbnailInfo = await getThumbnailInfo();
		if (thumbnailInfo === null) {
			// An error was already set by getThumbnailInfo.
			return;
		}

		const subtitleData = props.subtitles();

		const editData = {
			video_ranges: videoRanges.length === 0 ? null : videoRanges,
			video_transitions: transitions,
			video_title: props.videoTitle(),
			video_description: videoDescription,
			video_tags: props.videoTags(),
			subtitle_data: subtitleData ? subtitleData : null,
			chapter_markers: chapterMarkers.length === 0 ? null : chapterMarkers,
			allow_holes: props.allowHoles(),
			upload_location: uploadLocation(),
			public: !makeUnlisted(),
			video_channel: props.streamVideoInfo().streamName,
			video_quality: props.originalVideoData.video_quality,
			uploader_whitelist: uploaderAllowlist()
				.split(",")
				.filter((name) => name !== ""),
			state: "UNEDITED",
			thumbnail_mode: thumbnailInfo.type,
			thumbnail_template: thumbnailInfo.template,
			thumbnail_crop: thumbnailInfo.crop,
			thumbnail_location: thumbnailInfo.location,
			thumbnail_time: thumbnailInfo.time,
			thumbnail_image: thumbnailInfo.image,
			override_changes: needsOverrideMessage() !== "",

			// We also provide some information to verify data hasn't changed.
			sheet_name: props.originalVideoData.sheet_name,
			event_start: props.originalVideoData.event_start,
			event_end: props.originalVideoData.event_end,
			category: props.originalVideoData.category,
			description: props.originalVideoData.description,
			notes: props.originalVideoData.notes,
			tags: props.originalVideoData.tags,

			// These are added optionally below
			token: undefined as string | undefined,
		};
		const userAccountToken = props.accountToken();
		if (userAccountToken) {
			editData.token = userAccountToken;
		} else {
			delete editData.token;
		}

		const submitResponse = await fetch(`/thrimshim/${props.originalVideoData.id}`, {
			method: "POST",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
			},
			body: JSON.stringify(editData),
		});

		props.setEditorState(EditorState.Entry);
		if (submitResponse.ok) {
			setNeedsOverrideMessage("");
			setSubmissionSuccessMessage("Draft saved.");
		} else {
			if (submitResponse.status === 409) {
				setNeedsOverrideMessage(await submitResponse.text());
			} else if (submitResponse.status === 401) {
				setSubmissionError("Unauthorized. Did you remember to sign in?");
			} else {
				setSubmissionError(`${submitResponse.statusText}: ${await submitResponse.text()}`);
			}
		}
	};

	const submitButtonLabel = () => (needsOverrideMessage() === "" ? "Submit" : "Submit Anyway");
	const saveDraftButtonLabel = () =>
		needsOverrideMessage() === "" ? "Save Draft" : "Save Draft Anyway";
	const showSaveDraftButton = () =>
		props.originalVideoData.state !== "DONE" && props.originalVideoData.state !== "MODIFIED";

	return (
		<>
			<div>
				<div>{needsOverrideMessage()}</div>
				<Switch>
					<Match when={props.editorState() === EditorState.Entry}>
						<button onClick={submitVideo}>{submitButtonLabel()}</button>
						<Show when={showSaveDraftButton()}>
							<button onClick={saveVideoDraft}>{saveDraftButtonLabel()}</button>
						</Show>
					</Match>
					<Match when={props.editorState() === EditorState.Submitting}>
						<button disabled>{submitButtonLabel()}</button>
						<Show when={showSaveDraftButton()}>
							<button disabled>{saveDraftButtonLabel()}</button>
						</Show>
					</Match>
				</Switch>
				<span>|</span>
				<button onClick={toggleAdvancedSubmissionOptions}>
					<Show when={showAdvancedSubmissionOptions()} fallback="Show Advanced Submission Options">
						Hide Advanced Submission Options
					</Show>
				</button>
			</div>
			<div class={styles.submissionSuccess}>{submissionSuccessMessage()}</div>
			<div class={styles.submissionError}>{submissionError()}</div>
			<Show when={showAdvancedSubmissionOptions()}>
				<div>
					<label>
						<input
							type="checkbox"
							use:bindingInputChecked={[props.allowHoles, props.setAllowHoles]}
						/>
						<span class={styles.advancedSubmissionLabel}>Allow Holes</span>
					</label>
				</div>
				<div>
					<label>
						<input type="checkbox" use:bindingInputChecked={[makeUnlisted, setMakeUnlisted]} />
						<span class={styles.advancedSubmissionLabel}>Make Unlisted</span>
					</label>
				</div>
				<div>
					<label>
						<span class={styles.advancedSubmissionLabel}>Upload location:</span>
						<select value={uploadLocation()} onChange={updateUploadLocation}>
							<For each={props.uploadLocations}>
								{(location: string) => <option value={location}>{location}</option>}
							</For>
						</select>
					</label>
				</div>
				<div>
					<label>
						<span class={styles.advancedSubmissionLabel}>Uploader allowlist:</span>
						<input
							type="text"
							use:bindingInputOnChange={[uploaderAllowlist, setUploaderAllowlist]}
						/>
					</label>
				</div>
			</Show>
		</>
	);
};
