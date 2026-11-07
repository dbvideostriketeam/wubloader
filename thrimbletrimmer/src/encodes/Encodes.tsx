import {
	Accessor,
	Component,
	createEffect,
	createMemo,
	createSignal,
	Index,
	Match,
	Switch,
	untrack,
} from "solid-js";
import { GoogleSignIn, defaultAccountToken } from "../common/googleAuth";

import styles from "./Encodes.module.scss";

interface EncodeItem {
	src_url: string;
	src_hash: string;
	encode_args: string[];
	dest_url: string;
	claimed_by: string | null;
	dest_hash: string | null;
}

const EncodeUrl: Component<{ url: string }> = (props) => {
	const [expanded, setExpanded] = createSignal(false);
	const name = () => props.url.match(/DB\d{4}_(.*)\.mkv$/)?.[1] ?? props.url;

	return (
		<>
			{expanded() ? props.url : name()}{" "}
			<a href="#" onClick={(event) => {
				event.preventDefault();
				setExpanded(!expanded());
			}}>
				[{expanded() ? "compact" : "expand"}]
			</a>
		</>
	);
};

const EncodeHash: Component<{ hash: string }> = (props) => {
	const [expanded, setExpanded] = createSignal(false);
	const shortened = () => props.hash.length > 8 ? `${props.hash.slice(0, 4)}...${props.hash.slice(-4)}` : props.hash;

	return (
		<>
			{expanded() ? props.hash : shortened()}{" "}
			<a href="#" onClick={(event) => {
				event.preventDefault();
				setExpanded(!expanded());
			}}>
				[{expanded() ? "compact" : "expand"}]
			</a>
		</>
	);
};

export const Encodes: Component = () => {
	const [accountToken, setAccountToken] = createSignal<string | null>(defaultAccountToken());
	const isSignedIn = createMemo(() => accountToken() !== null);

	const [encodesList, setEncodesList] = createSignal<EncodeItem[]>([]);
	const [loadError, setLoadError] = createSignal("");

	const loadEncodeData = async () => {
		setLoadError("");

		// Before the first `await`, this can be used in a reactive context and still track used signals.
		const token = untrack(accountToken);
		if (token === null) {
			setEncodesList([]);
			return;
		}

		const requestBody = JSON.stringify({ token: token });
		const encodesResponse = await fetch("/thrimshim/encodes", {
			method: "POST",
			body: requestBody,
			headers: { "Content-Type": "application/json" },
		});
		if (!encodesResponse.ok) {
			setLoadError(`Failed to fetch encode data: ${await encodesResponse.text()}`);
			return;
		}
		const encodesList: EncodeItem[] = await encodesResponse.json();
		setEncodesList(encodesList);
	};
	createEffect(() => {
		// This tracks only the memoized derived value of whether we're signed in so that if, for whatever reason, the token
		// changes without signing out, we don't refetch everything.
		if (!isSignedIn()) {
			setEncodesList([]);
			return;
		}

		loadEncodeData();
	});

	return (
		<>
			<div class={styles.loadError}>{loadError()}</div>
			<table class={styles.encodesTable}>
				<thead>
					<tr>
						<th>Source</th>
						<th>Source Hash</th>
						<th>Encode Args</th>
						<th>Dest</th>
						<th>Claimed By</th>
						<th>Dest Hash</th>
					</tr>
				</thead>
				<tbody>
					<Index each={encodesList()}>
						{(item: Accessor<EncodeItem>, index: number) => {
							const [claimDisabled, setClaimDisabled] = createSignal(false);
							const [submitDisabled, setSubmitDisabled] = createSignal(false);

							const claimHandler = async (event: MouseEvent) => {
								setClaimDisabled(true);

								const payload = {
									token: accountToken(),
									dest_url: item().dest_url,
								};
								const payloadJSON = JSON.stringify(payload);
								await fetch("/thrimshim/encodes/claim", {
									method: "POST",
									body: payloadJSON,
									headers: { "Content-Type": "application/json" },
								});
								await loadEncodeData();
								setClaimDisabled(false);
							};

							const submitHandler = async (event: SubmitEvent) => {
								event.preventDefault();
								if (submitDisabled()) {
									return;
								}
								setSubmitDisabled(true);

								const formData = new FormData(event.currentTarget as HTMLFormElement);

								const payload = {
									token: accountToken(),
									dest_url: item().dest_url,
									dest_hash: formData.get("dest_hash") as string,
								};
								const payloadJSON = JSON.stringify(payload);
								await fetch("/thrimshim/encodes/submit", {
									method: "POST",
									body: payloadJSON,
									headers: { "Content-Type": "application/json" },
								});
								await loadEncodeData();
								setSubmitDisabled(false);
							};

							return (
								<tr>
									<td><EncodeUrl url={item().src_url} /></td>
									<td><EncodeHash hash={item().src_hash} /></td>
									<td>{item().encode_args.join(" ")}</td>
									<td><EncodeUrl url={item().dest_url} /></td>
									<td>
										<Switch>
											<Match when={item().claimed_by === null}>
												<button disabled={claimDisabled()} onClick={claimHandler}>
													Claim
												</button>
											</Match>
											<Match when={item().claimed_by !== null}>{item().claimed_by}</Match>
										</Switch>
									</td>
									<td>
										<Switch>
											<Match when={item().dest_hash === null}>
												<form onSubmit={submitHandler}>
													<input type="text" placeholder="Dest Hash" name="dest_hash" />
													<button type="submit" disabled={submitDisabled()}>
														Submit
													</button>
												</form>
											</Match>
											<Match when={item().dest_hash !== null}><EncodeHash hash={item().dest_hash!} /></Match>
										</Switch>
									</td>
								</tr>
							);
						}}
					</Index>
				</tbody>
			</table>
			<GoogleSignIn accountToken={accountToken} setAccountToken={setAccountToken} />
		</>
	);
};
