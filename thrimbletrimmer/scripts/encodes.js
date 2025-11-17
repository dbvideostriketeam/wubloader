let googleUser = null;

function googleOnSignIn(googleUserData) {
	googleUser = googleUserData;
	const signInElem = document.getElementById("google-auth-sign-in");
	const signOutElem = document.getElementById("google-auth-sign-out");
	signInElem.classList.add("hidden");
	signOutElem.classList.remove("hidden");
	loadTable();
}

async function googleSignOut() {
	if (googleUser) {
		googleUser = null;
		await gapi.auth2.getAuthInstance().signOut();
		const signInElem = document.getElementById("google-auth-sign-in");
		const signOutElem = document.getElementById("google-auth-sign-out");
		signInElem.classList.remove("hidden");
		signOutElem.classList.add("hidden");
	}
}

async function loadTable() {
	document.getElementById("google-auth-sign-out").addEventListener("click", (_event) => {
		googleSignOut();
	});

	const encodesResponse = await postJson("/thrimshim/encodes", {});
	if (!encodesResponse.ok) {
		return;
	}
	encodes = await encodesResponse.json();

	const table = document.getElementById("list-data");
	for (const encode of encodes) {
		const tr = document.createElement("tr");

		for (key of ["src_url", "src_hash", "encode_args", "dest_url"]) {
			const td = document.createElement("td");
			if (key === "encode_args") {
				td.innerText = encode[key].join(" ");
			} else {
				td.innerText = encode[key];
			}
			tr.appendChild(td);
		}

		const claimCell = document.createElement("td");
		if (encode.claimed_by === null) {
			const claimButton = document.createElement("button");
			claimButton.innerText = "Claim";
			claimButton.addEventListener("click", async (_event) => {
				await postJson("/thrimshim/encodes/claim", { dest_url: encode.dest_url });
				location.reload();
			});
			claimCell.appendChild(claimButton);
		} else {
			claimCell.innerText = encode.claimed_by;
		}
		tr.appendChild(claimCell);

		const submitCell = document.createElement("td");
		if (encode.dest_hash === null) {
			const hashText = document.createElement("input");
			hashText.type = "text";
			hashText.placeholder = "Dest Hash";
			const submitButton = document.createElement("button");
			submitButton.innerText = "Submit";
			submitButton.addEventListener("click", async (_event) => {
				await postJson("/thrimshim/encodes/submit", {
					dest_url: encode.dest_url,
					dest_hash: hashText.value,
				});
				location.reload();
			});
			submitCell.appendChild(hashText);
			submitCell.appendChild(submitButton);
		} else {
			submitCell.innerText = encode.dest_hash;
		}
		tr.appendChild(submitCell);

		table.appendChild(tr);
	}
};

function postJson(url, data) {
	if (googleUser) {
		data.token = googleUser.getAuthResponse().id_token;
	}

	return fetch(url, {
		method: "POST",
		body: JSON.stringify(data),
		headers: { "Content-Type": "application/json" },
	});
}
