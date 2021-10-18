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
        },
        sources: [{src: `//localhost:8005/professor/line/${line_id}/playlist.m3u8`}]
    });

    fetch(`//localhost:8005/professor/line/${line_id}`)
        .then(response => response.json())
        .then(fillLineInfo);

}

function fillLineInfo(line_json) {
    // document.getElementById("original_transcription").innerText = line_json.line_data.text;
    document.getElementById("original_transcription").innerHTML = line_json.line_data.result
        .map(word => `<span style="opacity: ${word.conf}">${word.word}</span>`).join(" ");
    document.getElementById("new_transcription")
        .attributes.getNamedItem("placeholder").value = line_json.line_data.text;
}

async function submit() {
    const new_transcription = document.getElementById("new_transcription").value;
    const new_speakers = await Promise.all(document.getElementById("speaker_input").value
        .split(",")
        .filter(x => x !== "")
        .map(speaker_raw => speaker_raw.trim())
        .map(async function (speaker) {
            for (const speaker_json of speakers) {
                if (speaker_json.name === speaker) {
                    return speaker_json.id
                }
            }

            return await fetch("//localhost:8005/professor/speaker",
                {
                    method: "PUT",
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(speaker)
                }).then(response =>
                parseInt(response.headers.get("Content-Location")
                    .split("/")
                    .pop(), 10));
        }));

    fetch(`//localhost:8005/professor/line/${line_id}`,
        {
            method: "POST",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({transcription: new_transcription, speakers: new_speakers})
        })
}

$(function () {
    fetch("//localhost:8005/professor/speaker")
        .then(response => response.json())
        .then(function (speakers_json) {
            speakers = speakers_json;
            speaker_names = speakers_json.map(x => x.name)
        })
        .then(function () {
                function split(val) {
                    return val.split(/,\s*/);
                }

                function extractLast(term) {
                    return split(term).pop();
                }

                $("#speaker_input")
                    // don't navigate away from the field on tab when selecting an item
                    .on("keydown", function (event) {
                        if (event.keyCode === $.ui.keyCode.TAB &&
                            $(this).autocomplete("instance").menu.active) {
                            event.preventDefault();
                        }
                    })
                    .autocomplete({
                        minLength: 0,
                        source: function (request, response) {
                            // delegate back to autocomplete, but extract the last term
                            response($.ui.autocomplete.filter(
                                speaker_names, extractLast(request.term)));
                        },
                        focus: function () {
                            // prevent value inserted on focus
                            return false;
                        },
                        select: function (event, ui) {
                            var terms = split(this.value);
                            // remove the current input
                            terms.pop();
                            // add the selected item
                            terms.push(ui.item.value);
                            // add placeholder to get the comma-and-space at the end
                            terms.push("");
                            this.value = terms.join(", ");
                            return false;
                        }
                    });
            }
        )

});