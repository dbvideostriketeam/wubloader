import {
	Accessor,
	Component,
	Setter,
	createEffect,
	createSignal,
	createResource,
	Match,
	onMount,
	Switch,
	Show,
} from "solid-js";
import { createScriptLoader } from "@solid-primitives/script-loader";

export interface GoogleSignInProps {
	accountToken: Accessor<string | null>;
	setAccountToken: Setter<string | null>;
}

export const GoogleSignIn: Component<GoogleSignInProps> = (props) => {
	let loginButtonParent!: HTMLDivElement;

	const [scriptLoaded, setScriptLoaded] = createSignal(false);
	const [mounted, setMounted] = createSignal(false);
	const [authConfig] = createResource(async () => {
		const response = await fetch("/thrimshim/auth-config");
		if (!response.ok) throw new Error("Unable to load sign-in configuration.");
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

	const handleSignIn = (response) => {
		props.setAccountToken(response.credential);
	};

	const handleSignOut = (event) => {
		props.setAccountToken(null);
	};

	onMount(() => {
		setMounted(true);
	});

	createEffect(() => {
		const loadComplete = scriptLoaded();
		const mountComplete = mounted();
		const config = authConfig.error ? undefined : authConfig();
		if (loadComplete && mountComplete && config) {
			google.accounts.id.initialize({
				client_id: config.google_client_id,
				callback: handleSignIn,
			});
			google.accounts.id.renderButton(loginButtonParent, { theme: "outline_dark", width: "250" });
		}
	});

	return (
		<>
			<Show when={authConfig.error}>
				<span role="alert">Unable to load sign-in configuration. Please reload to try again.</span>
			</Show>
			<Switch fallback={<a onClick={handleSignOut}>Sign Out of Google</a>}>
				<Match when={props.accountToken() === null}>
					<div ref={loginButtonParent}></div>
				</Match>
			</Switch>
		</>
	);
};
