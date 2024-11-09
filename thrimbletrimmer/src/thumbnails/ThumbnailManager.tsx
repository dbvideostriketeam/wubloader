import { Accessor, Component, createSignal, For, Index, onMount, Setter, Show } from "solid-js";
import { GoogleSignIn, googleUser } from "../common/googleAuth";
import styles from "./ThumbnailManager.module.scss";

class Coordinate {
	x: number;
	y: number;
}

class Template {
	name: string;
	description: string;
	attribution: string;
	cropStart: Coordinate;
	cropEnd: Coordinate;
	locationStart: Coordinate;
	locationEnd: Coordinate;
}

const ThumbnailManager: Component = () => {
	const [templates, setTemplates] = createSignal<Template[]>([]);
	const [newTemplateErrors, setNewTemplateErrors] = createSignal<string[]>([]);

	onMount(async () => {
		const templateDataResponse = await fetch("/thrimshim/templates");
		if (!templateDataResponse.ok) {
			return;
		}
		const templateData = await templateDataResponse.json();
		const templateList: Template[] = [];
		for (const template of templateData) {
			const cropStart = { x: template.crop[0], y: template.crop[1] };
			const cropEnd = { x: template.crop[2], y: template.crop[3] };
			const locationStart = { x: template.location[0], y: template.location[1] };
			const locationEnd = { x: template.location[2], y: template.location[3] };

			templateList.push({
				name: template.name,
				description: template.description,
				attribution: template.attribution,
				cropStart: cropStart,
				cropEnd: cropEnd,
				locationStart: locationStart,
				locationEnd: locationEnd
			});
		}
		setTemplates(templateList);
	});

	const submitHandler = async (origName: string, noImageIsError: boolean, errorList: Accessor<string[]>, setErrorList: Setter<string[]>, event: SubmitEvent): Promise<Template | null> => {
		setErrorList([]);

		const form = event.currentTarget as HTMLFormElement;
		const formData = new FormData(form);

		const name = formData.get("name") as string;
		const description = formData.get("description") as string;
		const attribution = formData.get("attribution") as string;

		const cropStartX = parseInt(formData.get("cropstartx") as string, 10);
		const cropStartY = parseInt(formData.get("cropstarty") as string, 10);
		const cropEndX = parseInt(formData.get("cropendx") as string, 10);
		const cropEndY = parseInt(formData.get("cropendy") as string, 10);

		const locStartX = parseInt(formData.get("locstartx") as string, 10);
		const locStartY = parseInt(formData.get("locstarty") as string, 10);
		const locEndX = parseInt(formData.get("locendx") as string, 10);
		const locEndY = parseInt(formData.get("locendy") as string, 10);

		if (isNaN(cropStartX) || isNaN(cropStartY) || isNaN(cropEndX) || isNaN(cropEndY) || isNaN(locStartX) || isNaN(locStartY) || isNaN(locEndX) || isNaN(locEndY)) {
			setErrorList((errors) => {
				errors.push("All crop and location information must be entered.");
				return errors;
			});
		}

		const imageFile = formData.get("image") as Blob;
		const fileReader = new FileReader();
		const fileReaderCompletePromise = new Promise<void>((resolve, reject) => {
			fileReader.addEventListener("loadend", (event) => resolve());
		});
		fileReader.readAsDataURL(imageFile);

		await fileReaderCompletePromise;

		const submitData = new Map();
		submitData.set("name", name);
		submitData.set("description", description);
		submitData.set("attribution", attribution);
		submitData.set("crop", [cropStartX, cropStartY, cropEndX, cropEndY]);
		submitData.set("location", [locStartX, locStartY, locEndX, locEndY]);

		const imageDataURL = fileReader.result as string;
		if (imageDataURL.startsWith("data:image/png;base64,")) {
			submitData.set("image", imageDataURL.substring(22));
		} else if (noImageIsError) {
			setErrorList((errors) => {
				errors.push("A PNG image must be selected.");
				return errors;
			});
		}

		if (googleUser) {
			submitData.set("token", googleUser.getAuthResponse().id_token);
		}

		if (errorList().length > 0) {
			return null;
		}

		const submitURL = (origName === "") ? "/thrimshim/add-template" : `/thrimshim/update-template/${encodeURIComponent(origName)}`;
		const submitDataJSON = JSON.stringify(Object.fromEntries(submitData));
		const submitResponse = await fetch(submitURL, {
			method: "POST",
			body: submitDataJSON,
			headers: { "Content-Type": "application/json" }
		});
		if (!submitResponse.ok) {
			const errorText = await submitResponse.text();
			setErrorList((errors) => {
				errors.push(errorText);
				return errors;
			});
		}

		form.reset();

		return {
			name: name,
			description: description,
			attribution: attribution,
			cropStart: { x: cropStartX, y: cropStartY },
			cropEnd: { x: cropEndX, y: cropEndY },
			locationStart: { x: locStartX, y: locStartY },
			locationEnd: { x: locEndX, y: locEndY }
		};
	};

	return (
		<>
			<div class={styles.templatesList}>
				<div class={`${styles.templatesListRow} ${styles.templatesListHeader}`}>
					<div>Name</div>
					<div>Description</div>
					<div>Attribution</div>
					<div>Crop Coordinates</div>
					<div>Location Coordinates</div>
					<div>Preview</div>
					<div></div>
				</div>
				<Index each={templates()}>
					{(template: Accessor<Template>, index: number) => {
						const [formErrors, setFormErrors] = createSignal<string[]>([]);
						const [displayImagePreview, setDisplayImagePreview] = createSignal(false);
						const [editing, setEditing] = createSignal(false);

						return (
							<form
								class={styles.templatesListRow}
								onSubmit={async (event) => {
									const submitData = await submitHandler(template().name, false, formErrors, setFormErrors, event);
									if (submitData) {
										setTemplates((templateList) => {
											templateList[index] = submitData;
											return templateList;
										});
									}
								}}
							>
								<Show
									when={editing()}
									fallback={
										<>
											<div>{template().name}</div>
											<div>{template().description}</div>
											<div>{template().attribution}</div>
											<div>
												({template().cropStart.x}, {template().cropStart.y})
												to
												({template().cropEnd.x}, {template().cropEnd.y})
											</div>
											<div>
												({template().locationStart.x}, {template().locationStart.y})
												to
												({template().locationEnd.x}, {template().locationEnd.y})
											</div>
											<div>
												<Show
													when={displayImagePreview()}
													fallback={
														<a
															href="#"
															onClick={
																(event) => setDisplayImagePreview(true)
															}
														>
															Preview
														</a>
													}
												>
													<img class={styles.templateImagePreview} src={`/thrimshim/template/${encodeURIComponent(template().name)}.png`} />
												</Show>
											</div>
											<div>
												<button
													type="button"
													onClick={
														(event) => setEditing(true)
													}
												>
													Edit
												</button>
											</div>
										</>
									}
								>
									<>
										<div>
											<input type="text" name="name" value={template().name} />
										</div>
										<div>
											<textarea name="description">{template().description}</textarea>
										</div>
										<div>
											<input type="text" name="attribution" value={template().attribution} />
										</div>
										<div>
											(
											<input type="number" name="cropstartx" placeholder="X" min={0} step={1} class={styles.templateCoord} value={template().cropStart.x} />
											,
											<input type="number" name="cropstarty" placeholder="Y" min={0} step={1} class={styles.templateCoord} value={template().cropStart.y} />
											)
											<br />
											(
											<input type="number" name="cropendx" placeholder="X" min={0} step={1} class={styles.templateCoord} value={template().cropEnd.x} />
											,
											<input type="number" name="cropendy" placeholder="Y" min={0} step={1} class={styles.templateCoord} value={template().cropEnd.y} />
											)
										</div>
										<div>
											(
											<input type="number" name="locstartx" placeholder="X" min={0} step={1} class={styles.templateCoord} value={template().locationStart.x} />
											,
											<input type="number" name="locstarty" placeholder="Y" min={0} step={1} class={styles.templateCoord} value={template().locationStart.y} />
											)
											<br />
											(
											<input type="number" name="locendx" placeholder="X" min={0} step={1} class={styles.templateCoord} value={template().locationEnd.x} />
											,
											<input type="number" name="locendy" placeholder="Y" min={0} step={1} class={styles.templateCoord} value={template().locationEnd.y} />
											)
										</div>
										<div>
											<input type="file" name="image" accept="image/png" />
										</div>
										<div>
											<button type="submit">Submit</button>
											<ul class={styles.templateUpdateErrors}>
												<For each={formErrors()}>
													{(error: string, index: Accessor<number>) => <li>{error}</li>}
												</For>
											</ul>
										</div>
									</>
								</Show>
							</form>
						);
					}}
				</Index>
			</div>
			<form
				onSubmit={async (event) => {
					const submitData = await submitHandler("", true, newTemplateErrors, setNewTemplateErrors, event);
					if (submitData) {
						setTemplates((templateList) => [...templateList, submitData]);
					}
				}}
			>
				<h1>Add New Template</h1>
				<ul class={styles.templateUpdateErrors}>
					<For each={newTemplateErrors()}>
						{(error: string, index: Accessor<number>) => <li>{error}</li>}
					</For>
				</ul>
				<div class={styles.newTemplateFormFields}>
					<label class={styles.newTemplateFieldLabelContainer}>
						<span>Name:</span>
						<input type="text" name="name" />
					</label>
					<label class={styles.newTemplateFieldLabelContainer}>
						<span>Image:</span>
						<input type="file" name="image" accept="image/png" />
					</label>
					<label class={styles.newTemplateFieldLabelContainer}>
						<span>Description:</span>
						<textarea name="description"></textarea>
					</label>
					<label class={styles.newTemplateFieldLabelContainer}>
						<span>Attribution:</span>
						<input type="text" name="attribution" />
					</label>
					<span>Crop:</span>
					<span>
						<input
							type="number"
							class={styles.templateCoord}
							name="cropstartx"
							placeholder="X"
							min={0}
							step={1}
							value={182}
						/>
						<input
							type="number"
							class={styles.templateCoord}
							name="cropstarty"
							placeholder="Y"
							min={0}
							step={1}
							value={0}
						/>
						<span class={styles.newTemplateMidText}>to</span>
						<input
							type="number"
							class={styles.templateCoord}
							name="cropendx"
							placeholder="X"
							min={0}
							step={1}
							value={1738}
						/>
						<input
							type="number"
							class={styles.templateCoord}
							name="cropendy"
							placeholder="Y"
							min={0}
							step={1}
							value={824}
						/>
					</span>
					<span class={styles.newTemplateInlineLabel}>Location:</span>
					<span>
						<input
							type="number"
							class={styles.templateCoord}
							name="locstartx"
							placeholder="X"
							min={0}
							step={1}
							value={45}
						/>
						<input
							type="number"
							class={styles.templateCoord}
							name="locstarty"
							placeholder="Y"
							min={0}
							step={1}
							value={45}
						/>
						<span class={styles.newTemplateMidText}>to</span>
						<input
							type="number"
							class={styles.templateCoord}
							name="locendx"
							placeholder="X"
							min={0}
							step={1}
							value={1235}
						/>
						<input
							type="number"
							class={styles.templateCoord}
							name="locendy"
							placeholder="Y"
							min={0}
							step={1}
							value={675}
						/>
					</span>
				</div>
				<button type="submit">Add Template</button>
			</form>
			<GoogleSignIn />
		</>
	);
};

export default ThumbnailManager;
