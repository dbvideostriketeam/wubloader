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
const BUS_FRONT_OFFSET = 73;

// Start time of each day phase
const DAY_START_MINUTES = 450;
const DUSK_START_MINUTES = 1140;
const NIGHT_START_MINUTES = 1200;
const DAWN_START_MINUTES = 400;

const BUS_STOP_OFFSET = 6;
const POINT_OFFSET = 17;

// Bus stop positions are recorded in miles with the 0 position
// at route start. This array can be looped every point.
const BUS_STOP_POSITIONS = [1, 55.2, 125.4, 166.3, 233.9, 295.2];

// The default scaling factor is 20 seconds per pixel at max speed.
// This gives us
// - 3px per minute
// - 4px per mile
let scaleFactor = 1;

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

	context.fillStyle = COLORS[timeOfDay].sky;
	context.fillRect(leftX, 0, width, 100);
	context.fillStyle = COLORS[timeOfDay].surface;
	context.fillRect(leftX, 80, width, 1);
	context.fillStyle = COLORS[timeOfDay].ground;
	context.fillRect(leftX, 81, width, 7);
	context.fillRect(leftX, 89, width, 3);
	context.fillRect(leftX, 94, width, 2);
	context.fillRect(leftX, 99, width, 1);
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
	context.clearRect(0, 0, 1920, 100);

	const currentTime = busData.clock_minutes;
	const distance = busData.odometer;
	const timeOfDay = busData.timeofday;

	drawBackground(context, timeOfDay, 0, BUS_FRONT_OFFSET);

	const maxWidth = 1920 - BUS_FRONT_OFFSET;

	// TODO Figure out scaling factor
	const startMinute = busData.clock_minutes;
	const timeDuration = maxWidth / 3;

	let previousTime = startMinute;
	let previousTimeOfDay = timeOfDay;
	let remainingDuration = timeDuration;
	let x = BUS_FRONT_OFFSET;
	while (remainingDuration > 0) {
		const nextTimeOfDay = nextPhase(previousTimeOfDay);
		const nextStartTime = phaseStartTime(nextTimeOfDay);

		let thisDuration = nextStartTime - previousTime;
		if (thisDuration < 0) {
			thisDuration += 1440;
		}

		// TODO Figure out scaling factor
		const pixelWidth = thisDuration * 3;
		drawBackground(context, previousTimeOfDay, x, pixelWidth);

		remainingDuration -= thisDuration;
		previousTime = nextStartTime;
		previousTimeOfDay = nextTimeOfDay;
		x += pixelWidth;
	}

	x = BUS_FRONT_OFFSET;
	const currentPointProgress = distance % 360;
	let distanceToNextPoint;
	if (currentPointProgress <= 109.3) {
		distanceToNextPoint = 109.3 - currentPointProgress;
	} else {
		distanceToNextPoint = 469.3 - currentPointProgress;
	}

	// TODO Figure out scaling factor
	x += distanceToNextPoint * 4;
	const pointImage = new Image();
	pointImage.src = "point.png";
	context.drawImage(pointImage, x - POINT_OFFSET, 0);
	while (x < maxWidth) {
		// TODO Figure out scaling factor
		x += 360 * 4;
		context.drawImage(pointImage, x - POINT_OFFSET, 0);
	}

	const distanceOnRoute = (distance - 109.3) % 360;
	const busStopImage = new Image();
	busStopImage.src = "db_stop.png";
	// TODO Figure out scaling factor
	let distanceTracked = distanceOnRoute - BUS_FRONT_OFFSET / 4;
	if (distanceTracked < 0) {
		distanceTracked += 720;
	}
	x = 0;
	while (x < 1920) {
		const distanceTrackedOnRoute = distanceTracked % 360;
		let nextBusStopPosition = null;
		for (const busStopPosition of BUS_STOP_POSITIONS) {
			if (busStopPosition >= distanceTrackedOnRoute + 1) {
				nextBusStopPosition = busStopPosition;
				break;
			}
		}
		if (nextBusStopPosition === null) {
			nextBusStopPosition = 360 + BUS_STOP_POSITIONS[0];
		}
		const nextBusStopDistance = nextBusStopPosition - distanceTrackedOnRoute;
		distanceTracked += nextBusStopDistance;
		// TODO Figure out scaling factor
		x += nextBusStopDistance * 4;
		context.drawImage(busStopImage, x - BUS_STOP_OFFSET, 0);
	}

	const busImage = new Image();
	if (timeOfDay === "night") {
		busImage.src = "bus_night.png";
	} else {
		busImage.src = "bus_day.png";
	}
	context.drawImage(busImage, 0, 0);
}

window.addEventListener("DOMContentLoaded", (event) => {
	drawRoad();
	setInterval(drawRoad, 10000);
});
