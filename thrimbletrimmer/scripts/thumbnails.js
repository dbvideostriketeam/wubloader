let viewingTemplate = null;
let googleUser = null;
let templateData = [];

function googleOnSignIn(googleUserData) {
	googleUser = googleUserData;
	const signInElem = document.getElementById("google-auth-sign-in");
	const signOutElem = document.getElementById("google-auth-sign-out");
	signInElem.classList.add("hidden");
	signOutElem.classList.remove("hidden");
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

window.addEventListener("DOMContentLoaded", async (event) => {
	document.getElementById("template-new-form").addEventListener("submit", async (event) => {
		event.preventDefault();

		const errorListContainer = document.getElementById("template-new-errors");
		errorListContainer.innerHTML = "";

		const form = document.getElementById("template-new-form");
		const formData = new FormData(form);

		const name = formData.get("name");

		const imageFile = formData.get("image");
		const fileReader = new FileReader();
		const fileReaderCompletePromise = new Promise((resolve, reject) => {
			fileReader.addEventListener("loadend", (event) => resolve());
		});
		fileReader.readAsDataURL(imageFile);

		const description = formData.get("description");
		const attribution = formData.get("attribution");

		const cropXStart = parseInt(formData.get("cropxstart"), 10);
		const cropYStart = parseInt(formData.get("cropystart"), 10);
		const cropXEnd = parseInt(formData.get("cropxend"), 10);
		const cropYEnd = parseInt(formData.get("cropyend"), 10);

		const locXStart = parseInt(formData.get("locxstart"), 10);
		const locYStart = parseInt(formData.get("locystart"), 10);
		const locXEnd = parseInt(formData.get("locxend"), 10);
		const locYEnd = parseInt(formData.get("locyend"), 10);

		if (
			isNaN(cropXStart) ||
			isNaN(cropYStart) ||
			isNaN(cropXEnd) ||
			isNaN(cropYEnd) ||
			isNaN(locXStart) ||
			isNaN(locYStart) ||
			isNaN(locXEnd) ||
			isNaN(locYEnd)
		) {
			const parseNumbersError = document.createElement("li");
			parseNumbersError.innerText = "All crop and location information must be entered";
			errorListContainer.appendChild(parseNumbersError);
		}

		await fileReaderCompletePromise;

		const imageDataURL = fileReader.result;
		if (!imageDataURL.startsWith("data:image/png;base64,")) {
			const imageReadError = document.createElement("li");
			imageReadError.innerText = "Couldn't read the image data, or the image wasn't a valid PNG";
			errorListContainer.appendChild(imageReadError);
			return;
		}
		const image = imageDataURL.substring(22);

		const submitData = {
			name: name,
			image: image,
			description: description,
			attribution: attribution,
			crop: [cropXStart, cropYStart, cropXEnd, cropYEnd],
			location: [locXStart, locYStart, locXEnd, locYEnd],
		};

		if (!errorListContainer.hasChildNodes()) {
			const submitResponse = await fetch("/thrimshim/add-template", {
				method: "POST",
				body: JSON.stringify(submitData),
				headers: { "Content-Type": "application/json" },
			});
			if (!submitResponse.ok) {
				const submitError = document.createElement("li");
				submitError.innerText = await submitResponse.text();
				errorListContainer.appendChild(submitError);
				return;
			}

			addTemplate(templateData.length, submitData);
			templateData.push(submitData);

			form.reset();
		}
	});

	document.getElementById("google-auth-sign-out").addEventListener("click", (_event) => {
		googleSignOut();
	});

	const templateDataResponse = await fetch("/thrimshim/templates");
	if (!templateDataResponse.ok) {
		return;
	}
	templateData = await templateDataResponse.json();

	for (const [index, template] of templateData.entries()) {
		addTemplate(index, template);
	}
});

function addTemplate(index, template) {
	const { name, description, attribution, crop, location } = template;

	const nameCell = document.createElement("td");
	nameCell.innerText = name;
	const descriptionCell = document.createElement("td");
	descriptionCell.innerText = description;
	const attributionCell = document.createElement("td");
	attributionCell.innerText = attribution;
	const cropCell = document.createElement("td");
	cropCell.innerText = `(${crop[0]}, ${crop[1]}) to (${crop[2]}, ${crop[3]})`;
	const locationCell = document.createElement("td");
	locationCell.innerText = `(${location[0]}, ${location[1]}) to (${location[2]}, ${location[3]})`;
	const previewCell = document.createElement("td");
	const previewLink = document.createElement("a");
	previewLink.href = `javascript:showPreview(${index})`;
	previewLink.innerText = "Preview";
	previewCell.appendChild(previewLink);
	previewCell.id = `template-list-preview-${index}`;

	const templateRow = document.createElement("tr");
	templateRow.appendChild(nameCell);
	templateRow.appendChild(descriptionCell);
	templateRow.appendChild(attributionCell);
	templateRow.appendChild(cropCell);
	templateRow.appendChild(locationCell);
	templateRow.appendChild(previewCell);

	document.getElementById("template-list-data").appendChild(templateRow);
}

function showPreview(index) {
	const template = templateData[index];
	const previewCell = document.getElementById(`template-list-preview-${index}`);
	if (!previewCell) {
		return;
	}

	const previewContents = document.createElement("img");
	previewContents.classList.add("template-list-preview");
	previewContents.src = `/thrimshim/template/${template.name}.png`;

	previewCell.innerHTML = "";
	previewCell.appendChild(previewContents);
}
