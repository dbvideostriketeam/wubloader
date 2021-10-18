function pageReady() {

    const params = new URLSearchParams(document.location.search.substring(1));
    line_id = parseInt(params.get("line"), 10);

    videojs("player", {
            // src: "test.m3u8",
            controls: true,
            autoplay: false,
            width: 900,
            height: 420,
            playbackRates: [0.5, 1, 1.25, 1.5, 2],
            inactivityTimeout: 0,
            controlBar: {
                fullscreenToggle: true,
                volumePanel: {
                    inline: false,
                },
            }
        },
        function () {
            this.src({src: `//localhost:8005/professor/line/${line_id}/playlist.m3u8`});
        });

    fetch(`//localhost:8005/professor/line/${line_id}`)
        .then(response => response.json())
        .then(fillLineInfo)

}

function fillLineInfo(line_json) {
    document.getElementById("original_transcription").innerText = line_json.line_data.text

}