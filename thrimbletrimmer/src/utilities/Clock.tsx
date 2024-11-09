import { Accessor, Component, createSignal, onCleanup, onMount } from "solid-js";
import { DateTime, Interval } from "luxon";

interface ClockProps {
	busStartTime: Accessor<DateTime | null>;
}

const Clock: Component<ClockProps> = (props) => {
	const [delay, setDelay] = createSignal<number>(10);
	const [time, setTime] = createSignal<DateTime>(DateTime.utc());
	const busStartTime = props.busStartTime;

	const timer = setInterval(() => setTime(DateTime.utc()), 250);

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
