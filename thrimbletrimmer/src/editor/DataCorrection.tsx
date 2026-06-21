import { Component, Show, createSignal } from "solid-js";
import { bindingInputChecked, bindingInputOnChange } from "../common/binding";
import { googleUser } from "../common/googleAuth";

import styles from "./DataCorrection.module.scss";

interface DataCorrectionProps {
	videoID: string;
}

export const DataCorrection: Component<DataCorrectionProps> = (props) => {
	const [showManualLinkForm, setShowManualLinkForm] = createSignal(false);
	const [manualLink, setManualLink] = createSignal("");
	const [youtubeUpload, setYoutubeUpload] = createSignal(false);
	const [showForceResetConfirmation, setShowForceResetConfirmation] = createSignal(false);
	const [actionMessage, setActionMessage] = createSignal("");

	const toggleShowManualLinkForm = (event) => {
		setShowManualLinkForm(!showManualLinkForm());
	};

	const submitManualVideoLink = async (event) => {
		const uploadLocation = youtubeUpload() ? "youtube-manual" : "manual";
		const link = manualLink();

		const request = {
			link,
			upload_location: uploadLocation,
			token: undefined,
		};
		if (googleUser) {
			request.token = googleUser.getAuthResponse().id_token;
		} else {
			delete request.token;
		}

		setActionMessage("Submitting link...");

		const response = await fetch(`/thrimshim/manual-link/${props.videoID}`, {
			method: "POST",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
			},
			body: JSON.stringify(request),
		});

		if (response.ok) {
			setActionMessage(`Manual link set to ${link}`);
		} else {
			setActionMessage(
				`Failed to update manual link (${response.statusText}: ${await response.text()})`,
			);
		}
	};

	const cancelUpload = async (event) => {
		const request = {
			token: undefined,
		};
		if (googleUser) {
			request.token = googleUser.getAuthResponse().id_token;
		} else {
			delete request.token;
		}

		setActionMessage("Submitting cancel request...");

		const response = await fetch(`/thrimshim/reset/${props.videoID}?force=false`, {
			method: "POST",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
			},
			body: JSON.stringify(request),
		});

		if (response.ok) {
			setActionMessage("Row has been canceled.");
		} else {
			setActionMessage(`Cancel failed (${response.statusText}: ${await response.text()}`);
		}
	};

	const resetRow = async (event) => {
		const request = {
			token: undefined,
		};
		if (googleUser) {
			request.token = googleUser.getAuthResponse().id_token;
		} else {
			delete request.token;
		}

		setActionMessage("Submitting reset request...");

		const response = await fetch(`/thrimshim/reset/${props.videoID}?force=true`, {
			method: "POST",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
			},
			body: JSON.stringify(request),
		});

		if (response.ok) {
			setActionMessage("Row has been reset.");
			setShowForceResetConfirmation(false);
		} else {
			setActionMessage(`Reset failed (${response.statusText}: ${await response.text()})`);
		}
	};

	const showResetConfirmation = (event) => {
		setShowForceResetConfirmation(true);
	};

	const hideResetConfirmation = (event) => {
		setShowForceResetConfirmation(false);
	};

	return (
		<div>
			<div class={styles.toolbar}>
				<a onClick={toggleShowManualLinkForm} class={styles.click}>
					Manual Link Update
				</a>
				|
				<a onClick={cancelUpload} class={styles.click}>
					Cancel Upload
				</a>
				|
				<a onClick={showResetConfirmation} class={styles.click}>
					Force Reset Row
				</a>
			</div>
			<Show when={showManualLinkForm()}>
				<div class={styles.manualLinkRow}>
					<input type="text" use:bindingInputOnChange={[manualLink, setManualLink]} />
					<label>
						Is YouTube upload (add to playlists)?
						<input type="checkbox" use:bindingInputChecked={[youtubeUpload, setYoutubeUpload]} />
					</label>
					<button onClick={submitManualVideoLink}>Set Link</button>
				</div>
			</Show>
			<Show when={showForceResetConfirmation()}>
				<div>
					<p>Are you sure you want to reset this event?</p>
					<p>
						This will set the row back to Unedited and forget about any video that may already
						exist.
					</p>
					<p>
						This is intended as a last-ditch effort to clear a malfunctioning cutter, or if a video
						needs to be reedited and replaced.
					</p>
					<p>
						<strong>
							It is your responsibility to deal with any video that may have already been uploaded.
						</strong>
					</p>
					<p>
						<button onClick={resetRow}>Yes, reset it!</button>
						<button onClick={hideResetConfirmation}>Oh, never mind.</button>
					</p>
				</div>
			</Show>
			<div>{actionMessage()}</div>
		</div>
	);
};
