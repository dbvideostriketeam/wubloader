import { Component, createSignal, onCleanup, onMount } from "solid-js";
import { DateTime, Interval } from "../external/luxon.min";

const Clock: Component = () => {
	const [delay, setDelay] = createSignal<number>(10);
	const [time, setTime] = createSignal<DateTime>(DateTime.utc());
	const [busStartTime, setBusStartTime] = createSignal<DateTime | null>(null);

	const timer = setInterval(() => setTime(DateTime.utc()), 250);

	onMount(async () => {
		const dataResponse = await fetch("/thrimshim/defaults");
		const data = await dataResponse.json();
		setBusStartTime(DateTime.fromISO(data.bustime_start));
	});

	onCleanup(() => {
		clearInterval(timer);
	});

	const timeDisplay = () => {
		const currentTime = time().minus({ seconds: delay() });
		const busTime = busStartTime();
		if (!busTime) {
			return "";
		}

		const [timeElapsed, sign] =
			currentTime >= busTime
				? [Interval.fromDateTimes(busTime, currentTime).toDuration("seconds"), ""]
				: [Interval.fromDateTimes(currentTime, busTime).toDuration("seconds"), "-"];

		const timeElapsedString = timeElapsed.toFormat("h:mm:ss");
		return `${sign}${timeElapsedString}`;
	};

	return (
		<div>
			<div>{timeDisplay()}</div>
			<div>
				<input
					type="number"
					value={delay()}
					min={0}
					step={1}
					onInput={(event) => setDelay(+event.currentTarget.value)}
				/>
				&#32;seconds of delay
			</div>
		</div>
	);
};

export default Clock;
