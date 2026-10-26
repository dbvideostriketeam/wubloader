import { Accessor, createEffect, createSignal, createUniqueId, Setter, untrack } from "solid-js";
import { DateTime } from "luxon";
import { FragmentTimes } from "../common/common";

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
	thumbnail_mode: ThumbnailType;
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
	chapter_markers?: [number, string | null, string][] | null;
	subtitle_data: string | null;
}

export class RangeData {
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

	public constructor(initialTransitionType = "", initialTransitionSeconds = 0) {
		[this.startTime, this.setStartTime] = createSignal<DateTime | null>(null);
		[this.endTime, this.setEndTime] = createSignal<DateTime | null>(null);
		[this.transitionType, this.setTransitionType] = createSignal(initialTransitionType);
		[this.transitionSeconds, this.setTransitionSeconds] = createSignal(initialTransitionSeconds);
		[this.chapters, this.setChapters] = createSignal<ChapterData[]>([]);

		createEffect(() => {
			if (this.transitionType() === "") {
				this.setTransitionSeconds(0);
			} else if (untrack(this.transitionSeconds) === 0) {
				this.setTransitionSeconds(1);
			}
		});
	}
}

export class ChapterData {
	readonly id = `chapter-${createUniqueId()}`;
	time: DateTime | null;
	description: string;

	constructor() {
		this.time = null;
		this.description = "";
	}
}

export interface TransitionDefinition {
	name: string;
	description: string;
}

export enum ThumbnailType {
	None = "NONE",
	Frame = "BARE",
	Template = "TEMPLATE",
	CustomTemplate = "ONEOFF",
	CustomThumbnail = "CUSTOM",
}

export interface ThumbnailData {
	type: Accessor<ThumbnailType>;
	setType: Setter<ThumbnailType>;
	time: Accessor<DateTime | null>;
	setTime: Setter<DateTime | null>;
	template: Accessor<string | null>;
	setTemplate: Setter<string | null>;
	image: Accessor<string | null>;
	setImage: Setter<string | null>;
	crop: Accessor<[number, number, number, number] | null>;
	setCrop: Setter<[number, number, number, number] | null>;
	location: Accessor<[number, number, number, number] | null>;
	setLocation: Setter<[number, number, number, number] | null>;
}

export interface ThumbnailTemplateDefinition {
	name: string;
	description: string;
	attribution: string;
	crop: [number, number, number, number];
	location: [number, number, number, number];
}

export enum VideoHiddenReason {
	NotHidden = 0,
	AlreadySubmitted,
	RangeLong,
}

export function videoPlayerTimeFromDateTime(
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

export function displayTimeForVideoPlayerTime(time: number): string {
	// Round to the nearest millisecond, and split to minutes, seconds, and ms
	const totalMilliseconds = Math.round(time * 1000);
	const minutes = Math.trunc(totalMilliseconds / 60000);
	const seconds = Math.trunc((totalMilliseconds % 60000) / 1000);
	const milliseconds = totalMilliseconds % 1000;

	return `${minutes}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`;
}

export function videoPlayerTimeForDisplayTime(time: string): number {
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

export enum EditorState {
	Entry,
	Submitting,
	Submitted,
}
