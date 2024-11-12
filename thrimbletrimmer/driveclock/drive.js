
const PAGE_WIDTH = 1920;
const MINUTES_PER_PAGE = 60;
const POINT_WIDTH = PAGE_WIDTH * 8 * 60 / MINUTES_PER_PAGE;
const MILES_PER_PAGE = 45;
const BUS_POSITION_X = 93;
const BASE_ODO = 109.3;
const UPDATE_INTERVAL_MS = 5000
const WUBLOADER_URL = "";
const SKY_URLS = {
	day: "db_day.png",
	dawn: "db_dawn.png",
	dusk: "db_dusk.png",
	night: "db_night.png",
};
const BUS_URLS = {
	day: "bus_day.png",
	dawn: "bus_day.png",
	dusk: "bus_day.png",
	night: "bus_night.png",
};

function setSkyElements(left, right, timeToTransition) {
	const leftElement = document.getElementById("sky-left");
	const rightElement = document.getElementById("sky-right");
	const busElement = document.getElementById("bus");

	leftElement.style.backgroundImage = `url(${SKY_URLS[left]})`;
	rightElement.style.backgroundImage = `url(${SKY_URLS[right]})`;

	if (left === right) {
		leftElement.style.width = "100%";
	} else {
		const transitionPercent = timeToTransition / MINUTES_PER_PAGE;
		leftElement.style.width = `${transitionPercent * 100}%`
	}

	bus.style.backgroundImage = `url(${BUS_URLS[left]})`;
}

function nextSkyTransition(timeofday, clock) {
	switch (timeofday) {
		case "dawn":
		case "day":
			return [19 * 60, "dusk"]; // 7pm
		case "dusk":
			return [20 * 60, "night"]; // 8pm
		case "night":
			return [6 * 60 + 40, "dawn"]; // 6:40am
	}
}

function setSky(timeofday, clock) {
	const [transition, newSky] = nextSkyTransition(timeofday, clock);
	// 1440 minutes in 24h, this code will return time remaining even if
	// the transition is in the morning and we're currently in the evening.
	const timeToTransition = (1440 + transition - clock) % 1440;
	if (timeToTransition < MINUTES_PER_PAGE) {
		// Transition on screen
		setSkyElements(timeofday, newSky, timeToTransition);
	} else {
		// No transition on screen
		setSkyElements(timeofday, timeofday, undefined);
	}
}

function setOdo(odo) {
	const distancePixels = PAGE_WIDTH * (odo - BASE_ODO) / MILES_PER_PAGE;
	const offset = (BUS_POSITION_X - distancePixels) % POINT_WIDTH;

	const stopsElement = document.getElementById("stops");
	stopsElement.style.backgroundPosition = `${offset}px 0px`;
}

async function update() {
    const busDataResponse = await fetch(`${WUBLOADER_URL}/thrimshim/bus/buscam`);
    if (!busDataResponse.ok) {
        return;
    }
    const busData = await busDataResponse.json();
	console.log("Got data:", busData);
    setOdo(busData.odometer);
    setSky(busData.timeofday, busData.clock_minutes);
}

// Initial conditions, before the first refresh finishes
setSky("day", 7 * 60);
setOdo(BASE_ODO);

// Testing mode. Set true to enable.
const test = false;
if (test) {
	let h = 0;
	// Set to how long 1h of in-game time should take in real time
	const hourTimeMs = 1 * 1000;
	// Set to how often to update the screen
	const interval = 30;
	setInterval(() => {
		h += interval / hourTimeMs;
		setOdo(BASE_ODO + 45 * h);
		if (h < 19) {
			setSky("day", 60 * h);
		} else {
			m = (h % 24) * 60;
			let tod;
			if (m < 6 * 60 + 40) {
				tod = "night";
			} else if (m < 19 * 60) {
				tod = "dawn";
			} else if (m < 20 * 60) {
				tod = "dusk";
			} else {
				tod = "night";
			}
			setSky(tod, m);
		}
	}, interval);
} else {
	setInterval(update, UPDATE_INTERVAL_MS);
}
