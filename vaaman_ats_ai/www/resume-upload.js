function uploadResume() {
    const fileInput = document.getElementById("resumeFile");
    const output = document.getElementById("output");

    if (!fileInput.files.length) {
        frappe.msgprint("Please select a resume file");
        return;
    }

    const formData = new FormData();
    formData.append("resume", fileInput.files[0]);

    output.innerText = "Parsing resume...";

    fetch(
        // "https://cnd.octavision.in/api/method/vaaman_ats_ai.parse_resume.parse_resume",
        // "https://cnd.octavision.in/api/method/vaaman_ats_ai.api.resume.parse_resume.parse_resume",
        "https://cnd.octavision.in/api/method/vaaman_ats_ai.api.resume.resume_parse.resume_parse",
        {
            method: "POST",
            headers: {
                "X-Frappe-CSRF-Token": frappe.csrf_token
            },
            body: formData
        }
    )
        // .then(res => res.json())
        .then(async res => {
            const text = await res.text();
            console.log("RAW RESPONSE:", text);
            try {
                return JSON.parse(text);
            } catch (e) {
                throw new Error("Server did not return JSON:\n" + text);
            }
        })
        .then(data => {
            output.innerText = JSON.stringify(data, null, 2);
        })
        .catch(err => {
            output.innerText = "Error: " + err;
        });
}
