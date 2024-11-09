import "./globalStyle.scss";
import { render } from "solid-js/web";
import Editor from "./editor/Editor";

const root = document.getElementById("root");

render(() => <Editor />, root!);
