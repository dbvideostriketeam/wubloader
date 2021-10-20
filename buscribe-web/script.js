function onSiteLoad(e) {

    document.getElementById("search_tools").addEventListener("keydown",
        function (event) {
            if (event.key === 'Enter') doSearch()
        });

    doSearch();
}

function query(text, start_time, end_time) {
    let query_string = ""

    if (start_time !== "") {
        query_string += `start_time=${start_time}`;
    }
    if (end_time !== "") {
        query_string += `&end_time=${end_time}`;
    }
    if (text !== "") {
        query_string += `&query=${text}`
    }

    query_string += "&limit=30";

    fetch(`http://localhost:8010/buscribe/json?${query_string}`)
        .then(response => response.json())
        // .then(response => console.log(response.error()))
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
        `;


        results_element.append(line_div)
    }
}