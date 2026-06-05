import frappe
# import pdfplumber
# import docx
import requests
import json
import re
from vaaman_ats_ai.api.resume.chunker import chunk_text
from vaaman_ats_ai.api.resume.embedder import embed_texts
from vaaman_ats_ai.api.resume.vector_store import add_embeddings
from datetime import datetime
from vaaman_ats_ai.api.resume.gemini import (
    get_gemini,
    get_configured_gemini_model,
)

PROMPT = """
You are an advanced resume parsing engine.
Your task is to extract structured information from a resume.

Return ONLY valid JSON. Do NOT include explanations, markdown blocks, comments, or extra text.
If any field is missing, return an empty string "" or empty array [].

Normalize and clean extracted data:
- Capitalize names properly.
- Remove duplicate skills.
- Format phone numbers in international format (e.g., +919876543210).
- Extract only real technical/hard skills (ignore soft filler words like "Teamwork").
- Infer gender only if clearly identifiable from the name; otherwise leave empty.

Schema:
{
  "first_name": "",
  "last_name": "",
  "gender": "",
  "email": "",
  "phone": "",
  "skills": [
    {
      "skill_name": "",
      "proficiency": "Intermediate" 
    }
  ],
  "education": [
    {
      "degree": "",
      "institution": "",
      "year": ""
    }
  ],
  "experience": [
    {
      "company_name": "",
      "role": "",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "is_current": false,
      "description": ""
    }
  ]
}

Rules:
- For skills, default proficiency to "Intermediate" unless clearly stated otherwise.
- Extract the most recent education and experience first.
- If an experience is current/present, set "is_current" to true and "end_date" to "".
- If exact dates are unknown, use the first day of the month (e.g., "YYYY-MM-01") or year ("YYYY-01-01").
- Do not guess missing details. Do not fabricate data.
"""

def calculate_experience_years(experiences):
    total_months = 0

    for exp in experiences:
        is_current = exp.get("is_current", False)
        start_str = exp.get("start_date", "")
        end_str = exp.get("end_date", "")

        if not start_str:
            continue

        try:
            start = datetime.strptime(start_str, "%Y-%m-%d")
        except ValueError:
            continue

        if is_current or not end_str:
            end = datetime.today()
        else:
            try:
                end = datetime.strptime(end_str, "%Y-%m-%d")
            except ValueError:
                continue

        months = (end.year - start.year) * 12 + (end.month - start.month)
        if months > 0:
            total_months += months

    return round(total_months / 12, 2)

def index_resume(resume_id, resume_text):
    # ✅ Step 1: Delete old chunks ONLY for this specific resume document
    frappe.db.delete("Resume Chunk", {"resume_id": resume_id})
    frappe.db.commit()

    # ✅ Step 2: Create chunks
    chunks = chunk_text(resume_text)
    if not chunks:
        return

    chunk_docs = []
    for i, chunk in enumerate(chunks):
        chunk_doc = frappe.get_doc({
            "doctype": "Resume Chunk",
            "resume_id": resume_id,  # Link directly to the Resume DocType
            "chunk_index": i,
            "chunk_text": chunk
        })
        chunk_doc.insert(ignore_permissions=True)
        chunk_docs.append(chunk_doc)

    frappe.db.commit()

    # ✅ Step 3: Embeddings
    embeddings = embed_texts([d.chunk_text for d in chunk_docs])

    meta = []
    for doc in chunk_docs:
        meta.append({
            "resume_id": resume_id,  # Store the Resume ID in FAISS
            "resume_chunk": doc.name
        })

    add_embeddings(embeddings, meta)



# import base64

# def parse_with_gemini_file(file_path):
#     model = get_gemini()

#     with open(file_path, "rb") as f:
#         pdf_bytes = f.read()

#     prompt = PROMPT

#     response = model.generate_content(
#         [
#             {"mime_type": "application/pdf", "data": pdf_bytes},
#             prompt
#         ]
#     )
    
#     text = response.text.strip()

#     if text.startswith("```"):
#         text = text.replace("```json", "").replace("```", "").strip()

