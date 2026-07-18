import { Component, createEffect, createResource, createSignal } from "solid-js";
import { createIntervalCounter } from "@solid-primitives/timer";
import { bindingInputChecked, bindingInputNumberOnChange } from "../common/binding";
import styles from "./DriveClock.module.scss";

import BusDayImageUrl from "../assets/driveclock/bus_day.png";
import BusNightImageUrl from "../assets/driveclock/bus_night.png";
import BusStopImageUrl from "../assets/driveclock/db_stop.png";
import TucsonImageUrl from "../assets/driveclock/tucson.png";
import VegasImageUrl from "../assets/driveclock/vegas.png";

enum DayPhase {
	DAY = "day",
	DUSK = "dusk",
	NIGHT = "night",
	DAWN = "dawn",
}

interface BusData {
	// The web endpoint includes a "clock" property that we don't care about or use.
	clock_minutes: number | null;
	odometer: number | null;
	timeofday: DayPhase | null;
}

const COLORS = {
	day: {
		sky: "#41cee2",
		ground: "#e5931b",
		surface: "#b77616",
	},
	dusk: {
		sky: "#db92be",
		ground: "#dd926a",
		surface: "#b17555",
	},
	night: {
		sky: "#121336",
		ground: "#30201a",
		surface: "#261a15",
	},
	dawn: {
		sky: "#2b2f87",
		ground: "#724d41",
		surface: "#5b3e34",
	},
};

// The width from the left side of the bus image to the front of the bus
const BUS_FRONT_OFFSET = 72;

// Start time of each day phase
const DAY_START_MINUTES = 450;
const DUSK_START_MINUTES = 1140;
const NIGHT_START_MINUTES = 1200;
const DAWN_START_MINUTES = 400;

const BUS_STOP_OFFSET = 8;

// Bus stop positions are recorded in miles with the 0 position
// at route start. This array can be looped every point.
const BUS_STOP_POSITIONS = [1, 55.2, 125.4, 166.3, 233.9, 295.2];

const BUS_DAY_IMAGE = new Image();
BUS_DAY_IMAGE.src = BusDayImageUrl;
const BUS_NIGHT_IMAGE = new Image();
BUS_NIGHT_IMAGE.src = BusNightImageUrl;
const BUS_STOP_IMAGE = new Image();
BUS_STOP_IMAGE.src = BusStopImageUrl;
const VEGAS = {
	image: new Image(),
	offset: 12,
};
VEGAS.image.src = VegasImageUrl;
const TUCSON = {
	image: new Image(),
	offset: 32,
};
TUCSON.image.src = TucsonImageUrl;

const CANVAS_PIXEL_WIDTH = 1580;
const CANVAS_PIXEL_HEIGHT = 62;

const BUS_TRAVEL_WIDTH = CANVAS_PIXEL_WIDTH - BUS_FRONT_OFFSET;
const PIXELS_PER_MILE = BUS_TRAVEL_WIDTH / 360;
const PIXELS_PER_MINUTE = BUS_TRAVEL_WIDTH / 480;

const nextPhase = (timeOfDay: DayPhase): DayPhase => {
	switch (timeOfDay) {
		case DayPhase.DAY:
		case DayPhase.DAWN:
			return DayPhase.DUSK;
		case DayPhase.DUSK:
			return DayPhase.NIGHT;
		case DayPhase.NIGHT:
			return DayPhase.DAWN;
	}
};

const phaseStartTime = (timeOfDay: DayPhase): number => {
	switch (timeOfDay) {
		case DayPhase.DAY:
			return DAY_START_MINUTES;
		case DayPhase.DUSK:
			return DUSK_START_MINUTES;
		case DayPhase.NIGHT:
			return NIGHT_START_MINUTES;
		case DayPhase.DAWN:
			return DAWN_START_MINUTES;
	}
};

