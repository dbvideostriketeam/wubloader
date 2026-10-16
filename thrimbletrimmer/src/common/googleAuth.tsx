import { Accessor, Component, Setter, Show, createEffect, createResource, createSignal, onMount } from "solid-js";
import { createScriptLoader } from "@solid-primitives/script-loader";
import { jwtDecode } from "jwt-decode";
import { createTimeoutLoop } from "@solid-primitives/timer";

export interface GoogleSignInProps {
	accountToken: Accessor<string | null>;
	setAccountToken: Setter<string | null>;
}

const TOKEN_STORAGE_KEY = "thrimbletrimmer.googleToken";

// Tokens by default expire after an hour, we need to detect this to show the user a
// fresh sign-in prompt
function tokenExpiresAt(token: string): number {
	try {
		const { exp } = jwtDecode(token);
		if (typeof exp !== "number") {
			return 0;
		}
		const expiresAt = exp * 1000;
		return Number.isFinite(expiresAt) ? expiresAt : 0;
	} catch {
		return 0;
	}
}

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

	onMount(() => {
		try {
			const token = sessionStorage.getItem(TOKEN_STORAGE_KEY);
			if (token && tokenExpiresAt(token) > Date.now()) {
				props.setAccountToken(token);
			}
		} catch {
			// Browser storage is unavailable
		}
	});

	createEffect(() => {
		const token = props.accountToken();
		const expiresAt = token ? tokenExpiresAt(token) : 0;
		if (token && expiresAt <= Date.now()) {
			props.setAccountToken(null);
			return;
		}
		try {
			if (token) sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
			else sessionStorage.removeItem(TOKEN_STORAGE_KEY);
		} catch {
			// Browser storage is unavailable but we can still use the token on this pageview
		}
		if (!token) {
			return;
		}

		const checkExpiry = () => {
			if (expiresAt <= Date.now()) {
				props.setAccountToken(null);
			}
		};
		createTimeoutLoop(checkExpiry, () => Math.min(expiresAt - Date.now(), 2147483647));
	});

	const handleSignOut = () => {
		props.setAccountToken(null);
		if (scriptLoaded()) {
			google.accounts.id.disableAutoSelect();
		}
	};

	createEffect(() => {
		const loadComplete = scriptLoaded();
		const config = authConfig.error ? undefined : authConfig();
		if (loadComplete && config) {
			google.accounts.id.initialize({
				client_id: config.google_client_id,
				callback: handleSignIn,
			});
			google.accounts.id.renderButton(loginButtonParent, { theme: "outline_dark", width: 250 });
		}
	});

	return (
		<div>
			<Show when={authConfig.error}>
				<span role="alert">Unable to load sign-in configuration. Please reload to try again.</span>
			</Show>
			<div ref={loginButtonParent} hidden={!!props.accountToken()}></div>
			<Show when={props.accountToken()}>
				<span>Signed in. </span>
				<button type="button" onClick={handleSignOut}>Sign out</button>
			</Show>
		</div>
	);
};