#     return json.loads(text)

# def resume(doc, method=None):
#     """
#     FAST HOOK: Returns instantly to Next.js, pushes heavy AI parsing to the background.
#     """
#     # 1. Set status instantly so frontend knows it is processing
#     doc.db_set("parse_status", "Pending")
    
#     # 2. Trigger your exact logic in the background
#     frappe.enqueue(
#         "vaaman_ats_ai.api.resume.resume.process_resume_bg",
#         doc_name=doc.name,
#         queue="long",
#         timeout=300
#     )


def flatten_resume_data(parsed):
    return {
        # "candidate_name": f"{parsed.get('first_name', '')} {parsed.get('last_name', '')}".strip(),

        "experience_years": parsed.get("experience_years", 0),
        "location": parsed.get("location", 0),

        "skills": ", ".join([
            s.get("skill_name", "") for s in parsed.get("skills", [])
        ]),

        "current_role": (
            parsed.get("experience", [{}])[0].get("role", "")
            if parsed.get("experience") else ""
        ),

        "degree": (
            parsed.get("education", [{}])[0].get("degree", "")
            if parsed.get("education") else ""
        ),

        "institution": (
            parsed.get("education", [{}])[0].get("institution", "")
            if parsed.get("education") else ""
        )
        
    }
    
def index_resume_bg(resume_id, resume_text):
    frappe.log_error("Embedding started...")
    
    # ✅ Optional: Verify Job Applicant exists
    # if not frappe.db.exists("Job Applicant", job_applicant_id):
    #     frappe.log_error(f"Job Applicant not found: {job_applicant_id}")
    #     return
    
    index_resume(resume_id, resume_text)
    
def create_resume_from_upload(applicant_data, file_url, job_opening=None, applicant_doc=None):
    # import json

    # ✅ Avoid duplicate resume
    # email = applicant_data.get("email") or applicant_data.get("email_id")
    # if email and frappe.db.exists("Resume", {"email": email}):
    #     return
    
    # ✅ Calculate and inject into parsed JSON
    # applicant_data["experience_years"] = calculate_experience_years(applicant_data.get("experience", []))

    # ✅ Create Resume Doc
    # doc = frappe.get_doc({
    #     "doctype": "Resume",
    #     "candidate_name": applicant_data.get("applicant_name"),
    #     "email": email,
    #     "phone": applicant_data.get("phone_number") or applicant_data.get("phone"),
    #     "resume_file": file_url,

    #     # 🔥 Most important for AI
    #     "parsed_json": json.dumps(applicant_data),

    #     "parse_status": "Parsed"  # already parsed
    # })

    # doc.insert(ignore_permissions=True)
    
    

    # ✅ Flatten data (reuse your logic)
    # flat_data = flatten_resume_data(applicant_data)

    # doc.db_set("experience_years", flat_data["experience_years"])
    # doc.db_set("location", flat_data["location"])
    # doc.db_set("skills", flat_data["skills"])
    # doc.db_set("current_role", flat_data["current_role"])
    # doc.db_set("degree", flat_data["degree"])
    # doc.db_set("institution", flat_data["institution"])

    # ✅ Direct embedding (NO Gemini again)
    resume_text = json.dumps(applicant_data)
    # index_resume(doc.name, resume_text)
    # return resume_text
    # frappe.log_error(applicant_doc.name)
    # frappe.log_error(
    #     # message=frappe.get_traceback(),
    #     message=applicant_doc.name,
    #     title=f"Resume Error: {applicant_doc.name}"
    # )
    
    frappe.enqueue(
        "vaaman_ats_ai.api.resume.resume.index_resume_bg",
        resume_id=applicant_doc.name,
        resume_text=resume_text,
        queue="long",
        timeout=300
    )

    return applicant_doc.name



# def process_resume_bg(doc_name):
#     """
#     This is your exact original code, just running in the background!
#     """
#     doc = frappe.get_doc("Resume", doc_name)
#     logger = frappe.logger("resume_parser", allow_site=True)

