import { Accessor, Component, createSignal, For, Match, Setter, Show, Switch } from "solid-js";
import {
	CHAPTER_MARKER_DELIMITER,
	CHAPTER_MARKER_DELIMITER_PARTIAL,
	EditorState,
	FragmentTimes,
	RangeData,
	ThumbnailData,
	ThumbnailType,
	VideoData,
	displayTimeForVideoPlayerTime,
	videoPlayerTimeFromDateTime,
} from "./common";
import { bindingInputChecked, bindingInputOnChange } from "../common/binding";
import { wubloaderTimeFromDateTime } from "../common/convertTime";
import { GoogleSignIn, googleUser } from "../common/googleAuth";
import { DateTime } from "luxon";

import styles from "./Submission.module.scss";

interface SubmissionProps {
	videoData: Accessor<RangeData[]>;
	videoTitle: Accessor<string>;
	videoDescription: Accessor<string>;
	videoTags: Accessor<string[]>;
	chaptersEnabled: Accessor<boolean>;
	uploadLocations: string[];
	editorState: Accessor<EditorState>;
	setEditorState: Setter<EditorState>;
	thumbnailData: ThumbnailData;
	originalVideoData: VideoData;
	videoFragmentTimes: Accessor<FragmentTimes[]>;
}

export const Submission: Component<SubmissionProps> = (props) => {
	const [showAdvancedSubmissionOptions, setShowAdvancedSubmissionOptions] = createSignal(false);
	const [allowHoles, setAllowHoles] = createSignal(false);
	const [makeUnlisted, setMakeUnlisted] = createSignal(false);
	const [uploadLocation, setUploadLocation] = createSignal(
		props.uploadLocations.length > 0 ? props.uploadLocations[0] : "",
	);
	const [uploaderAllowlist, setUploaderAllowlist] = createSignal("");
	const [submissionError, setSubmissionError] = createSignal("");
	const [needsOverrideMessage, setNeedsOverrideMessage] = createSignal("");

	const toggleAdvancedSubmissionOptions = (event) => {
		setShowAdvancedSubmissionOptions(!showAdvancedSubmissionOptions());
	};

	const updateUploadLocation = (event: Event) => {
		const value = (event.currentTarget as HTMLSelectElement).value;
		setUploadLocation(value);
	};

	const submitVideo = async (event) => {
		const oldState = props.editorState();
		props.setEditorState(EditorState.Submitting);
		setSubmissionError("");

		const videoTitle = props.videoTitle();
		const videoDescription = props.videoDescription();
		if (videoTitle === "" || videoDescription === "") {
			setSubmissionError("The video title and/or description must be filled in");
			props.setEditorState(oldState);
			return;
		}
		if (videoDescription.indexOf(CHAPTER_MARKER_DELIMITER_PARTIAL) !== -1) {
			setSubmissionError("Description contains manually entered chapter marker delimiter");
			props.setEditorState(oldState);
			return;
		}

		const videoRanges: [string, string][] = [];
		const transitions: ([string, number] | null)[] = [];
		const chapters: string[] = [];
		let currentRangeStartSecs = 0;
		let checkedFirstChapter = false;
		let lastChapterTime: number | null = null;
		for (const rangeData of props.videoData()) {
			const rangeStartDate = rangeData.startTime();
			const rangeEndDate = rangeData.endTime();
			if (rangeStartDate === null || rangeEndDate === null) {
				setSubmissionError("There are missing times for ranges");
				props.setEditorState(oldState);
				return;
			}
			if (rangeStartDate > rangeEndDate) {
				setSubmissionError("The end time of a range is before its start time");
				props.setEditorState(oldState);
				return;
			}
			const rangeStart = wubloaderTimeFromDateTime(rangeStartDate);
			const rangeEnd = wubloaderTimeFromDateTime(rangeEndDate);
			videoRanges.push([rangeStart, rangeEnd]);

			const rangePlayerStart = videoPlayerTimeFromDateTime(
				rangeStartDate,
				props.videoFragmentTimes(),
			);
			const rangePlayerEnd = videoPlayerTimeFromDateTime(rangeEndDate, props.videoFragmentTimes());
			if (rangePlayerStart === null || rangePlayerEnd === null) {
				setSubmissionError("The start and/or end time of a range don't resolve to video times.");
				props.setEditorState(oldState);
				return;
			}

			if (props.chaptersEnabled()) {
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
						props.setEditorState(oldState);
						return;
					}

					if (!chapterData.description) {
						setSubmissionError("A chapter is missing a description");
						props.setEditorState(oldState);
						return;
					}

					const outputVideoTimeSeconds = chapterTime - rangePlayerStart + currentRangeStartSecs;
					if (!checkedFirstChapter) {
						checkedFirstChapter = true;
						if (outputVideoTimeSeconds !== 0) {
							setSubmissionError("The first chapter must start at the beginning of the video");
							props.setEditorState(oldState);
							return;
						}
					}
					if (lastChapterTime !== null && outputVideoTimeSeconds - lastChapterTime < 10) {
						setSubmissionError("Chapters must be at least 10 seconds apart");
						props.setEditorState(oldState);
						return;
					}
					lastChapterTime = outputVideoTimeSeconds;

					const outputVideoTime = `${Math.floor(outputVideoTimeSeconds / 60)}:${Math.floor(outputVideoTimeSeconds % 60)}`;
					chapters.push(`${outputVideoTime} - ${chapterData.description}`);
				}
			}

			const transitionSeconds = rangeData.transitionSeconds();
			transitions.push([rangeData.transitionType(), transitionSeconds]);

			currentRangeStartSecs += rangePlayerEnd - rangePlayerStart - transitionSeconds;

			if (currentRangeStartSecs < 0) {
				setSubmissionError(
					"Time ranges and transition data resulted in a negative video time at some point in the time calculations",
				);
				props.setEditorState(oldState);
				return;
			}
		}
		transitions.shift();

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
				props.setEditorState(oldState);
				return;
			}
		}

		if (thumbnailType === ThumbnailType.Template) {
			thumbnailTemplate = props.thumbnailData.template();
			if (thumbnailTemplate === null) {
				setSubmissionError("Thumbnail template is missing");
				props.setEditorState(oldState);
				return;
			}

			thumbnailCrop = props.thumbnailData.crop();
			thumbnailLocation = props.thumbnailData.location();
			if (thumbnailCrop === null || thumbnailLocation === null) {
				setSubmissionError("The thumbnail crop/location options are invalid");
				props.setEditorState(oldState);
				return;
			}
		}

		if (thumbnailType === ThumbnailType.CustomThumbnail) {
			thumbnailImage = props.thumbnailData.image();
			if (thumbnailImage === null) {
				setSubmissionError("The thumbnail image was invalid or not uploaded");
				props.setEditorState(oldState);
				return;
			}
		}

		if (thumbnailType === ThumbnailType.CustomTemplate) {
			const customTime = props.thumbnailData.time();
			if (customTime === null) {
				setSubmissionError("The thumbnail time is invalid");
				props.setEditorState(oldState);
				return;
			}

			const customCrop = props.thumbnailData.crop();
			const customLocation = props.thumbnailData.location();
			if (customCrop === null || customLocation === null) {
				setSubmissionError("The thumbnail crop/location options are invalid");
				props.setEditorState(oldState);
				return;
			}

			const query = new URLSearchParams({
				timestamp: wubloaderTimeFromDateTime(customTime),
				crop: customCrop.join(","),
				location: customLocation.join(","),
			});

			const customTemplate = props.thumbnailData.image();
			if (customTemplate === null) {
				setSubmissionError("The template image was not uploaded or invalid");
				props.setEditorState(oldState);
				return;
			}

			// Client-side javascript makes it shockingly hard to correctly decode base64.
			// See https://developer.mozilla.org/en-US/docs/Glossary/Base64#the_unicode_problem
			// The "cleanest" solution is to "fetch" the data URL containing base64 data.
			const templateResponse = await fetch(
				`data:application/octet-stream;base64,${customTemplate}`,
			);
			const templateBody = new Uint8Array(await templateResponse.arrayBuffer());
			const thumbnailResponse = await fetch(
				`/thumbnail/${props.originalVideoData.video_channel}/source.png?${query}`,
				{ method: "POST", body: templateBody },
			);
			if (!thumbnailResponse.ok) {
				setSubmissionError(
					`Rendering thumbnail failed with ${thumbnailResponse.status} ${thumbnailResponse.statusText}`,
				);
				props.setEditorState(oldState);
				return;
			}

			const thumbnailBlob = await thumbnailResponse.blob();
			const thumbnailData: string = await new Promise((resolve) => {
				const reader = new FileReader();
				reader.onload = () => resolve(reader.result as string);
				reader.readAsDataURL(thumbnailBlob);
			});
			if (thumbnailData.substring(0, 22) !== "data:image/png;base64,") {
				setSubmissionError("An error occurred converting the generated thumbnail to base64");
				props.setEditorState(oldState);
				return;
			}

			thumbnailImage = thumbnailData.substring(22);
			thumbnailType = ThumbnailType.CustomThumbnail;
		}

		const editData = {
			video_ranges: videoRanges,
			video_transitions: transitions,
			video_title: videoTitle,
			video_description: videoDescription,
			video_tags: props.videoTags(),
			allow_holes: allowHoles(),
			upload_location: uploadLocation(),
			public: !makeUnlisted(),
			video_channel: props.originalVideoData.video_channel,
			video_quality: props.originalVideoData.video_quality,
			uploader_whitelist: uploaderAllowlist()
				.split(",")
				.filter((name) => name !== ""),
			state: props.originalVideoData.uploader === null ? "EDITED" : "MODIFIED",
			thumbnail_mode: thumbnailType.toString(),
			thumbnail_template: thumbnailTemplate,
			thumbnail_crop: thumbnailCrop,
			thumbnail_location: thumbnailLocation,
			thumbnail_time: thumbnailTime,
			thumbnail_image: thumbnailImage,
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
			token: undefined,
		};
		if (googleUser) {
			editData.token = googleUser.getAuthResponse().id_token;
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
		} else {
			props.setEditorState(oldState);
			if (submitResponse.status === 409) {
				setNeedsOverrideMessage(await submitResponse.text());
			} else if (submitResponse.status === 401) {
				setSubmissionError("Unauthorized. Did you remember to sign in?");
			} else {
				setSubmissionError(`${submitResponse.statusText}: ${await submitResponse.text()}`);
			}
		}
	};

	const saveVideoDraft = async (event) => {
		const oldState = props.editorState();
		props.setEditorState(EditorState.Submitting);
		setSubmissionError("");

		let videoDescription = props.videoDescription();
		if (videoDescription.indexOf(CHAPTER_MARKER_DELIMITER_PARTIAL) !== -1) {
			setSubmissionError("Description contains manually entered chapter marker delimiter");
			props.setEditorState(oldState);
			return;
		}

		const videoRanges: [string | null, string | null][] = [];
		const transitions: ([string, number] | null)[] = [];
		for (const [rangeDataIndex, rangeData] of props.videoData().entries()) {
			const rangeStartDate = rangeData.startTime();
			const rangeEndDate = rangeData.endTime();
			const rangeStart = rangeStartDate ? wubloaderTimeFromDateTime(rangeStartDate) : null;
			const rangeEnd = rangeEndDate ? wubloaderTimeFromDateTime(rangeEndDate) : null;
			videoRanges.push([rangeStart, rangeEnd]);

			if (props.chaptersEnabled()) {
				const chapterDescriptions: string[] = [];
				for (const chapterData of rangeData.chapters()) {
					const chapterTime = chapterData.time ? wubloaderTimeFromDateTime(chapterData.time) : null;
					chapterDescriptions.push(`${rangeDataIndex};${chapterTime} - ${chapterData.description}`);
				}
				videoDescription = `${videoDescription}${CHAPTER_MARKER_DELIMITER}${chapterDescriptions.join("\n")}`;
			}

			transitions.push([rangeData.transitionType(), rangeData.transitionSeconds()]);
		}
		transitions.shift();

		const editData = {
			video_ranges: videoRanges,
			video_transitions: transitions,
			video_title: props.videoTitle(),
			video_description: videoDescription,
			video_tags: props.videoTags(),
			allow_holes: allowHoles(),
			upload_location: uploadLocation(),
			public: !makeUnlisted(),
			video_channel: props.originalVideoData.video_channel,
			video_quality: props.originalVideoData.video_quality,
			uploader_whitelist: uploaderAllowlist()
				.split(",")
				.filter((name) => name !== ""),
			state: "UNEDITED",
			thumbnail_mode: props.thumbnailData.type().toString(),
			thumbnail_template: props.thumbnailData.template(),
			thumbnail_crop: props.thumbnailData.crop(),
			thumbnail_location: props.thumbnailData.location(),
			thumbnail_time: props.thumbnailData.time(),
			thumbnail_image: props.thumbnailData.image(),
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
			token: undefined,
		};
		if (googleUser) {
			editData.token = googleUser.getAuthResponse().id_token;
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
			props.setEditorState(EditorState.Clean);
			setNeedsOverrideMessage("");
		} else {
			props.setEditorState(oldState);
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
					<Match when={props.editorState() === EditorState.Clean}>
						<button onClick={submitVideo}>{submitButtonLabel()}</button>
						<Show when={showSaveDraftButton()}>
							<button disabled>{saveDraftButtonLabel()}</button>
						</Show>
					</Match>
					<Match when={props.editorState() === EditorState.Dirty}>
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
			<div class={styles.submissionError}>{submissionError()}</div>
			<Show when={showAdvancedSubmissionOptions()}>
				<div>
					<label>
						<input type="checkbox" use:bindingInputChecked={[allowHoles, setAllowHoles]} />
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
			<GoogleSignIn />
		</>
	);
};
