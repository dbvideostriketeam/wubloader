let googleUser = null;

function googleOnSignIn(googleUserData) {
	googleUser = googleUserData;
	const signInElem = document.getElementById("google-auth-sign-in");
	const signOutElem = document.getElementById("google-auth-sign-out");
	signInElem.style.display = "none";
	signOutElem.style.display = "block";
}

async function googleSignOut() {
	if (googleUser) {
		googleUser = null;
		await gapi.auth2.getAuthInstance().signOut();
		const signInElem = document.getElementById("google-auth-sign-in");
		const signOutElem = document.getElementById("google-auth-sign-out");
		signInElem.style.display = "block";
		signOutElem.style.display = "none";
	}
}

window.addEventListener("DOMContentLoaded", async (event) => {
	const challengesResponse = await fetch("/thrimshim/challenges");
	if (!challengesResponse.ok) {
		const errorElement = document.createElement("div");
		errorElement.style.color = "#c00";
		errorElement.innerText = "Failed to get challenges data.";
		document.body.appendChild(errorElement);
		return;
	}

	const challengesData = await challengesResponse.json();

	const challengesTable = document.getElementById("challenges");

	for (const challenge of challengesData) {
		const messageDiv = document.createElement("div");
		const urlEntry = document.createElement("input");
		const submitButton = document.createElement("button");

		urlEntry.type = "text";
		urlEntry.name = "url";
		urlEntry.value = challenge.vstURL ? challenge.vstURL : "";
		submitButton.type = "submit";
		submitButton.innerText = "Submit";

		const urlForm = document.createElement("form");
		urlForm.addEventListener("submit", async (event) => {
			event.preventDefault();

			const formData = new FormData(event.currentTarget);
			const url = formData.get("url");
			if (!url.startsWith("https://www.youtube.com/watch") || !url.startsWith("https://youtube.com/watch") || !url.startsWith("https://youtu.be/")) {
				messageDiv.style.color = "#c00";
				messageDiv.innerText = "That doesn't seem to be a YouTube link.";
				return;
			}

			let authToken;
			if (googleUser) {
				authToken = googleUser.getAuthResponse().id_token;
			} else {
				messageDiv.style.color = "#c00";
				messageDiv.innerText = "You're not logged in.";
				return;
			}

			const submitResponse = await fetch(`/thrimshim/challenges/${challenge.id}`, {
				method: "POST",
				headers: {
					Accept: "application/json",
					"Content-Type": "application/json"
				},
				body: JSON.stringify({
					token: authToken,
					url: url
				})
			});
			if (submitResponse.ok) {
				messageDiv.style.color = "#0c0";
				messageDiv.innerText = "Updated successfully.";
			} else {
				messageDiv.style.color = "#c00";
				messageDiv.innerText = "Error during submission";
			}
		});

		const descriptionCell = document.createElement("td");
		descriptionCell.innerText = challenge.description;

		const updateCell = document.createElement("td");
		updateCell.appendChild(urlForm);

		const row = document.createElement("tr");
		challengesTable.appendChild(row);
	}
});
