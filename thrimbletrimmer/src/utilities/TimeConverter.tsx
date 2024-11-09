import { Accessor, Component, createSignal } from "solid-js";
import { DateTime } from "../external/luxon.min";
import {
	dateTimeFromWubloaderTime,
	dateTimeFromBusTime,
	dateTimeFromTimeAgo,
	wubloaderTimeFromDateTime,
	busTimeFromDateTime,
	timeAgoFromDateTime,
} from "../common/convertTime";

interface TimeConverterProps {
	busStartTime: Accessor<DateTime | null>;
}

enum TimeType {
	UTC,
	BusTime,
	TimeAgo,
}

const TimeConverter: Component<TimeConverterProps> = (props) => {
	const [enteredTime, setEnteredTime] = createSignal<string>("");
	const [startTimeType, setStartTimeType] = createSignal<TimeType>(TimeType.UTC);
	const [outputTimeType, setOutputTimeType] = createSignal<TimeType>(TimeType.UTC);

	const outputString = (): string => {
		const busStartTime = props.busStartTime();
		if (busStartTime === null) {
			return "";
		}
		const startType = startTimeType();
		let dateTime: DateTime | null = null;
		if (startType === TimeType.UTC) {
			dateTime = dateTimeFromWubloaderTime(enteredTime());
		} else if (startType === TimeType.BusTime) {
			dateTime = dateTimeFromBusTime(busStartTime, enteredTime());
		} else if (startType === TimeType.TimeAgo) {
			dateTime = dateTimeFromTimeAgo(enteredTime());
		}
		if (dateTime === null) {
			return "";
		}

		const outputType = outputTimeType();
		if (outputType === TimeType.UTC) {
			return wubloaderTimeFromDateTime(dateTime);
		}
		if (outputType === TimeType.BusTime) {
			return busTimeFromDateTime(busStartTime, dateTime);
		}
		if (outputType === TimeType.TimeAgo) {
			return timeAgoFromDateTime(dateTime);
		}
		return "";
	};

	return (
		<div>
			<h1>Convert Times</h1>
			<input
				type="text"
				placeholder="Time to convert"
				value={enteredTime()}
				onInput={(event) => {
					setEnteredTime(event.currentTarget.value);
				}}
			/>
			<div>
				From:
				<label>
					<input
						name="time-converter-from"
						type="radio"
						value={TimeType.UTC}
						checked={true}
						onClick={(event) => setStartTimeType(TimeType.UTC)}
					/>
					UTC
				</label>
				<label>
					<input
						name="time-converter-from"
						type="radio"
						value={TimeType.BusTime}
						onClick={(event) => setStartTimeType(TimeType.BusTime)}
					/>
					Bus Time
				</label>
				<label>
					<input
						name="time-converter-from"
						type="radio"
						value={TimeType.TimeAgo}
						onClick={(event) => setStartTimeType(TimeType.TimeAgo)}
					/>
					Time Ago
				</label>
			</div>
			<div>
				To:
				<label>
					<input
						name="time-converter-to"
						type="radio"
						checked={true}
						value={TimeType.UTC}
						onClick={(event) => setOutputTimeType(TimeType.UTC)}
					/>
					UTC
				</label>
				<label>
					<input
						name="time-converter-to"
						type="radio"
						value={TimeType.BusTime}
						onClick={(event) => setOutputTimeType(TimeType.BusTime)}
					/>
					Bus Time
				</label>
				<label>
					<input
						name="time-converter-to"
						type="radio"
						value={TimeType.TimeAgo}
						onClick={(event) => setOutputTimeType(TimeType.TimeAgo)}
					/>
					Time Ago
				</label>
			</div>
			<div>Converted Time: {outputString()}</div>
		</div>
	);
};

export default TimeConverter;
