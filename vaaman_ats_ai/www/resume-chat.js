frappe.ready(() => {

  function getResponseFormat() {
    const selected = document.querySelector(
      'input[name="responseMode"]:checked'
    );
    return selected ? selected.value : "text";
  }


  let activeFilters = {};

  window.applyFilters = function () {
    const skillsSelect = document.getElementById("filter-skills");
    const skills = Array.from(skillsSelect.selectedOptions).map(o => o.value);

    const minExp = document.getElementById("min-exp").value;
    const maxExp = document.getElementById("max-exp").value;
    const status = document.getElementById("filter-status").value;

    activeFilters = {
      skills,
      min_experience: minExp ? parseFloat(minExp) : null,
      max_experience: maxExp ? parseFloat(maxExp) : null,
      status: status || null
    };

    console.log("Active Filters:", activeFilters);
    alert("Filters applied. Chat will use selected profiles.");
  };


  window.sendQuestion = function () {
    const input = document.getElementById("questionInput");
    const chatBox = document.getElementById("chatBox");
    const question = input.value.trim();
    let modeLabel;
    if (!question) return;

    chatBox.innerHTML += `<div><b>You:</b> ${question}</div>`;
    input.value = "";

    const loaderId = "loader-" + Date.now();
    chatBox.innerHTML += `<div id="${loaderId}"><i>AI is thinking...</i></div>`;

    // fetch("/api/method/vaaman_ats_ai.chat_api.chat_query", {
    fetch("/api/method/vaaman_ats_ai.api.resume.chat_api.chat_query", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Frappe-CSRF-Token": frappe.csrf_token
      },
      body: JSON.stringify({
        question: question,
        filters: activeFilters,
        response_format: getResponseFormat()
      })
    })
      // .then(async res => {
      //   const text = await res.text();
      //   try {
      //     return JSON.parse(text);
      //   } catch {
      //     throw new Error("Server returned invalid response");
      //   }
      // })
      // .then(data => {
      //   document.getElementById(loaderId).remove();

      //   if (!data.message?.success) {
      //     chatBox.innerHTML += `<div style="color:red">${data.message?.error || "Error"}</div>`;
      //     return;
      //   }

      //   chatBox.innerHTML += `<div><b>AI:</b> ${data.message.answer}</div>`;

      //   if (data.message.sources?.length) {
      //     chatBox.innerHTML += `
      //       <div style="font-size:12px;color:#555">
      //         <b>Sources:</b>
      //         <ul>
      //           ${data.message.sources.map(s =>
      //             `<li>Candidate: ${s.candidate_id}</li>`
      //           ).join("")}
      //         </ul>
      //       </div>
      //     `;
      //   }
      // })
      // .catch(err => {
      //   document.getElementById(loaderId)?.remove();
      //   chatBox.innerHTML += `<div style="color:red">${err.message}</div>`;
      // });
      .then(async res => {
        const text = await res.text();
        try {
          return JSON.parse(text);
        } catch {
          console.error("Invalid response:", text);
          throw new Error("Server returned invalid response");
        }
      })
      .then(data => {
        document.getElementById(loaderId)?.remove();

        if (!data.message || !data.message.success) {
          chatBox.innerHTML += `<div style="color:red">Error</div>`;
          return;
        }

        modeLabel =
          getResponseFormat() === "table"
            ? "Table View"
            : "Explanation View";

        // 🔥 TABLE RESPONSE MODE
        if (data.message.format === "table") {
          let html = `
      <div style="margin:10px 0">
      <div style="font-size:12px;color:#888">
    Mode: ${modeLabel}
  </div>
        <b>Matched Candidates</b>
        <table border="1" cellpadding="8" cellspacing="0" style="width:100%; margin-top:8px; border-collapse:collapse;">
          <thead style="background:#f5f5f5">
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Skills</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
    `;

          //     data.message.rows.forEach(r => {
          //       html += `
          //   <tr>
          //     <td>${r.name || "-"}</td>
          //     <td>
          //       ${r.email ? `<a href="mailto:${r.email}">${r.email}</a>` : "-"}
          //     </td>
          //     <td>
          //       ${r.phone ? `<a href="tel:${r.phone}">${r.phone}</a>` : "-"}
          //     </td>
          //     <td>${r.skills || "-"}</td>
          //   </tr>
          // `;
          // });


//           data.message.rows.forEach(r => {
//             html += `
//         <tr>
//   <td>${r.name || "-"}</td>

//   <td>
//     ${r.email
//                 ? `<a href="mailto:${r.email}" title="Send Email">${r.email}</a>`
//                 : "-"}
//   </td>

//   <td>
//     ${r.phone
//                 ? `<a href="tel:${r.phone}" title="Call">${r.phone}</a>`
//                 : "-"}
//   </td>

//   <td>
//     ${Array.isArray(r.skills)
//                 ? r.skills.map(skill => {
//                   if (r.matched_skills?.includes(skill)) {
//                     return `<span style="background:#ffe066;padding:2px 4px;border-radius:3px;font-weight:bold">${skill}</span>`;
//                   }
//                   return skill;
//                 }).join(", ")
//                 : "-"}
//   </td>

//   <td style="white-space:nowrap">
//     ${r.email
//                 ? `<a href="mailto:${r.email}" style="margin-right:6px">
//            <button style="background:#007bff;color:white;border:none;padding:4px 8px;border-radius:3px;font-size:12px;">Email</button>
//          </a>`
//                 : ""}
//     ${r.phone
//                 ? `<a href="https://wa.me/${r.phone.replace(/[^0-9]/g, "")}" target="_blank">
//            <button style="background:#25D366;color:white;border:none;padding:4px 8px;border-radius:3px;font-size:12px;">WhatsApp</button>
//          </a>`
//                 : ""}
//   </td>
// </tr>

//       `;
//           });
          data.message.rows.forEach(r => {
            html += `
        <tr>
  <td>${r.name || "-"}</td>

  <td>
    ${r.email
                ? `<a href="mailto:${r.email}" title="Send Email">${r.email}</a>`
                : "-"}
  </td>

  <td>
    ${r.phone
                ? `<a href="tel:${r.phone}" title="Call">${r.phone}</a>`
                : "-"}
  </td>

  <td>
    ${r.skills || "-"}
  </td>

  <td style="white-space:nowrap">
    ${r.email
                ? `<a href="mailto:${r.email}" style="margin-right:6px">
           <button style="background:#007bff;color:white;border:none;padding:4px 8px;border-radius:3px;font-size:12px;">Email</button>
         </a>`
                : ""}
    ${r.phone
                ? `<a href="https://wa.me/${r.phone.replace(/[^0-9]/g, "")}" target="_blank">
           <button style="background:#25D366;color:white;border:none;padding:4px 8px;border-radius:3px;font-size:12px;">WhatsApp</button>
         </a>`
                : ""}
  </td>
</tr>

      `;
          });

          html += `
          </tbody>
        </table>
      </div>
    `;

          chatBox.innerHTML += html;
          chatBox.scrollTop = chatBox.scrollHeight;
          return;
        }

        modeLabel =
          getResponseFormat() === "table"
            ? "Table View"
            : "Explanation View";

        // 🧠 NORMAL TEXT RESPONSE MODE
        chatBox.innerHTML += `
        <div style="font-size:12px;color:#888">
    Mode: ${modeLabel}
  </div>
    <div style="margin-bottom:10px">
      <b>AI:</b> ${data.message.answer}
    </div>
  `;



        if (data.message.sources?.length) {
          chatBox.innerHTML += `
      <div style="font-size:12px;color:#555;margin-left:10px">
        <b>Sources:</b>
        <ul>
          ${data.message.sources.map(s =>
            `<li>${s.candidate}</li>`
          ).join("")}
        </ul>
      </div>
    `;
        }

        chatBox.scrollTop = chatBox.scrollHeight;
      })
      .catch(err => {
        document.getElementById(loaderId)?.remove();
        chatBox.innerHTML += `<div style="color:red">${err.message}</div>`;
      });

  };

});
