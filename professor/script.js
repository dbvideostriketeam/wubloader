function pageReady() {

    const params = new URLSearchParams(document.location.search.substring(1));
    let line_id;
    if (params.get("line") !== "random") {
        line_id = parseInt(params.get("line"), 10);
    } else {
        line_id = "random"
    }


    videojs("player", {
        // src: "test.m3u8",
        controls: true,
        autoplay: false,
        width: 900,
        height: 900 / 16 * 9,
        playbackRates: [0.5, 1, 1.25, 1.5, 2],
        inactivityTimeout: 0,
        controlBar: {
            fullscreenToggle: true,
            volumePanel: {
                inline: false,
            },
        }
    });

    // this changes the background color to red
    const bgColorSelector = document.querySelector('.vjs-bg-color > select');
    bgColorSelector.value = "#000";

    // this changes the background opacity to 0.5
    const bgOpacitySelector = document.querySelector('.vjs-bg-opacity > select');
    bgOpacitySelector.value = "0.5"

    fetch(`/professor/desertbus/line/${line_id}`)
        .then(response => response.json())
        .then(fillLineInfo)
        .then(initializePlayer);

    handleLoginState();
}

function handleLoginState() {
    if (document.cookie.split('; ').find(row => row.startsWith('credentials='))) {
        document.getElementById("logout").style.display = "";
    } else {
        document.getElementById("googleLoginButton").style.display = "";
    }

}

function doGoogle() {
    google.accounts.id.initialize({
        client_id: "164084252563-kaks3no7muqb82suvbubg7r0o87aip7n.apps.googleusercontent.com",
        callback: loggedIn,
        auto_select: true
    });
    google.accounts.id.renderButton(
        document.getElementById("googleLoginButton"),
        {theme: "outline", size: "large"}  // customization attributes
    );
    google.accounts.id.prompt(); // also display the One Tap dialog
}

function doLogout() {
    document.cookie = `credentials=;expires=Thu, 01 Jan 1970 00:00:01 GMT`;
    document.getElementById("googleLoginButton").style.display = "";
    document.getElementById("logout").style.display = "none";
}

function loggedIn(response) {

    document.cookie = `credentials=${response.credential}`;

    document.getElementById("googleLoginButton").style.display = "none";
    document.getElementById("logout").style.display = "";

    console.log(response);
}

function fillLineInfo(line_json) {
    line_id = line_json.id

    line = line_json
    document.getElementById("original_transcription").innerHTML = line_json.line_data.result
        .map(word => `<span style="opacity: ${word.conf}">${word.word}</span>`).join(" ");
    document.getElementById("new_transcription")
        .attributes.getNamedItem("placeholder").value = line_json.line_data.text;
}

function initializePlayer() {
    videojs.getPlayer("player").src([
        {src: `/professor/desertbus/line/${line_id}/playlist.m3u8`}
    ]);
    videojs.getPlayer("player").addRemoteTextTrack({
        kind: "captions",
        src: `/buscribe/desertbus/vtt?start_time=${line.start_time}&end_time=${line.end_time}`,
        srclang: "en",
        label: "English",
        default: true
    }, false);
}

async function submit() {
    document.getElementById("update_indicator").innerText = "⭯"


    const new_transcription = document.getElementById("new_transcription").value;
    const new_speakers = await Promise.all(document.getElementById("speaker_input").value
        .trim()
        .split(",")
        .filter(x => x !== "")
        .map(speaker_raw => speaker_raw.trim())
        .map(async function (speaker) {
            for (const speaker_json of speakers) {
                if (speaker_json.name === speaker) {
                    return speaker_json.id
                }
            }

            return await fetch("/professor/desertbus/speaker",
                {
                    method: "PUT",
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(speaker),
                    credentials: "include"
                }).then(response =>
                parseInt(response.headers.get("Content-Location")
                    .split("/")
                    .pop(), 10));
        }));

    fetch(`/professor/desertbus/line/${line_id}`,
        {
            method: "POST",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({transcription: new_transcription, speakers: new_speakers}),
            credentials: "include"
        }).then(response => {
        if (response.ok) {
            document.getElementById("update_indicator").innerText = "\u2714\ufe0f"
        } else {
            document.getElementById("update_indicator").innerText = "\u2716\ufe0f️"
        }
    })
}

$(function () {
    fetch("/professor/desertbus/speaker")
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

function parseJwt(token) {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
        atob(base64)
            .split('')
            .map(function (c) {
                return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
            }).join(''));

    return JSON.parse(jsonPayload);
}