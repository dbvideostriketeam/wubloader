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
		if (googleUser) {
			submitData.token = googleUser.getAuthResponse().id_token;
		}

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

function generateTemplateDOM(index, template) {
	const { name, description, attribution, crop, location } = template;

	const editForm = document.createElement("form");
	editForm.id = `template-data-edit-form-${index}`;

	const nameCell = document.createElement("td");
	const nameReadCell = document.createElement("div");
	nameReadCell.classList.add("template-data-view");
	nameReadCell.innerText = name;
	const nameEditCell = document.createElement("div");
	nameEditCell.classList.add("template-data-edit", "hidden");
	const nameEditField = document.createElement("input");
	nameEditField.type = "text";
	nameEditField.name = "name";
	nameEditField.value = name;
	nameEditField.form = editForm.id;
	nameEditCell.appendChild(nameEditField);
	nameCell.appendChild(nameReadCell);
	nameCell.appendChild(nameEditCell);

	const descriptionCell = document.createElement("td");
	const descriptionReadCell = document.createElement("div");
	descriptionReadCell.classList.add("template-data-view");
	descriptionReadCell.innerText = description;
	const descriptionEditCell = document.createElement("div");
	descriptionEditCell.classList.add("template-data-edit", "hidden");
	const descriptionEditField = document.createElement("textarea");
	descriptionEditField.name = "description";
	descriptionEditField.value = description;
	descriptionEditField.form = editForm.id;
	descriptionEditCell.appendChild(descriptionEditField);
	descriptionCell.appendChild(descriptionReadCell);
	descriptionCell.appendChild(descriptionEditCell);

	const attributionCell = document.createElement("td");
	const attributionReadCell = document.createElement("div");
	attributionReadCell.classList.add("template-data-view");
	attributionReadCell.innerText = attribution;
	const attributionEditCell = document.createElement("div");
	attributionEditCell.classList.add("template-data-edit", "hidden");
	const attributionEditField = document.createElement("input");
	attributionEditField.type = "text";
	attributionEditField.name = "attribution";
	attributionEditField.value = attribution;
	attributionEditField.form = editForm.id;
	attributionEditCell.appendChild(attributionEditField);
	attributionCell.appendChild(attributionReadCell);
	attributionCell.appendChild(attributionEditCell);

	const cropCell = document.createElement("td");
	const cropReadCell = document.createElement("div");
	cropReadCell.classList.add("template-data-view");
	cropReadCell.innerText = `(${crop[0]}, ${crop[1]}) to (${crop[2]}, ${crop[3]})`;
	const cropEditCell = document.createElement("div");
	cropEditCell.classList.add("template-data-edit", "hidden");

	const cropXStartField = document.createElement("input");
	cropXStartField.name = "cropxstart";
	setCoordNumberFieldProps(cropXStartField, "X");
	cropXStartField.value = crop[0];
	cropXStartField.form = editForm.id;
	const cropYStartField = document.createElement("input");
	cropYStartField.name = "cropystart";
	setCoordNumberFieldProps(cropYStartField, "Y");
	cropYStartField.value = crop[1];
	cropYStartField.form = editForm.id;
	const cropXEndField = document.createElement("input");
	cropXEndField.name = "cropxend";
	setCoordNumberFieldProps(cropXEndField, "X");
	cropXEndField.value = crop[2];
	cropXEndField.form = editForm.id;
	const cropYEndField = document.createElement("input");
	cropYEndField.name = "cropyend";
	setCoordNumberFieldProps(cropYEndField, "Y");
	cropYEndField.value = crop[3];
	cropYEndField.form = editForm.id;

	cropEditCell.appendChild(document.createTextNode("("));
	cropEditCell.appendChild(cropXStartField);
	cropEditCell.appendChild(document.createTextNode(", "));
	cropEditCell.appendChild(cropYStartField);
	cropEditCell.appendChild(document.createTextNode(") to ("));
	cropEditCell.appendChild(cropXEndField);
	cropEditCell.appendChild(document.createTextNode(", "));
	cropEditCell.appendChild(cropYEndField);
	cropEditCell.appendChild(document.createTextNode(")"));

	cropCell.appendChild(cropReadCell);
	cropCell.appendChild(cropEditCell);

	const locationCell = document.createElement("td");
	const locationReadCell = document.createElement("div");
	locationReadCell.classList.add("template-data-view");
	locationReadCell.innerText = `(${location[0]}, ${location[1]}) to (${location[2]}, ${location[3]})`;
	const locationEditCell = document.createElement("div");
	locationEditCell.classList.add("template-data-edit", "hidden");

	const locationXStartField = document.createElement("input");
	locationXStartField.name = "locxstart";
	setCoordNumberFieldProps(locationXStartField, "X");
	locationXStartField.value = location[0];
	locationXStartField.form = editForm.id;
	const locationYStartField = document.createElement("input");
	locationYStartField.name = "locystart";
	setCoordNumberFieldProps(locationYStartField, "Y");
	locationYStartField.value = location[1];
	locationYStartField.form = editForm.id;
	const locationXEndField = document.createElement("input");
	locationXEndField.name = "locxend";
	setCoordNumberFieldProps(locationXEndField, "X");
	locationXEndField.value = location[2];
	locationXEndField.form = editForm.id;
	const locationYEndField = document.createElement("input");
	locationYEndField.name = "locyend";
	setCoordNumberFieldProps(locationYEndField, "Y");
	locationYEndField.value = location[3];
	locationYEndField.form = editForm.id;

	locationEditCell.appendChild(document.createTextNode("("));
	locationEditCell.appendChild(locationXStartField);
	locationEditCell.appendChild(document.createTextNode(", "));
	locationEditCell.appendChild(locationYStartField);
	locationEditCell.appendChild(document.createTextNode(") to ("));
	locationEditCell.appendChild(locationXEndField);
	locationEditCell.appendChild(document.createTextNode(", "));
	locationEditCell.appendChild(locationYEndField);
	locationEditCell.appendChild(document.createTextNode(")"));

	locationCell.appendChild(locationReadCell);
	locationCell.appendChild(locationEditCell);

	const previewCell = document.createElement("td");
	const previewReadCell = document.createElement("div");
	previewReadCell.id = `template-list-preview-${index}`;
	previewReadCell.classList.add("template-data-view");
	const previewLink = document.createElement("a");
	previewLink.href = `javascript:showPreview(${index})`;
	previewLink.innerText = "Preview";
	previewReadCell.appendChild(previewLink);
	const previewEditCell = document.createElement("div");
	previewEditCell.classList.add("template-data-edit", "hidden");
	const imageEditField = document.createElement("input");
	imageEditField.name = "image";
	imageEditField.type = "file";
	imageEditField.accept = "image/png";
	imageEditField.form = editForm.id;
	previewEditCell.appendChild(imageEditField);
	previewCell.appendChild(previewReadCell);
	previewCell.appendChild(previewEditCell);

	const editCell = document.createElement("td");
	const editReadCell = document.createElement("div");
	editReadCell.classList.add("template-data-view");
	const switchToEditButton = document.createElement("button");
	switchToEditButton.type = "button";
	switchToEditButton.innerText = "Edit";
	editReadCell.appendChild(switchToEditButton);
	const editEditCell = document.createElement("div");
	editEditCell.classList.add("template-data-edit", "hidden");
	const editSubmitButton = document.createElement("button");
	editSubmitButton.type = "submit";
	editSubmitButton.innerText = "Submit";
	const editErrors = document.createElement("ul");
	editErrors.id = `template-data-edit-errors-${index}`;
	editErrors.classList.add("template-data-edit-errors");
	editForm.appendChild(editSubmitButton);
	editForm.appendChild(editErrors);
	editEditCell.appendChild(editForm);
	editCell.appendChild(editReadCell);
	editCell.appendChild(editEditCell);

	const templateRow = document.createElement("tr");
	templateRow.id = `template-list-data-${index}`;
	templateRow.appendChild(nameCell);
	templateRow.appendChild(descriptionCell);
	templateRow.appendChild(attributionCell);
	templateRow.appendChild(cropCell);
	templateRow.appendChild(locationCell);
	templateRow.appendChild(previewCell);
	templateRow.appendChild(editCell);

	switchToEditButton.addEventListener("click", (event) => {
		for (const element of templateRow.getElementsByClassName("template-data-view")) {
			element.classList.add("hidden");
		}
		for (const element of templateRow.getElementsByClassName("template-data-edit")) {
			element.classList.remove("hidden");
		}
	});

	templateRow.addEventListener("submit", async (event) => {
		event.preventDefault();

		editErrors.innerHTML = "";

		const name = nameEditField.value;

		const description = descriptionEditField.value;
		const attribution = attributionEditField.value;

		const cropXStart = parseInt(cropXStartField.value, 10);
		const cropYStart = parseInt(cropYStartField.value, 10);
		const cropXEnd = parseInt(cropXEndField.value, 10);
		const cropYEnd = parseInt(cropYEndField.value, 10);
		const locXStart = parseInt(locationXStartField.value, 10);
		const locYStart = parseInt(locationYStartField.value, 10);
		const locXEnd = parseInt(locationXEndField.value, 10);
		const locYEnd = parseInt(locationYEndField.value, 10);

		if (
			isNaN(cropXStart) ||
			isNaN(cropYStart) ||
			isNaN(cropXEnd) ||
			isNaN(cropYEnd) ||
			isNaN(locXStart) ||
			isNaN(locXEnd) ||
			isNaN(locYStart) ||
			isNaN(locYEnd)
		) {
			const parseNumbersError = document.createElement("li");
			parseNumbersError.innerText = "All crop and location information must be entered";
			editErrors.appendChild(parseNumbersError);
		}

		const submitData = {
			name: name,
			description: description,
			attribution: attribution,
			crop: [cropXStart, cropYStart, cropXEnd, cropYEnd],
			location: [locXStart, locYStart, locXEnd, locYEnd],
		};

		const imageFiles = imageEditField.files;
		if (imageFiles.length > 0) {
			const fileReader = new FileReader();
			const fileReaderCompletePromise = new Promise((resolve, reject) => {
				fileReader.addEventListener("loadend", (event) => resolve());
			});
			fileReader.readAsDataURL(imageFile);
			await fileReaderCompletePromise;

			const imageDataURL = fileReader.result;
			if (imageDataURL.startsWith("data:image/png;base64,")) {
				submitData.image = imageDataURL.substring(22);
			} else {
				const imageError = document.createElement("li");
				imageError.innerText = "Failed to process image as PNG";
				editErrors.appendChild(imageError);
			}
		}
		if (googleUser) {
			submitData.token = googleUser.getAuthResponse().id_token;
		}

		if (editErrors.hasChildNodes()) {
			return;
		}

		const origName = templateData[index].name;
		const encodedName = encodeURIComponent(origName);
		const submitResponse = await fetch(`/thrimshim/update-template/${encodedName}`, {
			method: "POST",
			body: JSON.stringify(submitData),
			headers: { "Content-Type": "application/json" },
		});
		if (!submitResponse.ok) {
			const submitError = document.createElement("li");
			submitError.innerText = await submitResponse.text();
			editErrors.appendChild(submitError);
			return;
		}

		templateData[index].name = name;
		if (submitData.hasOwnProperty("image")) {
			templateData[index].image = submitData.image;
		}
		templateData[index].description = description;
		templateData[index].attribution = attribution;
		templateData[index].crop = submitData.crop;
		templateData[index].location = submitData.location;

		const templateDOM = generateTemplateDOM(index, templateData[index]);
		templateRow.replaceWith(templateDOM);
	});

	return templateRow;
}

function addTemplate(index, template) {
	const templateDOM = generateTemplateDOM(index, template);
	document.getElementById("template-list-data").appendChild(templateDOM);
}

function setCoordNumberFieldProps(field, direction) {
	field.type = "number";
	field.placeholder = direction;
	field.min = 0;
	field.step = 1;
	field.classList.add("template-coord");
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
