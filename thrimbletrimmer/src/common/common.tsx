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
