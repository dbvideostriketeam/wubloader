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
const POINT_OFFSET = 17;

// Bus stop positions are recorded in miles with the 0 position
// at route start. This array can be looped every point.
const BUS_STOP_POSITIONS = [1, 55.2, 125.4, 166.3, 233.9, 295.2];

const BUS_DAY_IMAGE = new Image();
BUS_DAY_IMAGE.src = "bus_day.png";
const BUS_NIGHT_IMAGE = new Image();
BUS_NIGHT_IMAGE.src = "bus_night.png";
const BUS_STOP_IMAGE = new Image();
BUS_STOP_IMAGE.src = "db_stop.png";
const VEGAS = {
	image: new Image(),
	offset: 12,
};
VEGAS.image.src = "vegas.png";
const TUCSON = {
	image: new Image(),
	offset: 32,
};
TUCSON.image.src = "tucson.png";

// This should match the HTML canvas width
const CANVAS_PIXEL_WIDTH = 1580;

const BUS_TRAVEL_WIDTH = CANVAS_PIXEL_WIDTH - BUS_FRONT_OFFSET;
const PIXELS_PER_MILE = BUS_TRAVEL_WIDTH / 360;
const PIXELS_PER_MINUTE = BUS_TRAVEL_WIDTH / 480;
const FULL_SPEED_MILES_PER_MINUTE = 0.75;

function nextPhase(timeOfDay) {
	switch (timeOfDay) {
		case "day":
		case "dawn":
			return "dusk";
		case "dusk":
			return "night";
		case "night":
			return "dawn";
	}
}

function phaseStartTime(timeOfDay) {
	switch (timeOfDay) {
		case "day":
			return DAY_START_MINUTES;
		case "dusk":
			return DUSK_START_MINUTES;
		case "night":
			return NIGHT_START_MINUTES;
		case "dawn":
			return DAWN_START_MINUTES;
	}
}

function drawBackground(context, timeOfDay, leftX, width) {
	const skyColor = COLORS[timeOfDay].sky;
	const groundColor = COLORS[timeOfDay].ground;
	const surfaceColor = COLORS[timeOfDay].surface;

	width = Math.ceil(width);
	leftX = Math.floor(leftX);

	context.fillStyle = COLORS[timeOfDay].sky;
	context.fillRect(leftX, 0, width, 56);
	context.fillStyle = COLORS[timeOfDay].surface;
	context.fillRect(leftX, 56, width, 1);
	context.fillStyle = COLORS[timeOfDay].ground;
	context.fillRect(leftX, 57, width, 5);
}

async function drawRoad() {
	const busDataResponse = await fetch("/thrimshim/bus/buscam");
	if (!busDataResponse.ok) {
		return;
	}
	const busData = await busDataResponse.json();

	const canvas = document.getElementById("road");
	if (!canvas.getContext) {
		return;
	}
	const context = canvas.getContext("2d");

	// Clear the previous canvas before starting
	context.clearRect(0, 0, CANVAS_PIXEL_WIDTH, 62);

	const pointModeCheckbox = document.getElementById("point-progress-checkbox");
	if (pointModeCheckbox.checked) {
		drawRoadPoint(context, busData);
	} else {
		drawRoadDynamic(context, busData);
	}
}

function drawRoadPoint(context, busData) {
	const busDistance = (busData.odometer + 250.7) % 360;
	const busNextPoint = Math.floor((busData.odometer + 250.7) / 360);
	const busRemainingDistance = 360 - busDistance;
	const busRemainingDistancePixels = busRemainingDistance * PIXELS_PER_MILE;

	const busDistancePixels = busDistance * PIXELS_PER_MILE;
	let x = busDistancePixels + BUS_FRONT_OFFSET;
	drawBackground(context, busData.timeofday, 0, x);
	let currentTimeOfDay = busData.timeofday;
	let currentTime = busData.clock_minutes;
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

	const pointImage = (busNextPoint % 2 == 1) ? VEGAS : TUCSON;
	context.drawImage(pointImage.image, CANVAS_PIXEL_WIDTH - pointImage.offset, 0);

	for (const busStopDistance of BUS_STOP_POSITIONS) {
		const busStopPixelPosition =
			BUS_FRONT_OFFSET + PIXELS_PER_MILE * busStopDistance - BUS_STOP_OFFSET;
		context.drawImage(BUS_STOP_IMAGE, busStopPixelPosition, 16);
	}

	if (busData.timeofday === "night") {
		context.drawImage(BUS_NIGHT_IMAGE, busDistancePixels, 32);
	} else {
		context.drawImage(BUS_DAY_IMAGE, busDistancePixels, 32);
	}
}

function drawRoadDynamic(context, busData) {
	const distance = busData.odometer - 109.3;
	const timeOfDay = busData.timeofday;

	drawBackground(context, timeOfDay, 0, BUS_FRONT_OFFSET);

	// The default scaling factor (1) is 20 seconds per pixel at max speed.
	// This gives us
	// - 3px per minute
	// - 4px per mile
	let scaleFactor = +document.getElementById("scale-input").value;
	if (scaleFactor === 0 || isNaN(scaleFactor)) {
		scaleFactor = 1;
	}

	const startMinute = busData.clock_minutes;

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

		const pixelWidth = thisDuration * 3 * scaleFactor;
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

	distanceToNextPoint += BUS_FRONT_OFFSET / (4 * scaleFactor);
	if (distanceToNextPoint >= 360) {
		distanceToNextPoint -= 360;
		currentPoint -= 1;
	}

	x += distanceToNextPoint * 4 * scaleFactor;
	const pointImage = (currentPoint % 2 == 0) ? VEGAS : TUCSON;
	context.drawImage(pointImage.image, x - pointImage.offset, 0);
	while (x < CANVAS_PIXEL_WIDTH) {
		x += 360 * 4 * scaleFactor;
		currentPoint += 1;
		const pointImage = (currentPoint % 2 == 0) ? VEGAS : TUCSON;
		context.drawImage(pointImage.image, x - pointImage.offset, 0);
	}

	let distanceTracked = currentPointProgress - BUS_FRONT_OFFSET / (4 * scaleFactor);
	if (distanceTracked < 0) {
		distanceTracked += 720;
	}
	x = 0;
	while (x < CANVAS_PIXEL_WIDTH) {
		const distanceTrackedOnRoute = distanceTracked % 360;
		let nextBusStopPosition = null;
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
		x += nextBusStopDistance * 4 * scaleFactor;
		context.drawImage(BUS_STOP_IMAGE, x - BUS_STOP_OFFSET, 16);
	}

	if (timeOfDay === "night") {
		context.drawImage(BUS_NIGHT_IMAGE, 0, 32);
	} else {
		context.drawImage(BUS_DAY_IMAGE, 0, 32);
	}
}

window.addEventListener("DOMContentLoaded", (event) => {
	drawRoad();
	setInterval(drawRoad, 2500);
});
