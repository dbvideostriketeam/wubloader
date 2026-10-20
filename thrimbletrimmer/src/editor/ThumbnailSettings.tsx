import { Accessor, Component, createEffect, createSignal, For, on, Show, untrack } from "solid-js";
import { MediaPlayerElement } from "vidstack/elements";
import {
	displayTimeForVideoPlayerTime,
	FragmentTimes,
	ThumbnailData,
	ThumbnailTemplateDefinition,
	ThumbnailType,
	videoPlayerTimeForDisplayTime,
	videoPlayerTimeFromDateTime,
} from "./common";
import {
	bindingInputChecked,
	bindingInputOnChange,
	bindingInputPositiveNumberOnChange,
	bindingInputPositiveNumberOrZeroOnChange,
} from "../common/binding";
import { StreamVideoInfo } from "../common/streamInfo";
import { BASE64_PNG_PREFIX, BASE64_PNG_PREFIX_LENGTH } from "../common/thumbnails";
import styles from "./ThumbnailSettings.module.scss";

import PencilIcon from "../assets/pencil.png";
import PlayToIcon from "../assets/play_to.png";
import { dateTimeFromVideoPlayerTime, wubloaderTimeFromDateTime } from "../common/convertTime";

import "cropperjs"; // This is required for Cropper.js to work, even with the specific import below
import { CropperSelection } from "cropperjs";

interface ThumbnailSettingsProps {
	allThumbnailTemplates: ThumbnailTemplateDefinition[];
	thumbnailData: ThumbnailData;
	streamInfo: Accessor<StreamVideoInfo>;
	videoFragments: Accessor<FragmentTimes[]>;
	videoPlayerTime: Accessor<number>;
	videoPlayer: Accessor<MediaPlayerElement>;
}

