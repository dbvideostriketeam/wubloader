import "./globalStyle.scss";
import { render } from "solid-js/web";
import { Challenges } from "./challenges/Challenges";

const root = document.getElementById("root");

render(() => <Challenges />, root!);
