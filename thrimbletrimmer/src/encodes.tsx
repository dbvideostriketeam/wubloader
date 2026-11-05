import "./globalStyle.scss";
import { render } from "solid-js/web";
import { Encodes } from "./encodes/Encodes";

const root = document.getElementById("root");

render(() => <Encodes />, root!);
