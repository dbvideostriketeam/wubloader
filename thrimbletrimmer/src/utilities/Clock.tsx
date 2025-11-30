import { Accessor, Component, createMemo, createSignal, onCleanup, onMount } from "solid-js";
import { useTitle } from "solidjs-use";
import { DateTime, Interval } from "luxon";
import { bindingInputChecked } from "../common/binding";

interface ClockProps {
	busStartTime: Accessor<DateTime | null>;
	initialPageTitle: string;
}

const Clock: Component<ClockProps> = (props) => {
	const [delay, setDelay] = createSignal(10);
	const [time, setTime] = createSignal(DateTime.utc());
	const [useTimeAsTitle, setUseTimeAsTitle] = createSignal(false);
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

	const titleToUse = createMemo(() => {
		const time = timeDisplay();
		if (useTimeAsTitle()) {
			return time;
		}
		return props.initialPageTitle;
	});
	useTitle(titleToUse);

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
			<div>
				<label>
					<input type="checkbox" use:bindingInputChecked={[useTimeAsTitle, setUseTimeAsTitle]} />
					&#32;Show time in page title
				</label>
			</div>
		</div>
	);
};

export default Clock;
