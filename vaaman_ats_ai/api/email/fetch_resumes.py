from resume.api.parse_guards import (
    applicant_exists_for_job,
    should_skip_file_for_job,
)
from resume.resume.doctype.pdf_upload.pdf_upload import (
    _extract_and_parse_file,
    reset_gemini_retry_counter,
    get_gemini_retry_counter,
)
from vaaman_ats_ai.api.resume.resume import (
    calculate_experience_years,
    flatten_resume_data,
    create_resume_from_upload,
    get_active_job_openings_cached,
    match_job_opening_for_email,
)

import email.utils
import os
import json
import frappe
import re

CAREER_EMAIL_SOURCE = "Career Email"
EMAIL_BATCH_SIZE = 50
STALE_PROCESSING_MINUTES = 30
MAX_LONG_QUEUE_BEFORE_ENQUEUE = 40
MIN_EMAIL_BATCH_WHEN_BACKLOG = 5


def _long_queue_depth():
    try:
        from frappe.utils.background_jobs import get_queue
        return len(get_queue("long"))
    except Exception:
        return 0


def _effective_batch_size():
    """
    Keep ingesting fresh emails even when backlog exists.

    A hard stop (batch=0) can freeze new intake for long periods, so keep a
    small reserved intake window.
    """
    depth = _long_queue_depth()
    available_slots = MAX_LONG_QUEUE_BEFORE_ENQUEUE - depth
    if available_slots <= 0:
        return min(EMAIL_BATCH_SIZE, MIN_EMAIL_BATCH_WHEN_BACKLOG)
    return min(
        EMAIL_BATCH_SIZE,
        max(MIN_EMAIL_BATCH_WHEN_BACKLOG, available_slots),
    )


def _extract_email_address(raw):
    if not raw:
        return ""
    _, addr = email.utils.parseaddr(raw)
    return (addr or str(raw)).strip().lower()


def _recover_stale_processing_locks():
    """Unlock emails stuck in custom_processing after worker crash."""
    cutoff = frappe.utils.add_to_date(
        frappe.utils.now(), minutes=-STALE_PROCESSING_MINUTES
    )
    stale = frappe.get_all(
        "Communication",
        filters={
            "custom_processing": 1,
            "custom_processed": 0,
            "modified": ["<", cutoff],
        },
        pluck="name",
    )
    for name in stale:
        frappe.db.set_value(
            "Communication", name, {"custom_processing": 0}
        )
    if stale:
        frappe.db.commit()
    return len(stale)


def _ensure_db_connection():
    """Reconnect MySQL after long Ollama/Gemini calls (wait_timeout)."""
    try:
        frappe.db.sql("SELECT 1")
    except Exception:
        try:
            frappe.db.close()
        except Exception:
            pass
        frappe.db.connect(reconnect=True)


def _mark_communication_processed(communication_name):
    frappe.db.set_value(
        "Communication",
        communication_name,
        {"custom_processed": 1, "custom_processing": 0},
    )
    frappe.db.commit()


def _is_email_reply(comm_doc):
    subject = (comm_doc.subject or "").strip().lower()
    if comm_doc.in_reply_to:
        return True
    return subject.startswith(("re:", "fwd:", "fw:"))


def _get_skip_reason_for_job(comm_doc, sender_email, job_opening):
    """Skip only when the same candidate already applied for this job opening."""
    if not job_opening or not sender_email:
        return ""

    if not applicant_exists_for_job(sender_email, job_opening):
        return ""

    if _is_email_reply(comm_doc):
        return "reply_same_job_already_applied"
    return "duplicate_sender_same_job"


def _filter_attachments_needing_parse(valid_files, job_opening=None):
    """Return attachments not yet imported for this specific job opening."""
    pending = []
    skipped_existing_attachment = 0
    for f in valid_files:
        attachment_filters = {"resume_attachment": f.file_url}
        if job_opening:
            attachment_filters["job_title"] = job_opening
            if frappe.db.exists("Job Applicant", attachment_filters):
                skipped_existing_attachment += 1
                continue
        try:
            file_doc = frappe.get_doc("File", {"file_url": f.file_url})
        except Exception:
            pending.append(f)
            continue
        if job_opening and should_skip_file_for_job(
            f.file_url, file_doc.content_hash, job_opening
        ):
            skipped_existing_attachment += 1
            continue
        pending.append(f)
    return pending, skipped_existing_attachment


