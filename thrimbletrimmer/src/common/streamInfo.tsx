import { DateTime } from "luxon";

export class StreamVideoInfo {
	streamName: string;
	streamStartTime: DateTime;
	streamEndTime: DateTime | null;
}