const drawBackground = (
	context: CanvasRenderingContext2D,
	timeOfDay: DayPhase,
	leftX: number,
	width: number,
) => {
	const colorSet = COLORS[timeOfDay];
	const skyColor = colorSet.sky;
	const groundColor = colorSet.ground;
	const surfaceColor = colorSet.surface;

	const renderWidth = Math.ceil(width);
	const renderLeftX = Math.floor(leftX);

	context.fillStyle = skyColor;
	context.fillRect(renderLeftX, 0, renderWidth, 56);
	context.fillStyle = surfaceColor;
	context.fillRect(renderLeftX, 56, renderWidth, 1);
	context.fillStyle = groundColor;
	context.fillRect(renderLeftX, 57, width, 5);
};

export const DriveClock: Component = () => {
	let busCanvas!: HTMLCanvasElement;
	const [scale, setScale] = createSignal(1);
	const [pointProgressMode, setPointProgressMode] = createSignal(false);
	const reloadTimer = createIntervalCounter(2500);

	const [busData, busDataActions] = createResource(async () => {
		const pageQueryParams = new URLSearchParams(window.location.search);
		if (
			pageQueryParams.has("odometer") ||
			pageQueryParams.has("clock_minutes") ||
			pageQueryParams.has("timeofday")
		) {
			return {
				odometer: parseFloat(pageQueryParams.get("odometer") ?? "109.3"), // default odo start position
				clock_minutes: parseFloat(pageQueryParams.get("clock_minutes") ?? "450"), // default 7:30AM
				timeofday: pageQueryParams.get("timeofday") ?? "day",
			} as BusData;
		}
		const response = await fetch("/thrimshim/bus/buscam");
		const data: BusData = await response.json();
		return data;
	});

	createEffect(() => {
		reloadTimer(); // Track this so it runs on interval
		busDataActions.refetch();
	});

	// We also want to update once when all images have been loaded
	createEffect(async () => {
		const images = [BUS_DAY_IMAGE, BUS_NIGHT_IMAGE, BUS_STOP_IMAGE, TUCSON.image, VEGAS.image];
		await Promise.all(
			images.map(
				(image) =>
					new Promise<void>((resolve) => image.addEventListener("load", (event) => resolve())),
			),
		);
		busDataActions.refetch();
	});

	createEffect(() => {
		const renderData = busData();
		let renderScale = scale();
		const usePointProgressMode = pointProgressMode();

		if (!renderData) {
			return;
		}
		if (
			renderData.odometer === null ||
			renderData.clock_minutes === null ||
			renderData.timeofday === null
		) {
			return;
		}

		const context = busCanvas.getContext("2d");
		if (!context) {
			return;
		}
		context.clearRect(0, 0, CANVAS_PIXEL_WIDTH, CANVAS_PIXEL_HEIGHT);

		if (usePointProgressMode) {
			const busDistance = (renderData.odometer + 250.7) % 360;
			const busDistancePixels = busDistance * PIXELS_PER_MILE;
			let x = busDistancePixels + BUS_FRONT_OFFSET;
			drawBackground(context, renderData.timeofday, 0, x);

			let currentTimeOfDay = renderData.timeofday;
			let currentTime = renderData.clock_minutes;
			while (x < CANVAS_PIXEL_WIDTH) {
				const nextTimeOfDay = nextPhase(currentTimeOfDay);
				const nextStartTime = phaseStartTime(nextTimeOfDay);

				let thisDuration = nextStartTime - currentTime;
				if (thisDuration < 0) {
					thisDuration += 1440;
				}

				const pixelWidth = thisDuration * PIXELS_PER_MINUTE;
				drawBackground(context, currentTimeOfDay, x, pixelWidth);
				x += pixelWidth;
				currentTimeOfDay = nextTimeOfDay;
				currentTime += thisDuration;
			}

			for (const busStopDistance of BUS_STOP_POSITIONS) {
				const busStopPixelPosition =
					BUS_FRONT_OFFSET + PIXELS_PER_MILE * busStopDistance - BUS_STOP_OFFSET;
				context.drawImage(BUS_STOP_IMAGE, busStopPixelPosition, 16);
			}

			if (renderData.timeofday === DayPhase.NIGHT) {
				context.drawImage(BUS_NIGHT_IMAGE, busDistancePixels, 32);
			} else {
				context.drawImage(BUS_DAY_IMAGE, busDistancePixels, 32);
			}
		} else {
			const distance = renderData.odometer - 109.3;
			const timeOfDay = renderData.timeofday;

			drawBackground(context, timeOfDay, 0, BUS_FRONT_OFFSET);

			// The default scaling factor (1) is 20 seconds per pixel at max speed.
			// This gives us
			// - 3px per minute
			// - 4px per mile
			if (renderScale === 0 || isNaN(renderScale)) {
				renderScale = 1;
			}

			const startMinute = renderData.clock_minutes;

			let previousTime = startMinute;
			let previousTimeOfDay = timeOfDay;
			let x = BUS_FRONT_OFFSET;
			while (x < CANVAS_PIXEL_WIDTH) {
				const nextTimeOfDay = nextPhase(previousTimeOfDay);
				const nextStartTime = phaseStartTime(nextTimeOfDay);

				let thisDuration = nextStartTime - previousTime;
				if (thisDuration < 0) {
					thisDuration += 1440;
				}

				const pixelWidth = thisDuration * 3 * renderScale;
				drawBackground(context, previousTimeOfDay, x, pixelWidth);

				previousTime = nextStartTime;
				previousTimeOfDay = nextTimeOfDay;
				x += pixelWidth;
			}

			x = 0;
			let currentPointProgress = distance % 360;
			let currentPoint = Math.floor(distance / 360);
			if (currentPointProgress < 0) {
				currentPointProgress += 360;
			}
			let distanceToNextPoint = 360 - currentPointProgress;

			distanceToNextPoint += BUS_FRONT_OFFSET / (4 * renderScale);
			if (distanceToNextPoint >= 360) {
				distanceToNextPoint -= 360;
				currentPoint -= 1;
			}

			x += distanceToNextPoint * 4 * renderScale;
			const pointImage = currentPoint % 2 === 0 ? VEGAS : TUCSON;
			context.drawImage(pointImage.image, x - pointImage.offset, 0);
			while (x < CANVAS_PIXEL_WIDTH) {
				x += 360 * 4 * renderScale;
				currentPoint += 1;
				const pointImage = currentPoint % 2 === 0 ? VEGAS : TUCSON;
				context.drawImage(pointImage.image, x - pointImage.offset, 0);
			}

			let distanceTracked = currentPointProgress - BUS_FRONT_OFFSET / (4 * renderScale);
			if (distanceTracked < 0) {
				distanceTracked += 720;
			}

			x = 0;
			while (x < CANVAS_PIXEL_WIDTH) {
				const distanceTrackedOnRoute = distanceTracked % 360;
				let nextBusStopPosition: number | null = null;
				for (const busStopPosition of BUS_STOP_POSITIONS) {
					if (busStopPosition >= distanceTrackedOnRoute + 0.05) {
						nextBusStopPosition = busStopPosition;
						break;
					}
				}
				if (nextBusStopPosition === null) {
					nextBusStopPosition = 360 + BUS_STOP_POSITIONS[0];
				}
				const nextBusStopDistance = nextBusStopPosition - distanceTrackedOnRoute;
				distanceTracked += nextBusStopDistance;
				x += nextBusStopDistance * 4 * renderScale;
				context.drawImage(BUS_STOP_IMAGE, x - BUS_STOP_OFFSET, 16);
			}

			if (timeOfDay === DayPhase.NIGHT) {
				context.drawImage(BUS_NIGHT_IMAGE, 0, 32);
			} else {
				context.drawImage(BUS_DAY_IMAGE, 0, 32);
			}
		}
	});

	return (
		<>
			<canvas ref={busCanvas} width={CANVAS_PIXEL_WIDTH} height={CANVAS_PIXEL_HEIGHT} />
			<label class={styles.scaleSetting}>
				Scale:
				<input
					type="number"
					use:bindingInputNumberOnChange={[scale, setScale]}
					min="0.1"
					step="0.1"
				/>
			</label>
			<label>
				<input type="checkbox" />
				Point Progress Mode
			</label>
			<p class={styles.settingsDisclaimer}>The scale setting is ignored in Point Progress Mode.</p>
		</>
	);
};
