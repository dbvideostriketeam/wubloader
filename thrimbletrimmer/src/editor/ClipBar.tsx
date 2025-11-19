import { Accessor, Component, For, Show } from "solid-js";
import { FragmentTimes, RangeData, videoPlayerTimeFromDateTime } from "./common";
import styles from "./ClipBar.module.scss";

interface ClipBarProperties {
	rangeData: Accessor<RangeData[]>;
	videoFragments: Accessor<FragmentTimes[]>;
	videoDuration: Accessor<number>;
}

export const ClipBar: Component<ClipBarProperties> = (props) => {
	return (
		<div class={styles.clipBar}>
			<Show when={props.videoFragments().length > 0 && props.videoDuration() > 0} keyed>
				<For each={props.rangeData()}>
					{(range: RangeData) => {
						const styleString = () => {
							const rangeStartTime = range.startTime();
							const rangeEndTime = range.endTime();
							const fragments = props.videoFragments();
							const duration = props.videoDuration();

							if (rangeStartTime === null || rangeEndTime === null) {
								return "width: 0px";
							}
							const rangeStart = videoPlayerTimeFromDateTime(rangeStartTime, fragments);
							const rangeEnd = videoPlayerTimeFromDateTime(rangeEndTime, fragments);
							if (rangeStart === null || rangeEnd === null) {
								return "width: 0px";
							}
							const startPercentage = (rangeStart / duration) * 100;
							const endPercentage = (rangeEnd / duration) * 100;
							const widthPercentage = endPercentage - startPercentage;
							return `left: ${startPercentage}%; width: ${widthPercentage}%;`;
						};
						return <div style={styleString()}></div>;
					}}
				</For>
			</Show>
		</div>
	);
};
