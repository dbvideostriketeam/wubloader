import { DateTime } from "luxon";

export class FragmentTimes {
	rawStart: DateTime;
	rawEnd: DateTime;
	playerStart: number;
	duration: number;

	equals(other: FragmentTimes): boolean {
		if (this.rawStart.toMillis() !== other.rawStart.toMillis()) {
			return false;
		}
		if (this.rawEnd.toMillis() !== other.rawEnd.toMillis()) {
			return false;
		}
		if (this.playerStart !== other.playerStart) {
			return false;
		}
		if (this.duration !== other.duration) {
			return false;
		}
		return true;
	}
}

export function arrayEquals<T>(
	lhs: T[],
	rhs: T[],
	elementEquals: (lhs: T, rhs: T) => boolean,
): boolean {
	if (lhs.length !== rhs.length) {
		return false;
	}
	for (let index = 0; index < lhs.length; index++) {
		if (!elementEquals(lhs[index], rhs[index])) {
			return false;
		}
	}
	return true;
}
