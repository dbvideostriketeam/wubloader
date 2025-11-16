import { DateTime } from "luxon";

export class StreamVideoInfo {
	streamName: string;
	streamStartTime: DateTime;
	streamEndTime: DateTime | null;

	public clone(): StreamVideoInfo {
		const copy = new StreamVideoInfo();
		copy.streamName = this.streamName;
		copy.streamStartTime = this.streamStartTime;
		copy.streamEndTime = this.streamEndTime;
		return copy;
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

		const info = new StreamVideoInfo();
		info.streamName = stream;
		info.streamStartTime = startTime;
		info.streamEndTime = endTime;
		return info;
	}
}
