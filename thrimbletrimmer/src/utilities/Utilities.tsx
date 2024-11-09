import { Component, createSignal, onMount } from "solid-js";
import { DateTime } from "luxon";
import Clock from "./Clock";
import TimeConverter from "./TimeConverter";

const Utilities: Component = () => {
	const [busStartTime, setBusStartTime] = createSignal<DateTime | null>(null);

	onMount(async () => {
		const dataResponse = await fetch("/thrimshim/defaults");
		const data = await dataResponse.json();
		setBusStartTime(DateTime.fromISO(data.bustime_start));
	});

	return (
		<>
			<Clock busStartTime={busStartTime} />
			<TimeConverter busStartTime={busStartTime} />
		</>
	);
};

export default Utilities;
