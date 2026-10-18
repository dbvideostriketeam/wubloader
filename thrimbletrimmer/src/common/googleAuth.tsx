import {
	Accessor,
	Component,
	Setter,
	createEffect,
	createSignal,
	createResource,
	onMount,
	Show,
} from "solid-js";
import { createScriptLoader } from "@solid-primitives/script-loader";

export interface GoogleSignInProps {
	accountToken: Accessor<string | null>;
	setAccountToken: Setter<string | null>;
}

const TOKEN_STORAGE_KEY = "thrimbletrimmer.googleToken";

export const GoogleSignIn: Component<GoogleSignInProps> = (props) => {
	let loginButtonParent!: HTMLDivElement;

	const [scriptLoaded, setScriptLoaded] = createSignal(false);
	const [authConfig] = createResource(async () => {
		const response = await fetch("/thrimshim/auth-config");
		if (!response.ok) {
			throw new Error("Unable to load sign-in configuration.");
		}
		const config = await response.json();
		if (typeof config.google_client_id !== "string" || !config.google_client_id) {
			throw new Error("Google sign-in is not configured.");
		}
		return config as { google_client_id: string };
	});

	createScriptLoader({
		src: "https://accounts.google.com/gsi/client",
		onLoad: async () => {
			setScriptLoaded(true);
		},
	});

	const handleSignIn = (response: google.accounts.id.CredentialResponse) => {
		props.setAccountToken(response.credential);
	};

	const handleSignOut = () => {
		props.setAccountToken(null);
		if (scriptLoaded()) {
			google.accounts.id.disableAutoSelect();
		}
	};

	onMount(() => {
		let token: string | null;
		try {
			token = localStorage.getItem(TOKEN_STORAGE_KEY);
		} catch {
			// Sign-in still works without browser storage.
			return;
		}
		if (token) {
			props.setAccountToken(token);
		}
	});

	createEffect(() => {
		const token = props.accountToken();
		try {
			if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
			else localStorage.removeItem(TOKEN_STORAGE_KEY);
		} catch {
			// Persistence is optional; authentication is verified by the server.
		}
	});

	createEffect(() => {
		const loadComplete = scriptLoaded();
		const config = authConfig.error ? undefined : authConfig();
		if (loadComplete && config) {
			google.accounts.id.initialize({
				client_id: config.google_client_id,
				callback: handleSignIn,
			});
			google.accounts.id.renderButton(loginButtonParent, { theme: "outline_dark", width: "250" });
		}
	});

	return (
		<Show
			when={!authConfig.error}
			fallback={
				<span role="alert">Unable to load sign-in configuration. Please reload to try again.</span>
			}
		>
			<div>
				<div ref={loginButtonParent} hidden={!!props.accountToken()}></div>
				<Show when={props.accountToken()}>
					<span>Signed in. </span>
					<button type="button" onClick={handleSignOut}>Sign out</button>
				</Show>
			</div>
		</Show>
	);
};
