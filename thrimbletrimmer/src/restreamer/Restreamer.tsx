import { Accessor, Component, createResource, createSignal, For, Show, Suspense } from "solid-js";
import { DateTime } from "luxon";
import styles from "./Restreamer.module.scss";
import { dateTimeFromWubloaderTime } from "../common/convertTime";
import { KeyboardShortcuts, StreamTimeSettings, StreamVideoInfo } from "../common/video";

export interface DefaultsData {
	video_channel: string;
	bustime_start: string;
	title_prefix: string;
	title_max_length: string;
	upload_locations: string[];
}

export const Restreamer: Component = () => {
	const [pageErrors, setPageErrors] = createSignal<string[]>([]);
	const [defaultsData] = createResource<DefaultsData | null>(
		async (source, { value, refetching }) => {
			const response = await fetch("/thrimshim/defaults");
			if (!response.ok) {
				return null;
			}
			return await response.json();
		},
	);

	const busStartTime = () => {
		const defaults = defaultsData();
		if (defaults && defaults.hasOwnProperty("bustime_start")) {
			return dateTimeFromWubloaderTime(defaults.bustime_start);
		}
		return null;
	};

	const now = DateTime.utc();

	return (
		<>
			<ul class={styles.errorList}>
				<For each={pageErrors()}>
					{(error: string, index: Accessor<number>) => (
						<li>
							{error}
							<a class={styles.errorRemoveLink}>[X]</a>
						</li>
					)}
				</For>
			</ul>
			<div class={styles.keyboardShortcutHelp}>
				<KeyboardShortcuts includeEditorShortcuts={false} />
			</div>
			<Suspense>
				<Show when={defaultsData()}>
					<RestreamerWithDefaults defaults={defaultsData()} />
				</Show>
			</Suspense>
		</>
	);
};

interface RestreamerDefaultProps {
	defaults: DefaultsData;
}

const RestreamerWithDefaults: Component<RestreamerDefaultProps> = (props) => {
	const [busStartTime, setBusStartTime] = createSignal<DateTime>(
		dateTimeFromWubloaderTime(props.defaults.bustime_start),
	);
	const [streamVideoInfo, setStreamVideoInfo] = createSignal<StreamVideoInfo>({
		streamName: props.defaults.video_channel,
		streamStartTime: DateTime.utc().minus({ minutes: 10 }),
		streamEndTime: null,
	});

	return (
		<>
			<StreamTimeSettings
				busStartTime={busStartTime}
				streamVideoInfo={streamVideoInfo}
				setStreamVideoInfo={setStreamVideoInfo}
				showTimeRangeLink={false}
			/>
		</>
	);
};
