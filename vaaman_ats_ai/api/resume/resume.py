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
from vaaman_ats_ai.api.resume.gemini import get_gemini

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

from datetime import datetime

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
    
    
import ollama
import json
import frappe

# ✅ Configurable via site_config.json
# OLLAMA_MODEL = frappe.conf.get("ollama_model", "gemma4:e2b")
OLLAMA_MODEL = frappe.conf.get("ollama_model", "gemma4:e2b")
OLLAMA_HOST = frappe.conf.get("ollama_host", "http://localhost:11434")

def get_ollama_client():
    """Initialize Ollama client with configurable host."""
    return ollama.Client(host=OLLAMA_HOST)

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

def match_job_opening_with_ai(email_subject, email_body, job_openings, resume_data=None, max_retries=2):
    """
    Match email + resume to Job Opening using Ollama + Gemma 2B.
    Returns: dict with job_opening, confidence, fit_level, score, justification
    """
    client = get_ollama_client()
    
    # ✅ Truncate context for Gemma 2B (~8K token limit)
    jobs_context = "\n".join([
        f"• ID:{j['name']} | {j['job_title']} ({j.get('department','N/A')})\n"
        f"  Desc:{j.get('description','')[:150]}...\n"
        f"  Reqs:{j.get('requirements','')[:100]}..."
        for j in job_openings
    ])

    resume_context = ""
    if resume_data:
        skills = ", ".join([s.get("skill_name","") for s in resume_data.get("skills",[])[:5]])
        resume_context = f"""[CANDIDATE]
Name:{resume_data.get('applicant_name','')}
Skills:{skills}
Exp:{resume_data.get('experience_years',0)}yrs
Role:{resume_data.get('current_role','N/A')}
Edu:{resume_data.get('degree','N/A')}@{resume_data.get('institution','N/A')}"""

    # ✅ Optimized prompt for small model + JSON output
    system_prompt = """You are an HR screening AI. Output ONLY valid JSON. No markdown, no explanations.
Required JSON schema:
{
  "matched_job_id": "Job Opening name or null",
  "match_confidence": "high"|"medium"|"low",
  "fit_level": "Strong Fit"|"Moderate Fit"|"Weak Fit"|"Unable to Assess",
  "score": 0-100,
  "justification_by_ai": "Max 20 words explaining match"
}
Rules: If unclear→null, be conservative, no fabricated data."""

    user_prompt = f"""[EMAIL]
Subject:{email_subject}
Body:{email_body[:600]}

{resume_context}

[OPEN_JOBS]
{jobs_context}

Match candidate to ONE job. Output JSON only."""

    for attempt in range(max_retries):
        try:
            response = client.chat(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                options={
                    "temperature": 0.1,      # Deterministic output
                    "num_ctx": 8192,         # Gemma 2B context window
                    "repeat_penalty": 1.1,   # Reduce repetition
                    "top_p": 0.9
                },
                keep_alive="5m"  # Keep model loaded for 5 min
            )
            
            content = response["message"]["content"]
            
            result = extract_json_from_response(content)
            
            if result and isinstance(result, dict):
                break
                
            frappe.log_error(
                title=f"Ollama JSON Parse Retry {attempt+1}",
                message=f"Raw: {content[:400]}"
            )
            
        except ollama.ResponseError as e:
            frappe.log_error(title="Ollama ResponseError", message=f"{e.status_code}: {e.error}")
            if attempt == max_retries - 1:
                return _safe_fallback_result("API Error")
        except Exception as e:
            frappe.log_error(title="Ollama Call Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            if attempt == max_retries - 1:
                return _safe_fallback_result("Processing Error")
    
    if not result:
        return _safe_fallback_result("No valid response")
    
    # ✅ Validate & sanitize output
    return _validate_ai_result(result)


def _validate_ai_result(result: dict) -> dict:
    """Sanitize AI output to match expected schema."""
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
        "justification": (result.get("justification_by_ai") or "")[:200]
    }


def _safe_fallback_result(reason: str) -> dict:
    """Return safe defaults when AI fails."""
    return {
        "job_opening": None,
        "confidence": "low",
        "fit_level": "Unable to Assess",
        "score": 0,
        "justification": f"AI unavailable: {reason}"
    }
    
def is_ollama_available():
    import shutil
    if not shutil.which("ollama"):
        return False

    try:
        client = get_ollama_client()
        client.list()
        return True
    except:
        return False
    
