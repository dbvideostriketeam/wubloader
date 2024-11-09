import { l } from "vite/dist/node/types.d-aGj9QkWt";
import { DateTime } from "../external/luxon.min";

export function dateTimeFromWubloaderTime(wubloaderTime: string): DateTime | null {
	const dt = DateTime.fromISO(wubloaderTime);
	if (dt.isValid) {
		return dt;
	}
	return null;
}

export function wubloaderTimeFromDateTime(dateTime: DateTime): string {
	// Not using ISO here because Luxon doesn't give us a quick way to print an ISO8601 string with no offset.
	return dateTime.toFormat("yyyy-LL-dd'T'HH:mm:ss.SSS");
}

class DateTimeMathObject {
	hours: number;
	minutes: number;
	seconds: number;
}

function dateTimeMathObjectFromBusTime(busTime: string): DateTimeMathObject | null {
	// We need to handle inputs like "-0:10:15" in a way that consistently makes the time negative.
	// Since we can't assign the negative sign to any particular part, we'll check for the whole thing here.
	let direction = 1;
	if (busTime.startsWith("-")) {
		busTime = busTime.slice(1);
		direction = -1;
	}

	const parts = busTime.split(":", 3);
	const hours = parseInt(parts[0], 10) * direction;
	const minutes = parts.length > 1 ? parseInt(parts[1], 10) * direction : 0;
	const seconds = parts.length > 2 ? parseInt(parts[2], 10) * direction : 0;
	return { hours: hours, minutes: minutes, seconds: seconds };
}

export function dateTimeFromBusTime(busStartTime: DateTime, busTime: string): DateTime | null {
	const busMathObject = dateTimeMathObjectFromBusTime(busTime);
	if (busMathObject === null) {
		return null;
	}
	return busStartTime.plus(busMathObject);
}

export function busTimeFromDateTime(busStartTime: DateTime, time: DateTime): string {
	const diff = time.diff(busStartTime);
	if (diff.milliseconds < 0) {
		const negativeInterval = diff.negate();
		return `-${negativeInterval.toFormat("hh:mm:ss.SSS")}`;
	}
	return diff.toFormat("hh:mm:ss.SSS");
}

export function dateTimeFromTimeAgo(timeAgo: string): DateTime | null {
	const parts = timeAgo.split(":");
	const properties = ["hours", "minutes", "seconds"];
	const mathObj = {};

	while (parts.length > 0) {
		const nextPart = parts.pop();
		if (properties.length === 0) {
			return null;
		}
		const nextProp = properties.pop();
		const partNumber = parseInt(nextPart, 10);
		if (isNaN(partNumber)) {
			return null;
		}
		mathObj[nextProp] = partNumber;
	}

	const now = DateTime.utc();
	return now.plus(mathObj);
}

export function timeAgoFromDateTime(dateTime: DateTime): string {
	const currentTime = DateTime.utc();
	const interval = currentTime.diff(dateTime, "seconds");
	let timeAgoSeconds = interval.seconds;

	let negative = "";
	if (timeAgoSeconds < 0) {
		negative = "-";
		timeAgoSeconds = -timeAgoSeconds;
	}

	const seconds = (((timeAgoSeconds % 60) * 1000) | 0) / 1000
	const secondsString = seconds < 10 ? `0${seconds}` : seconds.toString();
	const minutes = (timeAgoSeconds / 60) % 60 | 0;
	const minutesString = minutes < 10 ? `0${minutes}` : minutes.toString();
	const hours = Math.floor(timeAgoSeconds / 3600);

	return `${negative}${hours}:${minutesString}:${secondsString}`;
}
