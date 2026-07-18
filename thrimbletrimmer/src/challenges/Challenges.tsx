import { Component, createResource, createSignal, Index, Show } from "solid-js";
import { bindingInputOnChange } from "../common/binding";
import { GoogleSignIn, googleUser } from "../common/googleAuth";

import styles from "./Challenges.module.scss";

interface ChallengeData {
	id: string;
	description: string;
	vstURL: string;
}

export const Challenges: Component = () => {
	const [challenges, challengesActions] = createResource(
		async () => {
			const challengesResponse = await fetch("/thrimshim/challenges");
			if (!challengesResponse.ok) {
				return null;
			}
			const challengesData: ChallengeData[] = await challengesResponse.json();
			return challengesData;
		},
		{ initialValue: [] },
	);

	return (
		<>
			<Show when={challenges() === null}>
				<div class={styles.loadError}>Failed to get challenges data.</div>
			</Show>
			<table class={styles.challenges}>
				<Index each={challenges() ?? []}>
					{(challenge, index) => {
						const [enteredURL, setEnteredURL] = createSignal(challenge().vstURL);
						const [submitResult, setSubmitResult] = createSignal({ isError: false, message: "" });

						const submitHandler = async (event: SubmitEvent) => {
							event.preventDefault();

							let url: string | null = enteredURL();
							if (
								url !== "" &&
								!url.startsWith("https://www.youtube.com/watch") &&
								!url.startsWith("https://youtube.com/watch") &&
								!url.startsWith("https://youtu.be/")
							) {
								setSubmitResult({
									isError: true,
									message: "That doesn't seem to be a YouTube link.",
								});
								return;
							}
							if (url === "") {
								url = null;
							}

							let authToken: string;
							if (googleUser) {
								authToken = googleUser.getAuthResponse.id_token;
							} else {
								setSubmitResult({ isError: true, message: "You're not logged in." });
								return;
							}

							const submitResponse = await fetch(`/thrimshim/challenges/${challenge().id}`, {
								method: "POST",
								headers: {
									Accept: "application/json",
									"Content-Type": "application/json",
								},
								body: JSON.stringify({
									token: authToken,
									url: url,
								}),
							});

							if (submitResponse.ok) {
								setSubmitResult({ isError: false, message: "Updated successfully." });
							} else {
								setSubmitResult({ isError: true, message: "Error during submission" });
							}
						};

						return (
							<tr>
								<td>{challenge().description}</td>
								<td>
									<form on:submit={submitHandler}>
										<div class={submitResult().isError ? styles.submitError : styles.submitSuccess}>
											{submitResult().message}
										</div>
										<input
											type="text"
											name="url"
											use:bindingInputOnChange={[enteredURL, setEnteredURL]}
										/>
										<button type="submit">Submit</button>
									</form>
								</td>
							</tr>
						);
					}}
				</Index>
			</table>
			<GoogleSignIn />
		</>
	);
};
