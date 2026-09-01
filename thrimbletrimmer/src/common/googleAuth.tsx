import { Accessor, Component, Setter, createEffect, createSignal, onMount } from "solid-js";
import { createScriptLoader } from "@solid-primitives/script-loader";

export interface GoogleSignInProps {
	accountToken: Accessor<string | null>;
	setAccountToken: Setter<string | null>;
}

export const GoogleSignIn: Component<GoogleSignInProps> = (props) => {
	let loginButtonParent!: HTMLDivElement;

	const [scriptLoaded, setScriptLoaded] = createSignal(false);
	const [mounted, setMounted] = createSignal(false);

	createScriptLoader({
		src: "https://accounts.google.com/gsi/client",
		onLoad: async () => {
			setScriptLoaded(true);
		},
	});

	const handleSignIn = (response) => {
		props.setAccountToken(response.credential);
	};

	onMount(() => {
		setMounted(true);
	});

	createEffect(() => {
		const loadComplete = scriptLoaded();
		const mountComplete = mounted();
		if (loadComplete && mountComplete) {
			google.accounts.id.initialize({
				client_id: "345276493482-r84m2giavk10glnmqna0lbq8e1hdaus0.apps.googleusercontent.com",
				callback: handleSignIn,
			});
			google.accounts.id.renderButton(loginButtonParent, { theme: "outline_dark", width: "250" });
		}
	});

	return <div ref={loginButtonParent}></div>;
};