#     logger.info("===== RESUME PARSER STARTED =====")
#     logger.info(f"Doc: {doc.name}")
#     logger.info(f"File URL: {doc.resume_file}")

#     try:
#         if not doc.resume_file:
#             logger.warning("No resume file attached.")
#             return

#         if doc.parse_status == "Parsed":
#             logger.info("Already parsed. Skipping.")
#             return

#         try:
#             file_doc = frappe.get_doc("File", {"file_url": doc.resume_file})
#             file_path = file_doc.get_full_path()
#             logger.info(f"File path: {file_path}")
#         except Exception:
#             frappe.log_error(title="Resume Parser: File Lookup Failed", message=frappe.get_traceback())
#             doc.db_set("parse_status", "File Not Found")
#             return

        
#         logger.info("Sending resume to Gemini for parsing...")

#         logger.info("Parsing with LLM...")
#         parsed = parse_with_gemini_file(file_path)
#         logger.info("Parsing completed")
        
#         # ✅ Calculate and inject into parsed JSON
#         parsed["experience_years"] = calculate_experience_years(parsed.get("experience", []))
        
#         flat_data = flatten_resume_data(parsed)

#         # ✅ Save flattened fields
#         # doc.db_set("candidate_name", flat_data["candidate_name"])
#         doc.db_set("experience_years", flat_data["experience_years"])
#         doc.db_set("skills", flat_data["skills"])
#         doc.db_set("current_role", flat_data["current_role"])
#         doc.db_set("degree", flat_data["degree"])
#         doc.db_set("institution", flat_data["institution"])


#         # Use db_set instead of save() in background jobs to prevent infinite loops
#         doc.db_set("parsed_json", json.dumps(parsed, indent=2))
#         doc.db_set("parse_status", "Parsed")
        
#         # ✅ Index resume into FAISS
#         resume_text = json.dumps(parsed)  # use parsed JSON as text source
#         index_resume(doc.name, resume_text)
#         # frappe.enqueue(
#         #     "vaaman_ats_ai.api.resume.resume.index_resume_bg",
#         #     resume_id=doc.name,
#         #     resume_text=resume_text,
#         #     queue="long",
#         #     timeout=300
#         # )

#         logger.info("Resume parsed successfully")

#     except Exception as e:
#         frappe.log_error(title=f"Resume Parser Failed: {doc.name}", message=frappe.get_traceback())
#         doc.db_set("parse_status", "Failed")


# def match_job_opening_with_ai(email_subject, email_body, job_openings):
#     """
#     Use Gemini AI to match email content to the best Job Opening.
    
#     Args:
#         email_subject: Email subject line
#         email_body: Email message body
#         job_openings: List of dicts with job opening info
    
#     Returns:
#         job_opening_name: Best matching Job Opening name or None
#     """
#     try:
#         model = get_gemini()
        
#         # Prepare job openings context for AI
#         jobs_context = ""
#         for job in job_openings:
#             jobs_context += f"""
# Job ID: {job.get('name')}
# Title: {job.get('job_title')}
# Department: {job.get('department', 'N/A')}
# Description: {job.get('description', '')[:500]}...
# Requirements: {job.get('requirements', '')[:300]}...
# ---
# """
        
#         # Create intelligent matching prompt
#         prompt = f"""
# You are an intelligent job matching assistant.

# EMAIL TO ANALYZE:
# Subject: {email_subject}
# Body: {email_body[:1000]}

# AVAILABLE JOB OPENINGS:
# {jobs_context}

# TASK:
# Analyze the email and identify which Job Opening the applicant is applying for.
# Look for:
# - Explicit job title mentions
# - Job reference IDs
# - Department mentions
# - Skills/experience that match specific roles
# - Context clues in the email

# RESPONSE FORMAT:
# Return ONLY valid JSON with this structure:
# {{
#   "matched_job_id": "Job Opening ID or null",
#   "confidence": "high/medium/low",
#   "reasoning": "Brief explanation of why this match was made"
# }}

# RULES:
# - If no clear match, return "matched_job_id": null
# - If multiple possible matches, choose the best one based on context
# - Prioritize explicit mentions over inferred matches
# - Be conservative - only match if reasonably confident
# """
        
