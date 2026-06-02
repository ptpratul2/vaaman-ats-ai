from resume.resume.doctype.pdf_upload.pdf_upload import (
    _extract_and_parse_file,
    reset_gemini_retry_counter,
    get_gemini_retry_counter,
)
from vaaman_ats_ai.api.resume.resume import (
    calculate_experience_years,
    flatten_resume_data,
    create_resume_from_upload,
    match_job_opening_hybrid
)

import os
import json
import frappe
import re

CAREER_EMAIL_SOURCE = "Career Email"


def _ensure_career_email_source():
    """Create Job Applicant Source master if missing."""
    if not frappe.db.exists("Job Applicant Source", CAREER_EMAIL_SOURCE):
        frappe.get_doc(
            {
                "doctype": "Job Applicant Source",
                "source_name": CAREER_EMAIL_SOURCE,
                "details": "Auto-created by email resume parser",
            }
        ).insert(ignore_permissions=True)


def _normalize_scoring(parsed):
    """Return sanitized applicant_rating, score and fit_level."""
    allowed_fit_levels = {"", "Strong Fit", "Moderate Fit", "Weak Fit"}

    score = parsed.get("score")
    try:
        score = int(float(score)) if score not in (None, "") else None
    except Exception:
        score = None
    if score is not None:
        score = max(0, min(100, score))
    else:
        score = 0

    rating = parsed.get("applicant_rating") or parsed.get("rating")
    try:
        rating = float(rating) if rating not in (None, "") else None
    except Exception:
        rating = None
    if rating is None and score is not None:
        rating = round(score / 100, 2)
    if rating is not None:
        rating = max(0.0, min(1.0, rating))
    else:
        rating = 0.0

    fit_level = (parsed.get("fit_level") or "").strip()
    if fit_level not in allowed_fit_levels:
        fit_level = ""

    return rating, score, fit_level


def _map_highest_qualification(degree_text):
    d = (degree_text or "").lower()
    if "phd" in d or "doctor" in d:
        return "PhD"
    if "master" in d or "m.tech" in d or "mba" in d or "mca" in d:
        return "Master’s Degree"
    if "bachelor" in d or "b.tech" in d or "b.e" in d or "bca" in d or "b.sc" in d:
        return "Bachelor’s Degree"
    if "diploma" in d:
        return "Diploma"
    return "Other" if d else ""


def clean_phone_numbers(phone):
    if not phone:
        return [], ""

    # Convert list to string if AI returns array
    if isinstance(phone, list):
        phone = ",".join(phone)

    # Split multiple numbers
    numbers = re.split(r"[,\n;/]+", str(phone))

    valid_numbers = []

    for num in numbers:
        num = num.strip()

        # Remove unwanted chars
        num = re.sub(r"[^\d+]", "", num)

        # Basic validation
        if len(re.sub(r"\D", "", num)) >= 10:
            if num not in valid_numbers:
                valid_numbers.append(num)

    first_number = valid_numbers[0] if valid_numbers else ""
    remaining_numbers = ", ".join(valid_numbers[1:]) if len(valid_numbers) > 1 else ""

    return first_number, remaining_numbers


@frappe.whitelist(allow_guest=True)
def fetch_email_resumes():

    # ✅ Get configured email account
    email_account = (
        frappe.db.get_single_value("ATS Settings", "career_email_account")
        or frappe.conf.get("email_account")
    )

    if not email_account:
        frappe.log_error(
            title="Email Account Not Configured",
            message="Career email account not configured in ATS Settings."
        )
        return {
            "status": "error",
            "message": "Email account not configured"
        }

    # ✅ Fetch only limited unprocessed emails
    communications = frappe.get_all(
        "Communication",
        filters={
            "communication_type": "Communication",
            "sent_or_received": "Received",
            "email_account": email_account,
            "custom_processed": 0,
            "custom_processing": 0
        },
        fields=["name", "subject", "sender"],
        limit_page_length=10,
        order_by="creation desc"
    )

    if not communications:
        return {
            "status": "success",
            "message": "No new emails found"
        }

    # ✅ Fetch active job openings once
    active_job_openings = frappe.get_all(
        "Job Opening",
        filters={"status": "Open"},
        fields=["name", "job_title", "department", "description"]
    )

    queued = 0

    for comm in communications:
        try:
            # ✅ Lock record immediately
            frappe.db.set_value(
                "Communication",
                comm.name,
                "custom_processing",
                1
            )

            frappe.db.commit()
            
            frappe.enqueue(
                "vaaman_ats_ai.api.email.fetch_resumes.process_single_email_resume",
                queue="long",
                communication_name=comm.name,
                job_openings=active_job_openings
            )

            queued += 1

        except Exception:
            frappe.log_error(
                title="Queue Resume Processing Failed",
                message=frappe.get_traceback()
            )

    return {
        "status": "success",
        "queued": queued
    }


