import {
	Accessor,
	Component,
	createEffect,
	createResource,
	createSignal,
	Index,
	Setter,
	Show,
} from "solid-js";
import { DateTime } from "luxon";
import { bindingInputOnChange } from "../common/binding";
import { dateTimeFromWubloaderTime } from "../common/convertTime";
import { GoogleSignIn, defaultAccountToken } from "../common/googleAuth";

import styles from "./Challenges.module.scss";

interface ChallengeData {
	id: string;
	description_text: string;
	completed_at: string;
	vst_url: string | null;
}

enum VideoFilter {
	All = "all",
	HasVideo = "has-video",
	NoVideo = "no-video",
}

export function bindingVideoFilterSelectOnChange(
	element: HTMLSelectElement,
	accessor: () => [Accessor<VideoFilter>, Setter<VideoFilter>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) =>
		set((event.currentTarget as HTMLSelectElement).value as VideoFilter),
	);
	createEffect(() => (element.value = s().toString()));
}

declare module "solid-js" {
	namespace JSX {
		interface DirectiveFunctions {
			// This block is correct but cannot be made to typecheck correctly.
			// @ts-ignore
			bindingVideoFilterSelectOnChange: typeof bindingVideoFilterSelectOnChange;
		}
	}
}

export const Challenges: Component = () => {
	const [challengesLoadError, setChallengesLoadError] = createSignal("");
	const [challenges, challengesActions] = createResource(
		async () => {
			const challengesResponse = await fetch("/thrimshim/challenges");
			if (!challengesResponse.ok) {
				setChallengesLoadError(await challengesResponse.text());
				return null;
			}
			const challengesData: ChallengeData[] = await challengesResponse.json();
			return challengesData;
		},
		{ initialValue: [] },
	);
	const [accountToken, setAccountToken] = createSignal<string | null>(defaultAccountToken());

	const [filterHasVideo, setFilterHasVideo] = createSignal(VideoFilter.All);

	return (
		<>
			<div>
				<label>
					Has video filter:
					<select use:bindingVideoFilterSelectOnChange={[filterHasVideo, setFilterHasVideo]}>
						<option selected value={VideoFilter.All}>
							All
						</option>
						<option value={VideoFilter.HasVideo}>Has Video</option>
						<option value={VideoFilter.NoVideo}>No Video</option>
					</select>
				</label>
			</div>
			<GoogleSignIn accountToken={accountToken} setAccountToken={setAccountToken} />
			<Show when={challenges() === null}>
				<div class={styles.loadError}>
					<p>Failed to get challenges data.</p>
					<p>{challengesLoadError()}</p>
				</div>
			</Show>
			<table class={styles.challenges}>
				<Index each={challenges() ?? []}>
					{(challenge, index) => {
						const [enteredURL, setEnteredURL] = createSignal(challenge().vst_url ?? "");
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
							const userAccountToken = accountToken();
							if (userAccountToken) {
								authToken = userAccountToken;
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
								setSubmitResult({
									isError: true,
									message: `Error during submission: ${await submitResponse.text()}`,
								});
							}
						};

						const showChallenge = () => {
							const url = challenge().vst_url;
							const filter = filterHasVideo();
							if (filter === VideoFilter.All) {
								return true;
							}
							return (
								(filter === VideoFilter.HasVideo && url !== null) ||
								(filter === VideoFilter.NoVideo && url === null)
							);
						};

						const completed_at_timestamp = () => {
							const completed_time = dateTimeFromWubloaderTime(challenge().completed_at);
							if (completed_time === null) {
								return "";
							}
							const completed_time_local = completed_time.setZone("America/Vancouver");
							return completed_time_local.toLocaleString(DateTime.DATETIME_FULL);
						};

						return (
							<Show when={showChallenge()}>
								<tr>
									<td>{challenge().description_text}</td>
									<td style="text-wrap: nowrap">{completed_at_timestamp()}</td>
									<td>
										<form on:submit={submitHandler}>
											<div
												class={submitResult().isError ? styles.submitError : styles.submitSuccess}
											>
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
							</Show>
						);
					}}
				</Index>
			</table>
		</>
	);
};
