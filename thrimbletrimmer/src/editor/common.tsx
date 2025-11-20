import { Accessor, createSignal, Setter } from "solid-js";
import { DateTime } from "luxon";

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
}

export class ChapterData {
	time: DateTime | null;
	description: string;

	constructor() {
		this.time = null;
		this.description = "";
	}
}

export class FragmentTimes {
	rawStart: DateTime;
	rawEnd: DateTime;
	playerStart: number;
	duration: number;
}

export class TransitionDefinition {
	name: string;
	description: string;
}

export function defaultRangeData(): RangeData {
	const data = new RangeData();
	[data.startTime, data.setStartTime] = createSignal<DateTime | null>(null);
	[data.endTime, data.setEndTime] = createSignal<DateTime | null>(null);
	[data.transitionType, data.setTransitionType] = createSignal("");
	[data.transitionSeconds, data.setTransitionSeconds] = createSignal(0);
	[data.chapters, data.setChapters] = createSignal<ChapterData[]>([]);
	return data;
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

export function dateTimeFromVideoPlayerTime(
	time: number,
	fragments: FragmentTimes[],
): DateTime | null {
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

export function displayTimeForVideoPlayerTime(time: number): string {
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