def _log_email_parse_audit(communication_name, **counts):
    frappe.log_error(
        title="Email Parse Audit",
        message="\n".join(
            [f"Communication: {communication_name}"]
            + [f"{key}: {value}" for key, value in counts.items()]
        ),
    )


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
        return "", ""

    # Convert list to string if AI returns array
    if isinstance(phone, list):
        normalized = []
        for p in phone:
            if isinstance(p, dict):
                normalized.append(
                    str(
                        p.get("phone")
                        or p.get("number")
                        or p.get("value")
                        or ""
                    )
                )
            else:
                normalized.append(str(p or ""))
        phone = ",".join(normalized)

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

    return str(first_number or ""), str(remaining_numbers or "")


def _normalize_scalar(value):
    """Ensure Document fields never receive list/dict types."""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


@frappe.whitelist()
def fetch_email_resumes():
    if frappe.session.user == "Guest":
        frappe.throw("Not permitted", frappe.PermissionError)

    _recover_stale_processing_locks()

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
    prioritize_new = frappe.db.get_single_value(
        "ATS Settings", "prioritize_new_emails_first"
    )
    if prioritize_new is None:
        prioritize_new = 1

    order_by = "communication_date desc" if prioritize_new else "communication_date asc"

    batch_size = _effective_batch_size()
    if batch_size <= 0:
        return {
            "status": "success",
            "message": "Long queue full — waiting for worker to drain",
            "queued": 0,
            "long_queue_depth": _long_queue_depth(),
        }

    communications = frappe.get_all(
        "Communication",
        filters={
            "communication_type": "Communication",
            "sent_or_received": "Received",
            "email_account": email_account,
            "custom_processed": 0,
            "custom_processing": 0
        },
        fields=["name", "subject", "sender", "communication_date"],
        limit_page_length=batch_size,
        order_by=order_by
    )

    if not communications:
        return {
            "status": "success",
            "message": "No new emails found"
        }

    queued = 0

    for comm in communications:
        try:
            frappe.enqueue(
                "vaaman_ats_ai.api.email.fetch_resumes.process_single_email_resume",
                queue="long",
                communication_name=comm.name,
                job_id=f"email_resume_{comm.name}",
                deduplicate=True,
                at_front=True,
                timeout=600,
            )

            frappe.db.set_value(
                "Communication",
                comm.name,
                "custom_processing",
                1,
            )
            frappe.db.commit()
            queued += 1

        except Exception:
            frappe.db.set_value(
                "Communication",
                comm.name,
                "custom_processing",
                0,
            )
            frappe.db.commit()
            frappe.log_error(
                title="Queue Resume Processing Failed",
                message=frappe.get_traceback()
            )

    return {
        "status": "success",
        "queued": queued,
        "prioritize_new_emails_first": bool(prioritize_new),
        "order_by": order_by,
        "long_queue_depth": _long_queue_depth(),
    }