def match_job_opening_with_gemini(email_subject, email_body, job_openings, resume_data=None):
    try:
        model = get_gemini()

        jobs_context = "\n".join([
            f"ID:{j['name']} | {j['job_title']} | {j.get('department','')}\n"
            f"{j.get('description','')[:300]}"
            for j in job_openings
        ])

        prompt = f"""
You are an HR AI.

EMAIL:
Subject: {email_subject}
Body: {email_body[:800]}

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

        response = model.generate_content(prompt)
        text = response.text.strip()

        result = extract_json_from_response(text)

        if not result:
            return _safe_fallback_result("Gemini invalid response")

        return _validate_ai_result({
            "matched_job_id": result.get("matched_job_id"),
            "match_confidence": result.get("confidence"),
            "fit_level": result.get("fit_level"),
            "score": result.get("score"),
            "justification_by_ai": result.get("justification")
        })

    except Exception:
        frappe.log_error("Gemini fallback failed", frappe.get_traceback())
        return _safe_fallback_result("Gemini failed")
    
def match_job_opening_hybrid(email_subject, email_body, job_openings, resume_data=None):

    mode = frappe.conf.get("ai_mode", "hybrid")

    # ✅ Direct Gemini mode
    if mode == "gemini":
        return match_job_opening_with_gemini(
            email_subject, email_body, job_openings, resume_data
        )

    # ✅ Direct Ollama mode
    if mode == "ollama":
        if is_ollama_available():
            return match_job_opening_with_ai(
                email_subject, email_body, job_openings, resume_data
            )
        return _safe_fallback_result("Ollama not available")

    # ✅ Hybrid mode (default)
    try:
        if is_ollama_available():
            ollama_result = match_job_opening_with_ai(
                email_subject, email_body, job_openings, resume_data
            )
        else:
            ollama_result = _safe_fallback_result("Ollama not available")
    except Exception:
        frappe.log_error("Ollama crash", frappe.get_traceback())
        ollama_result = _safe_fallback_result("Ollama crash")

    # ✅ Fallback condition
    should_fallback = (
        not ollama_result.get("job_opening")
        or ollama_result.get("confidence") == "low"
        or ollama_result.get("fit_level") == "Unable to Assess"
        or ollama_result.get("score", 0) < 50
    )

    gemini_result = None

    if should_fallback:
        gemini_result = match_job_opening_with_gemini(
            email_subject, email_body, job_openings, resume_data
        )

    # ✅ Final decision
    final_result = gemini_result if (
        gemini_result and gemini_result.get("score", 0) > ollama_result.get("score", 0)
    ) else ollama_result

    return final_result
    

@frappe.whitelist(allow_guest=True)
def check_ollama_health():
    """Check if local Ollama server and model are available."""
    try:
        client = get_ollama_client()
        response = client.list()
        
        # ✅ Handle ollama library Pydantic response structure
        # response.models is a list of Model objects, not dicts
        model_names = []
        if hasattr(response, "models"):
            for m in response.models:
                # Model objects have .name or .model attribute
                name = getattr(m, "name", None) or getattr(m, "model", None) or str(m)
                model_names.append(name)
        elif isinstance(response, (list, tuple)):
            # Fallback for older library versions
            for m in response:
                if isinstance(m, dict):
                    model_names.append(m.get("name") or m.get("model") or "unknown")
                else:
                    model_names.append(getattr(m, "name", None) or getattr(m, "model", None) or str(m))
        
        frappe.log_error(
            title="Ollama Models Detected",
            message=f"Found models: {model_names}"
        )

        if OLLAMA_MODEL in model_names:
            return {
                "status": "ok",
                "model": OLLAMA_MODEL,
                "available_models": model_names,
                "host": "localhost"
            }
            
        return {
            "status": "warning",
            "message": f"Model '{OLLAMA_MODEL}' not found. Available: {model_names}",
            "available_models": model_names,
            "host": "localhost"
        }
        
    except Exception as e:
        frappe.log_error(
            title="Ollama Health Check Failed",
            message=f"{type(e).__name__}: {str(e)}\n{frappe.get_traceback()}"
        )
        return {
            "status": "error",
            "message": f"{type(e).__name__}: {str(e)}",
            "host": "localhost"
        }