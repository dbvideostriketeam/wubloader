import { Component } from "solid-js";

export let googleUser: any = null;
declare var gapi: any; // This is a global we use from the Google Sign In script

function googleOnSignIn(googleUserData) {
	googleUser = googleUserData;

	const signInElem = document.getElementById("google-auth-sign-in");
	if (signInElem) {
		signInElem.classList.remove("hidden");
	}
	const signOutElem = document.getElementById("google-auth-sign-out");
	if (signOutElem) {
		signOutElem.classList.add("hidden");
	}
}

async function googleSignOut() {
	if (googleUser) {
		googleUser = null;
		await gapi.auth2.getAuthInstance().signOut();

		const signInElem = document.getElementById("google-auth-sign-in");
		if (signInElem) {
			signInElem.classList.add("hidden");
		}
		const signOutElem = document.getElementById("google-auth-sign-out");
		if (signOutElem) {
			signOutElem.classList.remove("hidden");
		}
	}
}

// The googleOnSignIn amd googleSignOut functions need to be available to the global scope for Google code to invoke it
(window as any).googleOnSignIn = googleOnSignIn;
(window as any).googleSignOut = googleSignOut;

export const GoogleSignIn: Component = () => {
	return (
		<div>
			<div id="google-auth-sign-in" class="g-signin2" data-onsuccess="googleOnSignIn"></div>
			<a href="javascript:googleSignOut" id="google-auth-sign-out" class="hidden">
				Sign Out of Google Account
			</a>
		</div>
	);
};