#         response = model.generate_content(prompt)
#         result_text = response.text.strip()
        
#         # Clean response if it has markdown
#         if result_text.startswith("```"):
#             result_text = result_text.replace("```json", "").replace("```", "").strip()
        
#         result = json.loads(result_text)
        
#         # Verify the matched job exists
#         if result.get("matched_job_id"):
#             if frappe.db.exists("Job Opening", result["matched_job_id"]):
#                 frappe.log_error(
#                     title="Job Matching Success",
#                     message=f"Matched: {result['matched_job_id']} (Confidence: {result.get('confidence')}) - {result.get('reasoning')}"
#                 )
#                 return result["matched_job_id"]
        
#         frappe.log_error(
#             title="Job Matching - No Clear Match",
#             message=f"Confidence: {result.get('confidence')} - {result.get('reasoning')}"
#         )
#         return None
        
#     except Exception as e:
#         frappe.log_error(
#             title="Job Matching AI Error",
#             message=f"Error: {str(e)}\n{frappe.get_traceback()}"
#         )
#         return None  # Fallback to None if AI fails
    
    
def extract_json_from_response(text: str) -> dict | None:
    """Safely extract JSON from LLM response text."""
    text = text.strip()
    
    # Remove markdown code blocks if present
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    
    # Find JSON object boundaries
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = text[start_idx:end_idx+1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Try fixing common issues: trailing commas, single quotes
            import re
            json_str = re.sub(r",\s*}", "}", json_str)  # Remove trailing comma
            json_str = re.sub(r",\s*]", "]", json_str)
            json_str = json_str.replace("'", '"')  # Single to double quotes
            try:
                return json.loads(json_str)
            except:
                pass
    return None


def _validate_ai_result(result: dict, ai_provider: str = "unknown") -> dict:
    """Sanitize AI output to match expected schema and attach AI provider name."""
    return {
        "job_opening": (
            result.get("matched_job_id") 
            if result.get("matched_job_id") and frappe.db.exists("Job Opening", result["matched_job_id"]) 
            else None
        ),
        "confidence": (
            result.get("match_confidence", "low") 
            if result.get("match_confidence") in ["high", "medium", "low"] 
            else "low"
        ),
        "fit_level": (
            result.get("fit_level") 
            if result.get("fit_level") in ["Strong Fit", "Moderate Fit", "Weak Fit", "Unable to Assess"] 
            else "Unable to Assess"
        ),
        "score": min(100, max(0, int(result.get("score", 0) or 0))),
        "justification": (result.get("justification_by_ai") or "")[:200],
        
        "ai_provider": ai_provider  # ✅ NAYA FLAG: Ye batayega ki kis AI ne kaam kiya
    }



def _safe_fallback_result(reason: str, is_error: bool = True, ai_provider: str = "none") -> dict:
    """Return safe defaults when AI fails."""
    return {
        "job_opening": None,
        "confidence": "low",
        "fit_level": "Unable to Assess",
        "score": 0,
        "justification": f"AI unavailable: {reason}",
        "api_failed": is_error,
        
        "ai_provider": ai_provider  # ✅ NAYA FLAG
    }
    
def get_active_job_openings_cached(ttl_sec=300):
    """Load open job openings once per worker; cache 5 min to avoid repeated DB hits."""
    cache_key = "ats_active_job_openings"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached
    openings = frappe.get_all(
        "Job Opening",
        filters={"status": "Open"},
        fields=["name", "job_title", "department", "description"],
    )
    frappe.cache().set_value(cache_key, openings, expires_in_sec=ttl_sec)
    return openings


def _normalize_email_subject(email_subject):
    return re.sub(
        r"^(?:\s*(?:re|fwd|fw)\s*:\s*)+",
        "",
        (email_subject or "").strip(),
        flags=re.IGNORECASE,
    ).lower()


def _score_job_against_email(job, subject_norm, body_norm=""):
    """Heuristic score 0–100 — no AI."""
    job_name = (job.get("name") or "").strip()
    title = (job.get("job_title") or "").strip().lower()
    dept = (job.get("department") or "").strip().lower()
    text = f"{subject_norm} {body_norm}"

    if job_name and job_name.lower() in subject_norm:
        return 100
    if title and len(title) >= 4 and title in subject_norm:
        return 90
    if dept and len(dept) >= 3 and dept in text:
        return 75

    title_tokens = {
        t for t in re.findall(r"[a-z0-9]{4,}", title) if t not in _SUBJECT_STOPWORDS
    }
    text_tokens = {
        t for t in re.findall(r"[a-z0-9]{4,}", text) if t not in _SUBJECT_STOPWORDS
    }
    overlap = len(title_tokens & text_tokens)
    if overlap >= 3:
        return 70
    if overlap >= 2:
        return 55
    if overlap >= 1:
        return 40
    return 0


def match_job_opening_from_subject(email_subject, job_openings, email_body=None):
    """Keyword match from email subject/body — no AI cost."""
    if not email_subject or not job_openings:
        return None

    subject_norm = _normalize_email_subject(email_subject)
    body_norm = (email_body or "")[:500].lower()

    best_job = None
    best_score = 0

    for job in job_openings:
        score = _score_job_against_email(job, subject_norm, body_norm)
        if score > best_score:
            best_score = score
            best_job = job

    if not best_job or best_score < 45:
        return None

    return {
        "job_opening": best_job.get("name"),
        "confidence": "high" if best_score >= 85 else "medium",
        "fit_level": "Unable to Assess",
        "score": 0,
        "justification": "Matched from email subject keywords (no AI)",
        "ai_provider": "keyword",
    }


def narrow_job_openings_for_match(email_subject, email_body, job_openings, max_jobs=5):
    """Keep only the most likely job openings for the AI prompt (faster Ollama/Gemini)."""
    if not job_openings:
        return []
    if len(job_openings) <= max_jobs:
        return job_openings

    subject_norm = _normalize_email_subject(email_subject)
    body_norm = (email_body or "")[:500].lower()

    scored = []
    for job in job_openings:
        score = _score_job_against_email(job, subject_norm, body_norm)
        if score > 0:
            scored.append((score, job))

    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        return [job for _, job in scored[:max_jobs]]

    return job_openings[:max_jobs]


def match_job_opening_for_email(email_subject, email_body, job_openings, use_cache=True):
    """
    Fast job match for career emails:
    1) cache by normalized subject
    2) keyword match (free)
    3) if not matched, Gemini fallback (job_matching_model)
    """
    if not job_openings:
        return _safe_fallback_result("No open jobs")

    if len(job_openings) == 1:
        return {
            "job_opening": job_openings[0].get("name"),
            "confidence": "high",
            "fit_level": "Unable to Assess",
            "score": 0,
            "justification": "Single active job opening auto-mapped",
            "ai_provider": "single_job",
        }

    subject_norm = _normalize_email_subject(email_subject)
    cache_key = f"job_match:gemini:{hash(subject_norm)}:{len(job_openings)}"
    if use_cache:
        cached = frappe.cache().get_value(cache_key)
        if cached:
            cached = dict(cached)
            cached["ai_provider"] = "cached"
            return cached

    keyword = match_job_opening_from_subject(email_subject, job_openings, email_body)
    if keyword:
        if use_cache:
            frappe.cache().set_value(cache_key, keyword, expires_in_sec=3600)
        return keyword

    narrowed = narrow_job_openings_for_match(email_subject, email_body, job_openings)
    result = match_job_opening_hybrid(
        email_subject=email_subject,
        email_body=email_body,
        job_openings=narrowed,
    )

    if use_cache and result and result.get("job_opening"):
        frappe.cache().set_value(cache_key, result, expires_in_sec=3600)
    return result


_SUBJECT_STOPWORDS = {
    "application",
    "apply",
    "applying",
    "candidate",
    "career",
    "email",
    "engineer",
    "fresher",
    "graduate",
    "hiring",
    "interview",
    "job",
    "opening",
    "position",
    "resume",
    "subject",
    "trainee",
    "vaaman",
}


def _get_job_matching_model():
    """Separate model for job matching so resume parsing can stay on higher-quality model."""
    default_model = frappe.conf.get("job_matching_model") or "gemini-1.5-flash"
    try:
        row = frappe.db.sql(
            """
            SELECT value
            FROM `tabSingles`
            WHERE doctype='ATS Settings' AND field='job_matching_model'
            LIMIT 1
            """,
            as_dict=True,
        )
        if row and row[0].get("value"):
            return row[0]["value"]
    except Exception:
        pass
    return default_model


def _gemini_model_candidates():
    configured = _get_job_matching_model()
    # Prefer cheap model for job matching; fallback to higher quality only if needed.
    fallbacks = ["gemini-1.5-flash", get_configured_gemini_model(), "gemini-2.5-flash"]
    seen = set()
    ordered = []
    for model_name in [configured] + fallbacks:
        if model_name and model_name not in seen:
            seen.add(model_name)
            ordered.append(model_name)
    return ordered


def match_job_opening_with_gemini(email_subject, email_body, job_openings, resume_data=None, max_retries=1):
    jobs_context = "\n".join([
        f"ID:{j['name']} | {j['job_title']} | {j.get('department','')}\n"
        f"{j.get('description','')[:120]}"
        for j in job_openings
    ])

    prompt = f"""
You are an HR AI.

EMAIL:
Subject: {email_subject}
Body: {email_body[:400]}

JOBS:
{jobs_context}

Return ONLY JSON:
{{
  "matched_job_id": "id or null",
  "confidence": "high|medium|low",
  "fit_level": "Strong Fit|Moderate Fit|Weak Fit|Unable to Assess",
  "score": 0-100,
  "justification": "short reason"
}}
"""

    last_error = None
    for model_name in _gemini_model_candidates():
        for attempt in range(max_retries):
            try:
                model = get_gemini(model_name=model_name)
                response = model.generate_content(prompt)
                text = (response.text or "").strip()
                result = extract_json_from_response(text)

                if not result:
                    last_error = f"invalid_json:{model_name}"
                    continue

                return _validate_ai_result({
                    "matched_job_id": result.get("matched_job_id"),
                    "match_confidence": result.get("confidence"),
                    "fit_level": result.get("fit_level"),
                    "score": result.get("score"),
                    "justification_by_ai": result.get("justification")
                }, ai_provider=f"gemini:{model_name}")
            except Exception:
                last_error = f"{model_name}: {frappe.get_traceback()}"
                # Retry same model quickly once, then move to next fallback model.
                continue

    frappe.log_error(
        title="Gemini job matching failed",
        message=str(last_error or "Unknown Gemini failure"),
    )
    return _safe_fallback_result("Gemini failed", is_error=True, ai_provider="gemini_failed")
    
def _apply_keyword_job_fallback(result, email_subject, job_openings):
    """If AI did not match a job, try free subject keyword match."""
    if result and result.get("job_opening"):
        return result
    keyword = match_job_opening_from_subject(email_subject, job_openings)
    return keyword or result


def match_job_opening_hybrid(email_subject, email_body, job_openings, resume_data=None):
    """Job match using ATS Settings ai_mode: gemini | hybrid | ollama (deprecated)."""

    # Caller should use match_job_opening_for_email(); keep keyword-first here as safety net.
    keyword = match_job_opening_from_subject(email_subject, job_openings, email_body)
    if keyword:
        return keyword

    mode = frappe.db.get_single_value("ATS Settings", "ai_mode") or frappe.conf.get("ai_mode", "gemini")

    if mode in ("ollama", "hybrid"):
        # Keep backward compatibility for old settings values while avoiding Ollama instability.
        frappe.logger().warning(
            f"ai_mode '{mode}' requested; routing to Gemini-only matcher"
        )

    result = match_job_opening_with_gemini(
        email_subject, email_body, job_openings, resume_data
    )
    return _apply_keyword_job_fallback(result, email_subject, job_openings)
    