export const ThumbnailSettings: Component<ThumbnailSettingsProps> = (props) => {
	const setThumbnailType = (event) => {
		const value = (event.currentTarget as HTMLSelectElement).value as ThumbnailType;
		props.thumbnailData.setType(value);
	};
	const setThumbnailTemplate = (event) => {
		const value = (event.currentTarget as HTMLSelectElement).value;
		if (value === "") {
			props.thumbnailData.setTemplate(null);
		} else {
			props.thumbnailData.setTemplate(value);
		}
	};

	const [thumbnailTimeEntry, setThumbnailTimeEntry] = createSignal("");

	createEffect(() => {
		const thumbnailTime = props.thumbnailData.time();
		const fragments = props.videoFragments();
		if (fragments.length === 0) {
			return;
		}
		if (thumbnailTime === null) {
			setThumbnailTimeEntry("");
			return;
		}
		const playerTime = videoPlayerTimeFromDateTime(thumbnailTime, fragments);
		if (playerTime === null) {
			setThumbnailTimeEntry("");
			return;
		}
		const entryTime = displayTimeForVideoPlayerTime(playerTime);
		setThumbnailTimeEntry(entryTime);
	});

	createEffect(() => {
		const enteredTime = thumbnailTimeEntry();
		const fragments = props.videoFragments();
		if (fragments.length === 0) {
			return;
		}
		if (enteredTime === "") {
			props.thumbnailData.setTime(null);
			return;
		}
		const playerTime = videoPlayerTimeForDisplayTime(enteredTime);
		const thumbnailTime = dateTimeFromVideoPlayerTime(playerTime, fragments);
		props.thumbnailData.setTime(thumbnailTime);
	});

	const setThumbnailTime = (event) => {
		const playerTime = props.videoPlayerTime();
		const entryTime = displayTimeForVideoPlayerTime(playerTime);
		setThumbnailTimeEntry(entryTime);
	};

	const setPlayerTimeToThumbnailTime = (event) => {
		const enteredTime = thumbnailTimeEntry();
		const playerTime = videoPlayerTimeForDisplayTime(enteredTime);
		props.videoPlayer().currentTime = playerTime;
	};

	const [thumbnailUploadError, setThumbnailUploadError] = createSignal<string | null>(null);
	const customThumbnailChange = async (event) => {
		const fileElement = event.currentTarget as HTMLInputElement;
		const imageData = await getUploadedImageAsBase64(fileElement);
		setThumbnailUploadError(imageData.error);
		if (!imageData.error) {
			props.thumbnailData.setImage(imageData.base64Contents);
		}
	};

	const [showAdvancedThumbnailControls, setShowAdvancedThumbnailControls] = createSignal(false);
	const toggleAdvancedThumbnailControls = () => {
		setShowAdvancedThumbnailControls(!showAdvancedThumbnailControls());
	};
	const canShowCropTools = () => {
		return (
			props.thumbnailData.time() !== null &&
			(props.thumbnailData.type() === ThumbnailType.Template ||
				(props.thumbnailData.type() === ThumbnailType.CustomTemplate &&
					props.thumbnailData.image() !== null))
		);
	};

	const cropBaseImageURL = () => {
		const imageTime = props.thumbnailData.time();
		if (imageTime === null) {
			return "";
		}
		const queryParams = new URLSearchParams({ timestamp: wubloaderTimeFromDateTime(imageTime) });
		return `/frame/${props.streamInfo().streamName}/source.png?${queryParams.toString()}`;
	};
	const locBaseImageURL = () => {
		switch (props.thumbnailData.type()) {
			case ThumbnailType.Template:
				const templateName = props.thumbnailData.template();
				if (templateName === null) {
					return "";
				}
				return `/thrimshim/template/${templateName}.png`;
			case ThumbnailType.CustomTemplate:
				const imageData = props.thumbnailData.image();
				if (imageData === null) {
					return "";
				}
				return `${BASE64_PNG_PREFIX}${imageData}`;
			default:
				return "";
		}
	};

	const ASPECT_RATIO = 1920 / 1080;
	const CROPPABLE_SCREENGRAB_WIDTH = 1920;
	const CROPPABLE_SCREENGRAB_HEIGHT = CROPPABLE_SCREENGRAB_WIDTH / ASPECT_RATIO;
	const TEMPLATE_WIDTH = 1280;
	const TEMPLATE_HEIGHT = TEMPLATE_WIDTH / ASPECT_RATIO;
	const CROPPER_CANVAS_WIDTH = 640;
	const CROPPER_CANVAS_HEIGHT = CROPPER_CANVAS_WIDTH / ASPECT_RATIO;
	const CROP_SCALE_FACTOR = CROPPABLE_SCREENGRAB_WIDTH / CROPPER_CANVAS_WIDTH;
	const LOCATION_SCALE_FACTOR = TEMPLATE_WIDTH / CROPPER_CANVAS_WIDTH;
	let cropSelection: CropperSelection | undefined;
	let locationSelection: CropperSelection | undefined;
	const onCropSelectionChange = (event) => {
		const newSelection: { x: number; y: number; width: number; height: number } = event.detail;

		const minX = Math.round(newSelection.x * CROP_SCALE_FACTOR);
		const minY = Math.round(newSelection.y * CROP_SCALE_FACTOR);
		const maxX = Math.round((newSelection.x + newSelection.width) * CROP_SCALE_FACTOR);
		const maxY = Math.round((newSelection.y + newSelection.height) * CROP_SCALE_FACTOR);

		props.thumbnailData.setCrop([minX, minY, maxX, maxY]);
	};

	const onLocSelectionChange = (event) => {
		const newSelection: { x: number; y: number; width: number; height: number } = event.detail;

		const minX = Math.round(newSelection.x * LOCATION_SCALE_FACTOR);
		const minY = Math.round(newSelection.y * LOCATION_SCALE_FACTOR);
		const maxX = Math.round((newSelection.x + newSelection.width) * LOCATION_SCALE_FACTOR);
		const maxY = Math.round((newSelection.y + newSelection.height) * LOCATION_SCALE_FACTOR);

		props.thumbnailData.setLocation([minX, minY, maxX, maxY]);
	};

	const [cropX, setCropX] = createSignal(0);
	const [cropY, setCropY] = createSignal(0);
	const [cropWidth, setCropWidth] = createSignal(CROPPABLE_SCREENGRAB_WIDTH);
	const [cropHeight, setCropHeight] = createSignal(CROPPABLE_SCREENGRAB_HEIGHT);

	createEffect(() => {
		const crop = props.thumbnailData.crop();
		if (crop === null) {
			return;
		}
		if (
			untrack(cropX) === crop[0] &&
			untrack(cropY) === crop[1] &&
			untrack(cropWidth) === crop[2] - crop[0] &&
			untrack(cropHeight) === crop[3] - crop[1]
		) {
			return;
		}

		setCropX(crop[0]);
		setCropY(crop[1]);
		setCropWidth(crop[2] - crop[0]);
		setCropHeight(crop[3] - crop[1]);
	});

	createEffect(() => {
		const minX = Math.round(cropX());
		const minY = Math.round(cropY());
		const maxX = Math.round(cropX() + cropWidth());
		const maxY = Math.round(cropY() + cropHeight());

		const currentCrop = untrack(props.thumbnailData.crop);

		if (
			currentCrop === null ||
			minX !== currentCrop[0] ||
			minY !== currentCrop[1] ||
			maxX !== currentCrop[0] + currentCrop[2] ||
			maxY !== currentCrop[1] + currentCrop[3]
		) {
			props.thumbnailData.setCrop([minX, minY, maxX, maxY]);
		}
	});

	const [locX, setLocX] = createSignal(0);
	const [locY, setLocY] = createSignal(0);
	const [locWidth, setLocWidth] = createSignal(TEMPLATE_WIDTH);
	const [locHeight, setLocHeight] = createSignal(TEMPLATE_HEIGHT);

	createEffect(() => {
		const location = props.thumbnailData.location();
		if (location === null) {
			return;
		}
		if (
			untrack(locX) === location[0] &&
			untrack(locY) === location[1] &&
			untrack(locWidth) === location[2] - location[0] &&
			untrack(locHeight) === location[3] - location[1]
		) {
			return;
		}

		setLocX(location[0]);
		setLocY(location[1]);
		setLocWidth(location[2] - location[0]);
		setLocHeight(location[3] - location[1]);
	});

	createEffect(() => {
		const minX = Math.round(locX());
		const minY = Math.round(locY());
		const maxX = Math.round(locX() + locWidth());
		const maxY = Math.round(locY() + locHeight());

		const currentLoc = untrack(props.thumbnailData.location);

		if (
			currentLoc === null ||
			minX != currentLoc[0] ||
			minY != currentLoc[1] ||
			maxX != currentLoc[0] + currentLoc[2] ||
			maxY !== currentLoc[1] + currentLoc[3]
		) {
			props.thumbnailData.setLocation([minX, minY, maxX, maxY]);
		}
	});

	const [aspectRatioLocked, setAspectRatioLocked] = createSignal(true);

	const matchCropAspectRatioToLocation = (event) => {
		const cropAspectRatio = cropWidth() / cropHeight();
		const locationAspectRatio = locWidth() / locHeight();
		if (aspectRatioLocked()) {
			cropSelection!.aspectRatio = locationAspectRatio;
		}
		if (locationAspectRatio > cropAspectRatio) {
			setCropHeight(cropWidth() / locationAspectRatio);
		} else {
			setCropWidth(cropHeight() * locationAspectRatio);
		}
	};

	const matchLocationAspectRatioToCrop = (event) => {
		const locationAspectRatio = locWidth() / locHeight();
		const cropAspectRatio = cropWidth() / cropHeight();
		if (aspectRatioLocked()) {
			locationSelection!.aspectRatio = cropAspectRatio;
		}
		if (cropAspectRatio > locationAspectRatio) {
			setLocHeight(locWidth() / cropAspectRatio);
		} else {
			setLocWidth(locHeight() * cropAspectRatio);
		}
	};

	createEffect(() => {
		const ratioLocked = aspectRatioLocked();
		if (!showAdvancedThumbnailControls()) {
			// If this isn't set, neither cropper exists yet, so neither will be able
			// to be updated. Both should get this set when starting to display (the Show
			// Advanced Thumbnail Controls button).
			return;
		}

		if (ratioLocked) {
			if (cropSelection) {
				const cropAspectRatio = untrack(cropWidth) / untrack(cropHeight);
				cropSelection.aspectRatio = cropAspectRatio;
			}
			if (locationSelection) {
				const locationAspectRatio = untrack(locWidth) / untrack(locHeight);
				locationSelection.aspectRatio = locationAspectRatio;
			}
		} else {
			if (cropSelection) {
				cropSelection.aspectRatio = NaN;
			}
			if (locationSelection) {
				locationSelection.aspectRatio = NaN;
			}
		}
	});

	let previewCanvas: HTMLCanvasElement | undefined;
	createEffect(
		on(
			[
				canShowCropTools,
				cropBaseImageURL,
				locBaseImageURL,
				cropX,
				cropY,
				cropWidth,
				cropHeight,
				locX,
				locY,
				locWidth,
				locHeight,
			],
			(values) => {
				const canShowCropTools = values[0];
				if (!canShowCropTools || !previewCanvas) {
					return;
				}

				const canvasContext = previewCanvas.getContext("2d");
				if (!canvasContext) {
					return;
				}

				const cropURL = values[1];
				const locURL = values[2];
				if (!cropURL || !locURL) {
					canvasContext.reset();
					return;
				}

				const cropImage = new Image();
				const templateImage = new Image(TEMPLATE_WIDTH, TEMPLATE_HEIGHT);
				cropImage.src = cropURL;
				templateImage.src = locURL;

				const renderPreview = () => {
					canvasContext.reset();
					canvasContext.scale(0.25, 0.25); // The scaling used here is relative to a base size of 1280x720.
					canvasContext.drawImage(
						cropImage,
						cropX(),
						cropY(),
						cropWidth(),
						cropHeight(),
						locX(),
						locY(),
						locWidth(),
						locHeight(),
					);
					canvasContext.drawImage(templateImage, 0, 0);
				};

				let cropLoaded = false;
				let templateLoaded = false;
				cropImage.addEventListener("load", (event) => {
					cropLoaded = true;
					if (templateLoaded) {
						renderPreview();
					}
				});
				templateImage.addEventListener("load", (event) => {
					templateLoaded = true;
					if (cropLoaded) {
						renderPreview();
					}
				});
			},
		),
	);

	return (
		<div>
			<div class={styles.thumbnailLabel}>Thumbnail:</div>
			<div class={styles.firstThumbnailRow}>
				<select value={props.thumbnailData.type()} onChange={setThumbnailType}>
					<option value={ThumbnailType.None}>No custom thumbnail</option>
					<option value={ThumbnailType.Frame}>Use video frame</option>
					<option value={ThumbnailType.Template}>Use video frame in image template</option>
					<option value={ThumbnailType.CustomTemplate}>
						Use video frame with a custom one-off overlay
					</option>
					<option value={ThumbnailType.CustomThumbnail}>Use a custom thumbnail image</option>
				</select>
				<Show when={props.thumbnailData.type() === ThumbnailType.Template}>
					<select value={props.thumbnailData.template() ?? ""} onChange={setThumbnailTemplate}>
						<For each={props.allThumbnailTemplates}>
							{(template: ThumbnailTemplateDefinition) => (
								<option
									value={template.name}
									title={template.description}
									selected={template.name === (props.thumbnailData.template() ?? "")}
								>
									{template.name}
								</option>
							)}
						</For>
					</select>
				</Show>
				<Show
					when={
						props.thumbnailData.type() === ThumbnailType.Frame ||
						props.thumbnailData.type() === ThumbnailType.Template ||
						props.thumbnailData.type() === ThumbnailType.CustomTemplate
					}
				>
					<div class={styles.timeRangeEntry}>
						<div class={styles.timeRangeSelect}>
							<input
								class={styles.timeEntry}
								use:bindingInputOnChange={[thumbnailTimeEntry, setThumbnailTimeEntry]}
							/>
						</div>
						<div class={styles.timeRangeIcon}>
							<img
								class={styles.clickable}
								src={PencilIcon}
								alt="Set thumbnail time to current video time"
								title="Set thumbnail time to current video time"
								onClick={setThumbnailTime}
							/>
						</div>
						<div class={styles.timeRangeIcon}>
							<img
								class={styles.clickable}
								src={PlayToIcon}
								alt="Play from the thumbnail time"
								title="Play from the thumbnail time"
								onClick={setPlayerTimeToThumbnailTime}
							/>
						</div>
					</div>
				</Show>
			</div>
			<div>
				<Show
					when={
						props.thumbnailData.type() === ThumbnailType.CustomTemplate ||
						props.thumbnailData.type() === ThumbnailType.CustomThumbnail
					}
				>
					<input type="file" onChange={customThumbnailChange} />
				</Show>
			</div>
			<Show when={thumbnailUploadError() !== null}>
				<div class={styles.uploadError}>{thumbnailUploadError()}</div>
			</Show>
			<div class={styles.cropOptions}>
				<Show when={canShowCropTools()}>
					<button type="button" onClick={toggleAdvancedThumbnailControls}>
						<Show
							when={showAdvancedThumbnailControls()}
							fallback="Show Advanced Thumbnail Controls"
						>
							Hide Advanced Thumbnail Controls
						</Show>
					</button>
					<Show when={showAdvancedThumbnailControls()}>
						<button type="button" onClick={matchCropAspectRatioToLocation}>
							Match Crop Aspect Ratio to Location
						</button>
						<button type="button" onClick={matchLocationAspectRatioToCrop}>
							Match Location Aspect Ratio to Crop
						</button>
						<label>
							<input
								type="checkbox"
								use:bindingInputChecked={[aspectRatioLocked, setAspectRatioLocked]}
							/>
							Lock Aspect Ratio
						</label>
					</Show>
				</Show>
			</div>
			<Show when={canShowCropTools() && showAdvancedThumbnailControls()}>
				<div>
					<span class={styles.cropCoordinatesLabel}>Image crop coordinates:</span>
					<input
						type="number"
						min={0}
						step={1}
						placeholder="x"
						title="Starting X"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOrZeroOnChange={[cropX, setCropX]}
					/>
					<input
						type="number"
						min={0}
						step={1}
						placeholder="y"
						title="Starting Y"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOrZeroOnChange={[cropY, setCropY]}
					/>
					<input
						type="number"
						min={1}
						step={1}
						placeholder="w"
						title="Crop width"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOnChange={[cropWidth, setCropWidth]}
					/>
					<input
						type="number"
						min={1}
						step={1}
						placeholder="h"
						title="Crop height"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOnChange={[cropHeight, setCropHeight]}
					/>
				</div>
				<div>
					<span class={styles.cropCoordinatesLabel}>Template location coordinates:</span>
					<input
						type="number"
						min={0}
						step={1}
						placeholder="x"
						title="Starting X"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOrZeroOnChange={[locX, setLocX]}
					/>
					<input
						type="number"
						min={0}
						step={1}
						placeholder="y"
						title="Starting y"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOrZeroOnChange={[locY, setLocY]}
					/>
					<input
						type="number"
						min={1}
						step={1}
						placeholder="w"
						title="Location width"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOnChange={[locWidth, setLocWidth]}
					/>
					<input
						type="number"
						min={1}
						step={1}
						placeholder="h"
						title="Location height"
						class={styles.thumbnailCoordinateInput}
						use:bindingInputPositiveNumberOnChange={[locHeight, setLocHeight]}
					/>
				</div>
			</Show>
			<div class={styles.croppers}>
				<Show when={canShowCropTools() && showAdvancedThumbnailControls()}>
					<cropper-canvas class={styles.cropper}>
						<cropper-image src={cropBaseImageURL()} />
						<cropper-shade />
						<cropper-handle action="select" plain />
						<cropper-selection
							x={cropX() / CROP_SCALE_FACTOR}
							y={cropY() / CROP_SCALE_FACTOR}
							width={cropWidth() / CROP_SCALE_FACTOR}
							height={cropHeight() / CROP_SCALE_FACTOR}
							min-inset="0"
							precise
							movable
							resizable
							outlined
							ref={cropSelection}
							onChange={onCropSelectionChange}
						>
							<cropper-grid covered />
							<cropper-crosshair centered />
							<cropper-handle action="move" />
							<cropper-handle action="n-resize" />
							<cropper-handle action="e-resize" />
							<cropper-handle action="s-resize" />
							<cropper-handle action="w-resize" />
							<cropper-handle action="nw-resize" />
							<cropper-handle action="ne-resize" />
							<cropper-handle action="se-resize" />
							<cropper-handle action="sw-resize" />
						</cropper-selection>
					</cropper-canvas>
				</Show>
				<Show when={canShowCropTools() && showAdvancedThumbnailControls()}>
					<cropper-canvas class={styles.cropper}>
						<cropper-image src={locBaseImageURL()} />
						<cropper-shade />
						<cropper-handle action="select" plain />
						<cropper-selection
							x={locX() / LOCATION_SCALE_FACTOR}
							y={locY() / LOCATION_SCALE_FACTOR}
							width={locWidth() / LOCATION_SCALE_FACTOR}
							height={locHeight() / LOCATION_SCALE_FACTOR}
							min-inset="0"
							precise
							movable
							resizable
							outlined
							ref={locationSelection}
							onChange={onLocSelectionChange}
						>
							<cropper-grid covered />
							<cropper-crosshair centered />
							<cropper-handle action="move" />
							<cropper-handle action="n-resize" />
							<cropper-handle action="e-resize" />
							<cropper-handle action="s-resize" />
							<cropper-handle action="w-resize" />
							<cropper-handle action="nw-resize" />
							<cropper-handle action="ne-resize" />
							<cropper-handle action="se-resize" />
							<cropper-handle action="sw-resize" />
						</cropper-selection>
					</cropper-canvas>
				</Show>
			</div>
			<Show when={canShowCropTools()}>
				<div>
					<canvas width={320} height={180} ref={previewCanvas}></canvas>
				</div>
			</Show>
		</div>
	);
};

