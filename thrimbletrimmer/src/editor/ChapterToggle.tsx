import { Accessor, Component, Setter } from "solid-js";
import styles from "./ChapterToggle.module.scss";
import { EditorState } from "./common";

interface ChapterToggleProps {
	chaptersEnabled: Accessor<boolean>;
	setChaptersEnabled: Setter<boolean>;
	allFieldsDisabled: Accessor<boolean>;
}

export const ChapterToggle: Component<ChapterToggleProps> = (props) => {
	const updateEnabled = (event: Event) => {
		const checkbox = event.currentTarget;
		if (checkbox) {
			const checkboxElement = checkbox as HTMLInputElement;
			props.setChaptersEnabled(checkboxElement.checked);
		}
	};
	return (
		<div class={styles.chaptersEnabledSelection}>
			<label>
				<input
					type="checkbox"
					checked={props.chaptersEnabled()}
					onChange={updateEnabled}
					disabled={props.allFieldsDisabled()}
				/>
				Add chapter markers to the video description
			</label>
		</div>
	);
};
