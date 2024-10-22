function onSiteLoad(e) {

    document.getElementById("search_tools").addEventListener("keydown",
        function (event) {
            if (event.key === 'Enter') doSearch()
        });

    doSearch();
}

function query(text, start_time, end_time) {
    let query_string = ""

    const time_type = document.getElementById("UTC_time_radio").checked ? "" : "bus_";

    if (start_time !== "") {
        query_string += `${time_type}start_time=${start_time}`;
    }
    if (end_time !== "") {
        query_string += `&${time_type}end_time=${end_time}`;
    }
    if (text !== "") {
        query_string += `&query=${text}`
    }

    query_string += "&limit=30";

    const channel = document.getElementById("channel_select").value;

    fetch(`https://wubloader.raptorpond.com/buscribe/${channel}/json?${query_string}`)
        .then(response => response.json())
        .then(fillResults)

}

function doSearch() {
    query(
        document.getElementById("search_text").value,
        document.getElementById("start_time").value,
        document.getElementById("end_time").value
    )
}

function fillResults(results) {
    const results_element = document.getElementById("results")
    results_element.innerHTML = ""

    const channel = document.getElementById("channel_select").value;

    for (const line of results) {
        const line_div = document.createElement("div");

        line_div.classList.add("line");
        if (line.verifier) {
            line_div.classList.add("verified");
        }


        line_div.innerHTML = `  
            <div class="line_start_bus_time">${line.start_bus_time}</div>
            <div class="line_speakers">${line.speakers == null ? "" : line.speakers.join(", ")}</div>
            <div class="line_start_time">${line.start_time}</div>
            <div class="line_text">${line.text}</div>
            <div class="line_links">
                <a href="/professor/professor.html?line=${line.id}">Edit</a>
                <a href="javascript:showContext('${line.start_time}');">Show context</a>
            </div>            
        `;


        results_element.append(line_div)
    }
}

function switchToUTC() {
    document.getElementById("start_time").type = "datetime-local";
    document.getElementById("end_time").type = "datetime-local";
}

function switchToBus() {
    document.getElementById("start_time").type = "text";
    document.getElementById("end_time").type = "text";
}

function showContext(time) {

    let start_time = new Date(time + "Z");
    start_time.setMinutes(start_time.getMinutes() - 3);
    let start_time_string = start_time.toISOString();
    start_time_string = start_time_string.substring(0, start_time_string.length - 1)

    let end_time = new Date(time + "Z");
    end_time.setMinutes(end_time.getMinutes() + 3);
    let end_time_string = end_time.toISOString();
    end_time_string = end_time_string.substring(0, end_time_string.length - 1)

    document.getElementById("start_time").value = start_time_string;
    document.getElementById("end_time").value = end_time_string;
    document.getElementById("search_text").value = "";

    doSearch();
}