class UploadedImageData {
	base64Contents: string | null;
	error: string | null;
}

function uploadedImageDataFromFileData(base64Contents: string | null): UploadedImageData {
	return {
		base64Contents: base64Contents,
		error: null,
	};
}

function uploadedImageDataFromErrorMessage(error: string): UploadedImageData {
	return {
		base64Contents: null,
		error: error,
	};
}

async function getUploadedImageAsBase64(fileElement: HTMLInputElement): Promise<UploadedImageData> {
	if (!fileElement.files) {
		return uploadedImageDataFromErrorMessage("Not a file upload field");
	}
	if (fileElement.files.length === 0) {
		return uploadedImageDataFromFileData(null);
	}

	const fileHandle = fileElement.files[0];
	if (fileHandle.size > 50 * 1048576) {
		return uploadedImageDataFromErrorMessage("Uploaded file is too large (limit: 50MB)");
	}
	const fileReader = new FileReader();

	let loadPromiseResolve: (value: void) => void;
	const loadPromise = new Promise((resolve, reject) => {
		loadPromiseResolve = resolve;
	});
	fileReader.addEventListener("loadend", (event) => {
		loadPromiseResolve();
	});
	fileReader.readAsDataURL(fileHandle);
	await loadPromise;

	const fileLoadData = fileReader.result as string;
	if (fileLoadData.substring(0, BASE64_PNG_PREFIX_LENGTH) !== BASE64_PNG_PREFIX) {
		return uploadedImageDataFromErrorMessage("Uploaded file isn't a PNG image");
	}
	return uploadedImageDataFromFileData(fileLoadData.substring(BASE64_PNG_PREFIX_LENGTH));
}
