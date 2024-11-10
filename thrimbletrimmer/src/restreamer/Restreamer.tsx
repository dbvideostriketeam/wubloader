import { Accessor, Component, createSignal, For } from "solid-js";
import styles from "./Restreamer.module.scss";
import { KeyboardShortcuts } from "../common/videoKeyboardShortcuts";

const Restreamer: Component = () => {
	const [pageErrors, setPageErrors] = createSignal<string[]>([]);

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
		</>
	);
};

export default Restreamer;
