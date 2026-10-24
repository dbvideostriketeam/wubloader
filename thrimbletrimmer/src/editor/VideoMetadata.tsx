import { Accessor, Component, createEffect, createSignal, Setter } from "solid-js";
import styles from "./VideoMetadata.module.scss";
import {
	bindingInputOnChange,
	bindingInputOnInput,
	bindingTextareaOnChange,
} from "../common/binding";

interface VideoMetadataProps {
	titlePrefix: string;
	titleMaxLength: number;
	title: Accessor<string>;
	setTitle: Setter<string>;
	description: Accessor<string>;
	setDescription: Setter<string>;
	tags: Accessor<string[]>;
	setTags: Setter<string[]>;
	setSubtitles: Setter<string>;
}

export const VideoMetadata: Component<VideoMetadataProps> = (props) => {
	const [enteredTags, setEnteredTags] = createSignal("");

	createEffect(() => {
		setEnteredTags(props.tags().join(","));
	});

	createEffect(() => {
		props.setTags(
			enteredTags()
				.split(",")
				.filter((tag) => tag.trim() !== ""),
		);
	});

	const [subtitleUploadError, setSubtitleUploadError] = createSignal("");
	const setSubtitles = async (event: Event) => {
		const fileElement = event.currentTarget as HTMLInputElement;
		const subtitleData = await getUploadedSubtitlesAsText(fileElement);
		if (subtitleData.valueType === SubtitleDataType.Error) {
			setSubtitleUploadError(subtitleData.data);
		} else {
			setSubtitleUploadError("");
			props.setSubtitles(subtitleData.data);
		}
	};

	return (
		<div class={styles.info}>
			<label>
				<div>Title:</div>
				<div class={styles.titleContainer}>
					<span>{props.titlePrefix}</span>
					<input
						class={styles.title}
						type="text"
						use:bindingInputOnInput={[props.title, props.setTitle]}
						maxLength={props.titleMaxLength}
					/>
				</div>
			</label>
			<div>Abbreviated title:</div>
			<div class={styles.abbreviatedTitle}>{props.title()}</div>
			<label>
				<div>Description:</div>
				<textarea use:bindingTextareaOnChange={[props.description, props.setDescription]} />
			</label>
			<label>
				<div>Tags (comma-separated):</div>
				<input type="text" use:bindingInputOnChange={[enteredTags, setEnteredTags]} />
			</label>
			<label>
				<div>Subtitles:</div>
				<div>
					<input type="file" onChange={setSubtitles} />
					<div class={styles.subtitleError}>{subtitleUploadError()}</div>
				</div>
			</label>
		</div>
	);
};

enum SubtitleDataType {
	ValidData,
	Error,
}

interface UploadedSubtitleData {
	valueType: SubtitleDataType;
	data: string;
}

async function getUploadedSubtitlesAsText(
	fileElement: HTMLInputElement,
): Promise<UploadedSubtitleData> {
	if (!fileElement.files) {
		return {
			valueType: SubtitleDataType.Error,
			data: "Not a file upload field",
		};
	}
	if (fileElement.files.length === 0) {
		return {
			valueType: SubtitleDataType.ValidData,
			data: "",
		};
	}

	const fileHandle = fileElement.files[0];
	if (fileHandle.size > 50 * 1048576) {
		return {
			valueType: SubtitleDataType.Error,
			data: "Uploaded file is too large (limit: 50MB)",
		};
	}
	const fileReader = new FileReader();

	let loadPromiseResolve: (value: void) => void;
	const loadPromise = new Promise((resolve, reject) => {
		loadPromiseResolve = resolve;
	});
	fileReader.addEventListener("loadend", (event) => {
		loadPromiseResolve();
	});
	fileReader.readAsText(fileHandle);
	await loadPromise;

	const textData = fileReader.result as string;

	if (textData.indexOf("\0") !== -1) {
		return {
			valueType: SubtitleDataType.Error,
			data: "The file you're uploading is not valid text data.",
		};
	}

	return {
		valueType: SubtitleDataType.ValidData,
		data: fileReader.result as string,
	};
}
