import "./globalStyle.scss";
import { render } from "solid-js/web";
import { DriveClock } from "./driveclock/DriveClock";

const root = document.getElementById("root");

render(() => <DriveClock />, root!);
