import { Component, Show } from "solid-js";
import styles from "./CategoryNotes.module.scss";

interface CategoryNotesProps {
	notes?: string;
}

export const CategoryNotes: Component<CategoryNotesProps> = (props) => {
	return (
		<Show when={props.notes}>
			<div class={styles.categoryNotes}>{props.notes}</div>
		</Show>
	);
};
