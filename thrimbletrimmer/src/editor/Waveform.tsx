import { Accessor, Component, createEffect, createSignal } from "solid-js";
import { leadingAndTrailing, throttle } from "@solid-primitives/scheduled";
import styles from "./Waveform.module.scss";
import { wubloaderTimeFromDateTime } from "../common/convertTime";
import { StreamVideoInfo } from "../common/streamInfo";

interface WaveformProperties {
	videoInfo: Accessor<StreamVideoInfo>;
	videoQuality: string;
	videoTime: Accessor<number>;
	videoDuration: Accessor<number>;
}

export const Waveform: Component<WaveformProperties> = (props) => {
	const generateWaveformURL = () => {
		const videoInfo = props.videoInfo();
		const videoQuality = props.videoQuality;
		const videoDuration = props.videoDuration();

		const start = wubloaderTimeFromDateTime(videoInfo.streamStartTime);
		const end = videoInfo.streamEndTime ? wubloaderTimeFromDateTime(videoInfo.streamEndTime) : null;

		const query = new URLSearchParams({
			size: "1920x125",
			d: videoDuration.toString(),
			color: "#e5e5e5",
			start: start,
		});
		if (end !== null) {
			query.append("end", end);
		}

		return `/waveform/${videoInfo.streamName}/${videoQuality}.png?${query.toString()}`;
	};

	const [waveformURL, setWaveformURL] = createSignal(generateWaveformURL());

	const setWaveformURLTrigger = leadingAndTrailing(throttle, setWaveformURL, 15000);

	createEffect(() => {
		const waveformURL = generateWaveformURL();
		setWaveformURLTrigger(waveformURL);
	});

	const markerStyle = () => {
		const videoPercentage = (props.videoTime() * 100) / props.videoDuration();
		return `left: ${videoPercentage}%`;
	};

	return (
		<div class={styles.waveformContainer}>
			<img class={styles.waveform} alt="Waveform for this video" src={waveformURL()} />
			<div class={styles.waveformMarker} style={markerStyle()}></div>
		</div>
	);
};
