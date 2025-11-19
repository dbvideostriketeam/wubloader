import { Component, Show } from "solid-js";
import styles from "./NotesToEditor.module.scss";

interface NotesToEditorProps {
	notes: string;
}

export const NotesToEditor: Component<NotesToEditorProps> = (props) => {
	return (
		<Show when={props.notes}>
			<div class={styles.notesToEditor}>
				<div>Notes to Editor:</div>
				<div>{props.notes}</div>
			</div>
		</Show>
	);
};
