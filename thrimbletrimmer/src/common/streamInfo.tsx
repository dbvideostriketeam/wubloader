import { DateTime } from "luxon";

export class StreamVideoInfo {
	streamName: string;
	streamStartTime: DateTime;
	streamEndTime: DateTime | null;

	public constructor(name: string, startTime: DateTime, endTime: DateTime | null) {
		this.streamName = name;
		this.streamStartTime = startTime;
		this.streamEndTime = endTime;
	}

	public clone(): StreamVideoInfo {
		return new StreamVideoInfo(this.streamName, this.streamStartTime, this.streamEndTime);
	}

	public static defaultFromURL(): StreamVideoInfo | null {
		const url = new URL(window.location.href);
		const urlParams = url.searchParams;
		const stream = urlParams.get("stream");
		const start = urlParams.get("start");
		const end = urlParams.get("end");
		if (stream === null) {
			return null;
		}
		if (start === null) {
			return null;
		}
		const startTime = DateTime.fromISO(start, { zone: "utc" });
		if (!startTime.isValid) {
			return null;
		}
		let endTime: DateTime | null = null;
		if (end !== null) {
			endTime = DateTime.fromISO(end, { zone: "utc" });
			if (!endTime.isValid) {
				return null;
			}
		}

		return new StreamVideoInfo(stream, startTime, endTime);
	}
}
