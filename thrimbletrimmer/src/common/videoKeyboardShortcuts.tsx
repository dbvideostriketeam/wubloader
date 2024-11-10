import { Component, Show } from "solid-js";

export interface KeyboardShortcutProps {
	includeEditorShortcuts: boolean;
}

export const KeyboardShortcuts: Component<KeyboardShortcutProps> = (
	props: KeyboardShortcutProps,
) => {
	return (
		<details>
			<summary>Keyboard Shortcuts</summary>
			<ul>
				<li>Number keys (0-9): Jump to that 10% interval of the video (0% - 90%)</li>
				<li>K or Space: Toggle pause</li>
				<li>M: Toggle mute</li>
				<li>J: Back 10 seconds</li>
				<li>L: Forward 10 seconds</li>
				<li>Left arrow: Back 5 seconds</li>
				<li>Right arrow: Forward 5 seconds</li>
				<li>Shift+J: Back 1 second</li>
				<li>Shift+L: Forward 1 second</li>
				<li>Comma (,): Back 1 frame</li>
				<li>Period (.): Forward 1 frame</li>
				<li>Equals (=): Increase playback speed 1 step</li>
				<li>Hyphen (-): Decrease playback speed 1 step</li>
				<li>Shift+=: 2x or maximum playback speed</li>
				<li>Shift+-: Minimum playback speed</li>
				<li>Backspace: Reset playback speed to 1x</li>
				<Show when={props.includeEditorShortcuts}>
					<li>
						Left bracket ([): Set start point for active range (indicated by arrow) to current video
						time
					</li>
					<li>Right bracket (]): Set end point for active range to current video time</li>
					<li>O: Set active range one above current active range</li>
					<li>
						P: Set active range one below current active range, adding a new range if the current
						range is the last one
					</li>
				</Show>
			</ul>
		</details>
	);
};