def process_single_email_resume(communication_name, job_openings=None):

    try:
        _ensure_career_email_source()
        if not frappe.db.exists("Communication", communication_name):
            frappe.log_error(
                title="Communication Missing",
                message=f"Communication {communication_name} no longer exists."
            )
            return

        comm_doc = frappe.get_doc("Communication", communication_name)

        # ✅ Skip already processed
        if comm_doc.custom_processed:
            return

        email_subject = comm_doc.subject or ""

        # ✅ Limit email body size to avoid memory issues
        email_body = (comm_doc.content or "")[:5000]

        # ✅ Get attachments
        files = frappe.get_all(
            "File",
            filters={"attached_to_name": communication_name},
            fields=["name", "file_url", "file_name"]
        )

        # ✅ Delete emails without attachments
        if not files:
            frappe.delete_doc(
                "Communication",
                communication_name,
                ignore_permissions=True
            )
            frappe.db.commit()
            return

        # ✅ Filter valid resume files
        valid_files = [
            f for f in files
            if f.file_name.lower().endswith((".pdf", ".doc", ".docx"))
        ]

        if not valid_files:
            frappe.delete_doc(
                "Communication",
                communication_name,
                ignore_permissions=True
            )
            frappe.db.commit()
            return

        # Parse audit counters
        parsed_count = 0
        skipped_existing_attachment = 0
        skipped_duplicate_email = 0
        gemini_retries_total = 0

        # ✅ Do job matching once per email (not once per attachment)
        matched_job_id = None
        selected_job_name = None
        selected_job_title = None
        selected_job_desc = None
        # Optimization: if only one open job exists, skip AI matching call entirely.
        if job_openings and len(job_openings) == 1:
            matched_job_id = {
                "job_opening": job_openings[0].get("name"),
                "confidence": "high",
                "fit_level": "Unable to Assess",
                "score": 0,
                "justification": "Single active job opening auto-mapped",
            }
        elif job_openings:
            matched_job_id = match_job_opening_hybrid(
                email_subject=email_subject,
                email_body=email_body,
                job_openings=job_openings
            )

        # Use matched job context for resume parsing/scoring prompt.
        if isinstance(matched_job_id, dict):
            selected_job_name = matched_job_id.get("job_opening")
        if selected_job_name and job_openings:
            for job in job_openings:
                if job.get("name") == selected_job_name:
                    selected_job_title = job.get("job_title") or selected_job_name
                    selected_job_desc = job.get("description")
                    break

        frappe.log_error(
            title="AI Job Matching",
            message=f"""
                    Email Subject: {email_subject}

                    Matched Job:
                    {matched_job_id}
                    """
        )

        # ✅ Process each attachment
        for f in valid_files:

            try:
                # Skip expensive parsing if this attachment was already processed earlier.
                if frappe.db.exists("Job Applicant", {"resume_attachment": f.file_url}):
                    skipped_existing_attachment += 1
                    continue

                # ✅ Get file path
                file_doc = frappe.get_doc(
                    "File",
                    {"file_url": f.file_url}
                )

                file_path = file_doc.get_full_path()

                ext = os.path.splitext(file_path)[1].lower()

                # ✅ Load prompt template
                prompt_path = frappe.get_app_path(
                    "resume",
                    "resume",
                    "doctype",
                    "pdf_upload",
                    "resume_prompt.txt"
                )

                with open(prompt_path, "r") as pf:
                    prompt_template = pf.read()

                api_key = frappe.conf.get("gemini_api_key")

                # ✅ Parse Resume
                reset_gemini_retry_counter()
                _fu, applicant_data, err = _extract_and_parse_file((
                    file_path,
                    f.file_url,
                    selected_job_title,
                    selected_job_desc,
                    ext,
                    api_key,
                    prompt_template,
                ))

                if isinstance(applicant_data, str):
                    try:
                        applicant_data = json.loads(applicant_data)
                    except Exception:
                        continue

                if err or not applicant_data:
                    gemini_retries_total += get_gemini_retry_counter()
                    continue

                # ✅ Normalize fields
                if (
                    "email_id" in applicant_data
                    and "email" not in applicant_data
                ):
                    applicant_data["email"] = applicant_data["email_id"]

                if (
                    "phone_number" in applicant_data
                    and "phone" not in applicant_data
                ):
                    applicant_data["phone"] = applicant_data["phone_number"]

                applicant_name = (
                    applicant_data.get("applicant_name")
                    or applicant_data.get("name")
                    or applicant_data.get("full_name")
                )

                email_value = applicant_data.get("email")

                if not applicant_name or not email_value:
                    continue

                # ✅ Skip duplicate applicants
                if frappe.db.exists(
                    "Job Applicant",
                    {"email_id": email_value}
                ):
                    gemini_retries_total += get_gemini_retry_counter()
                    skipped_duplicate_email += 1
                    continue

                # ✅ Calculate experience
                applicant_data["experience_years"] = (
                    calculate_experience_years(
                        applicant_data.get("experience", [])
                    )
                )

                flat_data = flatten_resume_data(applicant_data)
                applicant_rating, score, fit_level = _normalize_scoring(applicant_data)
                # If parser could not score (common when JD context is weak),
                # reuse the already computed job-matching signal (no extra API call).
                if isinstance(matched_job_id, dict):
                    match_score = matched_job_id.get("score")
                    match_fit = matched_job_id.get("fit_level")
                    if (score in (None, 0)) and isinstance(match_score, (int, float)):
                        score = int(max(0, min(100, match_score)))
                    if (not fit_level) and isinstance(match_fit, str):
                        fit_level = match_fit if match_fit in ("Strong Fit", "Moderate Fit", "Weak Fit") else fit_level
                    if applicant_rating in (None, 0.0) and isinstance(score, (int, float)):
                        applicant_rating = round(float(score) / 100, 2)
                    if not applicant_data.get("justification_by_ai"):
                        applicant_data["justification_by_ai"] = matched_job_id.get("justification") or ""
                
                clean_phone, other_phones = clean_phone_numbers(
                    applicant_data.get("phone", "")
                )

                # ✅ Create Job Applicant
                applicant = frappe.get_doc({
                    "doctype": "Job Applicant",
                    "applicant_name": applicant_name,
                    "email_id": email_value,
                    "job_title": selected_job_name,
                    "resume_attachment": f.file_url,
                    "status": "Open",
                    "source": CAREER_EMAIL_SOURCE,
                    "source_of_job_posting": "Company Website",
                    "position_applied_for": selected_job_title or "",
                    # "phone_number": applicant_data.get("phone", ""),
                    "phone_number": clean_phone,
                    "custom_phone_number_2": other_phones,
                    "applicant_rating": applicant_rating or 0,
                    "score": score or 0,
                    "fit_level": fit_level,
                    "justification_by_ai": applicant_data.get("justification_by_ai", ""),
                    "custom_parsed_json": json.dumps(applicant_data),
                    "custom_parse_status": "Parsed",
                    "custom_experience_years": flat_data.get(
                        "experience_years", 0
                    ),
                    "current_location": flat_data.get(
                        "location", ""
                    ),
                    "custom_skills": flat_data.get(
                        "skills", ""
                    ),
                    "custom_current_role": flat_data.get(
                        "current_role", ""
                    ),
                    "custom_degree": flat_data.get(
                        "degree", ""
                    ),
                    "custom_institution": flat_data.get(
                        "institution", ""
                    ),
                    "current_job_title": flat_data.get("current_role", ""),
                    "relevant_experience_in_years": applicant_data.get("custom_total_experience", ""),
                    "highest_qualification": _map_highest_qualification(flat_data.get("degree", "")),
                    "custom_current_company": applicant_data.get("custom_current_company")
                    or (
                        applicant_data.get("experience", [{}])[0].get("company_name", "")
                        if applicant_data.get("experience")
                        else ""
                    ),
                    "custom_total_experience": applicant_data.get("custom_total_experience", ""),
                })

                applicant.insert(ignore_permissions=True)
                parsed_count += 1
                gemini_retries_total += get_gemini_retry_counter()

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
                        title=f"Resume Embedding Failed: {applicant.name}",
                        message=frappe.get_traceback()
                    )

            except Exception:
                frappe.log_error(
                    title="Resume Processing Failed",
                    message=frappe.get_traceback()
                )

        frappe.log_error(
            title="Email Parse Audit",
            message=(
                f"Communication: {communication_name}\n"
                f"Parsed: {parsed_count}\n"
                f"Skipped existing attachment: {skipped_existing_attachment}\n"
                f"Skipped duplicate email: {skipped_duplicate_email}\n"
                f"Gemini retries: {gemini_retries_total}"
            ),
        )

        # ✅ Mark email processed
        frappe.db.set_value(
            "Communication",
            communication_name,
            {
                "custom_processed": 1,
                "custom_processing": 0
            }
        )

        frappe.db.commit()

    except Exception:

        if frappe.db.exists("Communication", communication_name):

            frappe.db.set_value(
                "Communication",
                communication_name,
                "custom_processing",
                0
            )

            frappe.db.commit()

        frappe.log_error(
            title="Email Resume Fetch Failed",
            message=frappe.get_traceback()
        )