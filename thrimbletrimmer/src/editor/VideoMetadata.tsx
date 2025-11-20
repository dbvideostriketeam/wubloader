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
}

export const VideoMetadata: Component<VideoMetadataProps> = (props) => {
	const [enteredTags, setEnteredTags] = createSignal("");

	createEffect(() => {
		setEnteredTags(props.tags().join(","));
	});

	createEffect(() => {
		props.setTags(enteredTags().split(","));
	});

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
		</div>
	);
};
