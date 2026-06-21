import { Accessor, Component, createEffect, createSignal, Setter } from "solid-js";
import { FragmentTimes, RangeData, dateTimeFromVideoPlayerTime } from "./common";
import { bindingDownloadTypeSelectOnChange } from "../common/binding";
import { wubloaderTimeFromDateTime } from "../common/convertTime";
import { DownloadType } from "../common/downloads";
import { StreamVideoInfo } from "../common/streamInfo";

import styles from "./Download.module.scss";

interface DownloadProps {
	streamVideoInfo: Accessor<StreamVideoInfo>;
	rangeData: Accessor<RangeData[]>;
	allowHoles: Accessor<boolean>;
	videoPlayerTime: Accessor<number>;
	videoQuality: string;
	videoFragments: Accessor<FragmentTimes[]>;
}

function downloadTypeInternalName(downloadType: DownloadType): string {
	switch (downloadType) {
		case DownloadType.Smart:
			return "smart";
		case DownloadType.Rough:
			return "rough";
		case DownloadType.Fast:
			return "fast";
		case DownloadType.MPEGTS:
			return "mpegts";
	}
}

export const Download: Component<DownloadProps> = (props) => {
	const [downloadType, setDownloadType] = createSignal(DownloadType.Smart);

	const downloadVideoLink = () => {
		const streamInfo = props.streamVideoInfo();
		const query = new URLSearchParams({
			type: downloadTypeInternalName(downloadType()),
			allow_holes: props.allowHoles().toString(),
		});

		let isFirstRange = true;
		for (const range of props.rangeData()) {
			if (isFirstRange) {
				isFirstRange = false;
			} else {
				query.append("transition", `${range.transitionType()},${range.transitionSeconds()}`);
			}

			let timeRangeString = "";
			const rangeStart = range.startTime();
			const rangeEnd = range.endTime();
			if (rangeStart !== null) {
				timeRangeString += wubloaderTimeFromDateTime(rangeStart);
			}
			timeRangeString += ",";
			if (rangeEnd !== null) {
				timeRangeString += wubloaderTimeFromDateTime(rangeEnd);
			}
			query.append("range", timeRangeString);
		}

		return `/cut/${streamInfo.streamName}/${props.videoQuality}.ts?${query.toString()}`;
	};

	const downloadFrameLink = () => {
		const currentPlayerDateTime = dateTimeFromVideoPlayerTime(
			props.videoPlayerTime(),
			props.videoFragments(),
		);
		if (currentPlayerDateTime === null) {
			return "";
		}
		const currentPlayerWubloaderTime = wubloaderTimeFromDateTime(currentPlayerDateTime);
		return `/frame/${props.streamVideoInfo().streamName}/${props.videoQuality}.png?timestamp=${currentPlayerWubloaderTime}`;
	};

	return (
		<div>
			Download type:
			<select
				use:bindingDownloadTypeSelectOnChange={[downloadType, setDownloadType]}
				class={styles.downloadTypeSelector}
			>
				<option value={DownloadType.Smart}>Standard (preferred option)</option>
				<option value={DownloadType.Rough}>
					Rough (raw content, pads start and end by a few seconds)
				</option>
				<option value={DownloadType.Fast}>
					Standard without retiming (use if Standard is broken)
				</option>
				<option value={DownloadType.MPEGTS}>
					Reencode (slow, consumes server resources to reencode entire video)
				</option>
			</select>
			<a href={downloadVideoLink()} class={styles.downloadLink}>
				Download Video
			</a>
			<a href={downloadFrameLink()} class={styles.downloadLink}>
				Download Current Frame as Image
			</a>
		</div>
	);
};