def process_single_email_resume(communication_name, job_openings=None):

    try:
        _ensure_db_connection()
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

        # ✅ Mark emails without attachments (do not delete — keep audit trail)
        if not files:
            _log_email_parse_audit(
                communication_name,
                skip_reason="no_attachments",
                parsed=0,
                gemini_retries=0,
            )
            _mark_communication_processed(communication_name)
            return

        # ✅ Filter valid resume files
        valid_files = [
            f for f in files
            if f.file_name.lower().endswith((".pdf", ".doc", ".docx"))
        ]

        if not valid_files:
            _log_email_parse_audit(
                communication_name,
                skip_reason="no_valid_resume_attachment",
                parsed=0,
                gemini_retries=0,
            )
            _mark_communication_processed(communication_name)
            return

        # Parse audit counters
        parsed_count = 0
        skipped_existing_attachment = 0
        skipped_duplicate_email = 0
        skipped_duplicate_same_job = 0
        skipped_reply_same_job = 0
        gemini_retries_total = 0

        sender_email = _extract_email_address(comm_doc.sender)

        if not job_openings:
            job_openings = get_active_job_openings_cached()

        # Job matching: keyword/cache first, then AI on top-N jobs only (not one RQ job per opening)
        matched_job_id = match_job_opening_for_email(
            email_subject=email_subject,
            email_body=email_body,
            job_openings=job_openings,
        )
        _ensure_db_connection()
        selected_job_name = None
        selected_job_title = None
        selected_job_desc = None

        # Use matched job context for resume parsing/scoring prompt.
        if isinstance(matched_job_id, dict):
            selected_job_name = matched_job_id.get("job_opening")
        if selected_job_name and job_openings:
            for job in job_openings:
                if job.get("name") == selected_job_name:
                    selected_job_title = job.get("job_title") or selected_job_name
                    selected_job_desc = job.get("description")
                    break

        provider = (matched_job_id or {}).get("ai_provider", "")
        api_failed = bool((matched_job_id or {}).get("api_failed"))
        if api_failed:
            frappe.log_error(
                title="AI Job Matching",
                message=(
                    f"Email Subject: {email_subject}\n"
                    f"Sender: {sender_email}\n"
                    f"AI provider: {provider}\n"
                    f"Matched Job: {matched_job_id}"
                ),
            )
        else:
            frappe.logger().info(
                f"Job match ({provider}): {email_subject[:80]} -> "
                f"{(matched_job_id or {}).get('job_opening')}"
            )
        skip_reason = _get_skip_reason_for_job(
            comm_doc, sender_email, selected_job_name
        )
        if skip_reason:
            if skip_reason == "duplicate_sender_same_job":
                skipped_duplicate_same_job = 1
            elif skip_reason == "reply_same_job_already_applied":
                skipped_reply_same_job = 1
            _log_email_parse_audit(
                communication_name,
                skip_reason=skip_reason,
                sender_email=sender_email or "(unknown)",
                matched_job=selected_job_name or "(none)",
                parsed=0,
                skipped_existing_attachment=0,
                skipped_duplicate_email=0,
                skipped_duplicate_same_job=skipped_duplicate_same_job,
                skipped_reply_same_job=skipped_reply_same_job,
                gemini_retries=0,
            )
            _mark_communication_processed(communication_name)
            return

        attachments_to_parse, skipped_existing_attachment = _filter_attachments_needing_parse(
            valid_files, selected_job_name
        )
        if not attachments_to_parse:
            _log_email_parse_audit(
                communication_name,
                skip_reason="all_attachments_already_processed_for_job",
                sender_email=sender_email or "(unknown)",
                matched_job=selected_job_name or "(none)",
                parsed=0,
                skipped_existing_attachment=skipped_existing_attachment,
                skipped_duplicate_email=0,
                skipped_duplicate_same_job=0,
                skipped_reply_same_job=0,
                gemini_retries=0,
            )
            _mark_communication_processed(communication_name)
            return

        # ✅ Process only attachments that still need parsing for this job
        for f in attachments_to_parse:

            try:
                if applicant_exists_for_job(sender_email, selected_job_name):
                    skipped_duplicate_same_job += 1
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

                # ✅ Parse Resume (reconnect DB — Ollama may have held the job for minutes)
                _ensure_db_connection()
                reset_gemini_retry_counter()
                _fu, _fname, applicant_data, err = _extract_and_parse_file((
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

                email_value = (applicant_data.get("email") or "").strip().lower()

                if not applicant_name or not email_value:
                    gemini_retries_total += get_gemini_retry_counter()
                    continue

                # ✅ Skip duplicate for same job (post-parse safety net)
                duplicate_filters = {"email_id": email_value}
                if selected_job_name:
                    duplicate_filters["job_title"] = selected_job_name
                if frappe.db.exists("Job Applicant", duplicate_filters):
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
                _ensure_db_connection()
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
                    "phone_number": _normalize_scalar(clean_phone),
                    "custom_phone_number_2": _normalize_scalar(other_phones),
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

        _log_email_parse_audit(
            communication_name,
            matched_job=selected_job_name or "(none)",
            parsed=parsed_count,
            skipped_existing_attachment=skipped_existing_attachment,
            skipped_duplicate_email=skipped_duplicate_email,
            skipped_duplicate_same_job=skipped_duplicate_same_job,
            skipped_reply_same_job=skipped_reply_same_job,
            gemini_retries=gemini_retries_total,
        )

        _ensure_db_connection()
        _mark_communication_processed(communication_name)

    except Exception:

        _ensure_db_connection()
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