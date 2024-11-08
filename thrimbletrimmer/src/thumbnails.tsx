import { render } from "solid-js/web";

import ThumbnailManager from "./thumbnails/ThumbnailManager";

const root = document.getElementById("root");

render(() => <ThumbnailManager />, root!);
