from resume.resume.doctype.pdf_upload.pdf_upload import _extract_and_parse_file
from vaaman_ats_ai.api.resume.resume import (
    calculate_experience_years,
    flatten_resume_data,
    create_resume_from_upload,
    match_job_opening_hybrid
)
import os
import json
import frappe

@frappe.whitelist(allow_guest=True)
def fetch_email_resumes():
    # ✅ Fetch ACTIVE Job Openings for matching
    active_job_openings = frappe.get_all(
        "Job Opening",
        filters={"status": "Open"},
        fields=["name", "job_title", "department", "description"]
    )
    
    # email_account = frappe.db.get_default("email_account")
    email_account = frappe.conf.get("email_account")
    if not email_account:
        frappe.log_error(
            title="Email Account Not Configured",
            message="Please set the default email account in the system settings."
        )
        return
    
    communications = frappe.get_all(
        "Communication",
        filters={
            "communication_type": "Communication",
            "sent_or_received": "Received",
            "email_account": email_account
            # "email_account": "Ajayshivhare047"
        },
        fields=["name", "sender", "subject", "content"]  # ✅ Added content field
    )
    
    for comm in communications:
        try:
            if frappe.db.get_value("Communication", comm.name, "custom_processed"):
                continue

            # ✅ Get email body/content
            comm_doc = frappe.get_doc("Communication", comm.name)
            email_subject = comm_doc.subject or ""
            email_body = comm_doc.content or ""  # or comm_doc.message if using that field
            
            files = frappe.get_all(
                "File",
                filters={"attached_to_name": comm.name},
                fields=["name", "file_url", "file_name"]
            )

            if not files:
                frappe.delete_doc("Communication", comm.name, ignore_permissions=True)
                frappe.db.commit()
                continue

            valid_files = [
                f for f in files
                if f.file_name.lower().endswith((".pdf", ".doc", ".docx"))
            ]

            if not valid_files:
                frappe.delete_doc("Communication", comm.name, ignore_permissions=True)
                frappe.db.commit()
                continue

            for f in valid_files:
                try:
                    # ✅ AI Match to Job Opening
                    matched_job_id = None
                    if active_job_openings:
                        matched_job_id = match_job_opening_hybrid(
                            email_subject=email_subject,
                            email_body=email_body,
                            job_openings=active_job_openings
                        )
                        # matched_job_id = match_job_opening_with_ai(
                        #     email_subject=email_subject,
                        #     email_body=email_body,
                        #     job_openings=active_job_openings
                        # )
                        
                    frappe.log_error(
                        title="AI Job Matching",
                        message=f"Email: {email_subject} matched to Job Opening ID: {matched_job_id}"
                    )
                    
                    # ✅ Get file path and parse resume
                    file_doc = frappe.get_doc("File", {"file_url": f.file_url})
                    file_path = file_doc.get_full_path()
                    ext = os.path.splitext(file_path)[1].lower()

                    prompt_path = frappe.get_app_path(
                        "resume", "resume", "doctype", "pdf_upload", "resume_prompt.txt"
                    )
                    with open(prompt_path, "r") as pf:
                        prompt_template = pf.read()

                    api_key = frappe.conf.get("gemini_api_key")

                    _fu, applicant_data, err = _extract_and_parse_file((
                        file_path,
                        f.file_url,
                        None,
                        None,
                        ext,
                        api_key,
                        prompt_template,
                    ))

                    if isinstance(applicant_data, str):
                        try:
                            applicant_data = json.loads(applicant_data)
                        except:
                            continue

                    if err or not applicant_data:
                        continue

                    # ✅ Normalize fields
                    if "email_id" in applicant_data and "email" not in applicant_data:
                        applicant_data["email"] = applicant_data["email_id"]

                    if "phone_number" in applicant_data and "phone" not in applicant_data:
                        applicant_data["phone"] = applicant_data["phone_number"]

                    applicant_name = (
                        applicant_data.get("applicant_name")
                        or applicant_data.get("name")
                        or applicant_data.get("full_name")
                    )

                    email_value = applicant_data.get("email")

                    if not applicant_name or not email_value:
                        continue

                    # ✅ Duplicate check
                    if frappe.db.exists("Job Applicant", {"email_id": email_value}):
                        continue

                    # ✅ Process data
                    applicant_data["experience_years"] = calculate_experience_years(
                        applicant_data.get("experience", [])
                    )

                    flat_data = flatten_resume_data(applicant_data)

                    # ✅ Create Job Applicant WITH Job Opening reference
                    applicant = frappe.get_doc({
                        "doctype": "Job Applicant",
                        "applicant_name": applicant_name,
                        "email_id": email_value,
                        # "job_applied_for": matched_job_id,  # ✅ Link to Job Opening
                        # "job_title": matched_job_id,  # ✅ Link to Job Opening
                        "job_title": matched_job_id.get("job_opening"),  # ✅ Link to Job Opening
                        "resume_attachment": f.file_url,
                        "status": "Open",
                        "phone_number": applicant_data.get("phone", ""),
                        "custom_parsed_json": json.dumps(applicant_data),
                        "custom_parse_status": "Parsed",
                        "custom_experience_years": flat_data["experience_years"],
                        "current_location": flat_data["location"],
                        "custom_skills": flat_data["skills"],
                        "custom_current_role": flat_data["current_role"],
                        "custom_degree": flat_data["degree"],
                        "custom_institution": flat_data["institution"],
                        # "custom_matched_by_ai": 1 if matched_job_id else 0,  # ✅ Track AI matching
                        # "custom_matching_confidence": "high"  # ✅ Optional: store confidence
                    })
                    
                    frappe.log_error(
                        title="Creating Job Applicant",
                        message=f"Creating applicant for {applicant_name} with applicant {applicant}"
                    )
                    
                    applicant.insert(ignore_permissions=True)
                    frappe.db.commit()

                    # ✅ Create embeddings
                    try:
                        create_resume_from_upload(
                            applicant_data=applicant_data,
                            file_url=f.file_url,
                            applicant_doc=applicant
                        )
                    except Exception:
                        frappe.log_error(
                            message=frappe.get_traceback(),
                            title=f"Resume Error: {applicant.name}"
                        )

                except Exception:
                    frappe.log_error(
                        title="Resume Processing Failed",
                        message=frappe.get_traceback()
                    )
            
            # ✅ Mark communication as processed
            frappe.db.set_value("Communication", comm.name, "custom_processed", 1)
            frappe.db.commit()

        except Exception:
            frappe.log_error(
                title="Email Resume Fetch Failed",
                message=frappe.get_traceback()
            )