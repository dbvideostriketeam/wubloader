import { Accessor, Component, createEffect, createSignal, For, Show, untrack } from "solid-js";
import { MediaPlayerElement } from "vidstack/elements";
import { dateTimeFromVideoPlayerTime, displayTimeForVideoPlayerTime, FragmentTimes, ThumbnailData, ThumbnailTemplateDefinition, ThumbnailType, videoPlayerTimeForDisplayTime, videoPlayerTimeFromDateTime } from "./common";
import { bindingInputOnChange } from "../common/binding";
import styles from "./ThumbnailSettings.module.scss";

import PencilIcon from "../assets/pencil.png";
import PlayToIcon from "../assets/play_to.png";

interface ThumbnailSettingsProps {
	allThumbnailTemplates: ThumbnailTemplateDefinition[];
	thumbnailData: ThumbnailData;
	videoFragments: Accessor<FragmentTimes[]>;
	videoPlayerTime: Accessor<number>;
	videoPlayer: Accessor<MediaPlayerElement>;
}

export const ThumbnailSettings: Component<ThumbnailSettingsProps> = (props) => {
	const setThumbnailType = (event) => {
		const value = (event.currentTarget as HTMLSelectElement).value as ThumbnailType;
		props.thumbnailData.setType(value);
	};
	const setThumbnailTemplate = (event) => {
		const value = (event.currentTarget as HTMLSelectElement).value;
		if (value === "") {
			props.thumbnailData.setTemplate(null);
		} else {
			props.thumbnailData.setTemplate(value);
		}
	};

	const [thumbnailTimeEntry, setThumbnailTimeEntry] = createSignal("");

	createEffect(() => {
		const enteredTime = thumbnailTimeEntry();
		const fragments = props.videoFragments();
		if (enteredTime === "") {
			props.thumbnailData.setTime(null);
			return;
		}
		const playerTime = videoPlayerTimeForDisplayTime(enteredTime);
		const thumbnailTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
		props.thumbnailData.setTime(thumbnailTime);
	});

	createEffect(() => {
		const thumbnailTime = props.thumbnailData.time();
		const fragments = props.videoFragments();
		if (thumbnailTime === null) {
			setThumbnailTimeEntry("");
			return;
		}
		const playerTime = videoPlayerTimeFromDateTime(thumbnailTime, fragments);
		if (playerTime === null) {
			setThumbnailTimeEntry("");
			return;
		}
		const entryTime = displayTimeForVideoPlayerTime(playerTime);
		setThumbnailTimeEntry(entryTime);
	});

	const setThumbnailTime = (event) => {
		const playerTime = props.videoPlayerTime();
		const entryTime = displayTimeForVideoPlayerTime(playerTime);
		setThumbnailTimeEntry(entryTime);
	};

	const setPlayerTimeToThumbnailTime = (event) => {
		const enteredTime = thumbnailTimeEntry();
		const playerTime = videoPlayerTimeForDisplayTime(enteredTime);
		props.videoPlayer().currentTime = playerTime;
	};

	return (
		<div>
			<div>
				Thumbnail:
			</div>
			<div class={styles.firstThumbnailRow}>
				<select value={props.thumbnailData.type()} onChange={setThumbnailType}>
					<option value={ThumbnailType.None}>No custom thumbnail</option>
					<option value={ThumbnailType.Frame}>Use video frame</option>
					<option value={ThumbnailType.Template}>Use video frame in image template</option>
					<option value={ThumbnailType.CustomTemplate}>Use video frame with a custom one-off overlay</option>
					<option value={ThumbnailType.CustomThumbnail}>Use a custom thumbnail image</option>
				</select>
				<Show when={props.thumbnailData.type() === ThumbnailType.Template}>
					<select value={props.thumbnailData.template() ?? ""} onChange={setThumbnailTemplate}>
						<For each={props.allThumbnails}>
							{(template: ThumbnailTemplateDefinition) => <option value={template.name} title={template.description}>{template.name}</option>}
						</For>
					</select>
				</Show>
				<Show when={props.thumbnailData.type() === ThumbnailType.Frame || props.thumbnailData.type() === ThumbnailType.Template || props.thumbnailData.type() === ThumbnailType.CustomTemplate}>
					<div class={styles.timeRangeEntry}>
						<div class={styles.timeRangeSelect}>
							<input
								class={styles.timeEntry}
								use:bindingInputOnChange={[thumbnailTimeEntry, setThumbnailTimeEntry]}
							/>
						</div>
						<div class={styles.timeRangeIcon}>
							<img
								class={styles.clickable}
								src={PencilIcon}
								alt="Set thumbnail time to current video time"
								title="Set thumbnail time to current video time"
								onClick={setThumbnailTime}
							/>
						</div>
						<div class={styles.timeRangeIcon}>
							<img
								class={styles.clickable}
								src={PlayToIcon}
								alt="Play from the thumbnail time"
								title="Play from the thumbnail time"
								onClick={setPlayerTimeToThumbnailTime}
							/>
						</div>
					</div>
				</Show>
			</div>
		</div>
	);
};
