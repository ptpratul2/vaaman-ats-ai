# import frappe
# import json
# from vaaman_ats_ai.api.resume.embedder import embed_texts
# from vaaman_ats_ai.api.resume.vector_store import search_similar
# from vaaman_ats_ai.api.resume.gemini import get_gemini

# # -----------------------------
# # 1️⃣ LLM Generation Function
# # -----------------------------
# def chat_with_llm(context, question, history=None):
#     model = get_gemini()

#     # Format the history into a string
#     history_text = ""
#     if history:
#         for msg in history:
#             role = "User" if msg.get("role") == "user" else "Assistant"
#             history_text += f"{role}: {msg.get('content')}\n"

#     prompt = f"""
# You are an resume intelligence AI assistant. You help recruiters find and evaluate candidates based on their resumes.

# You can answer questions about:
# - Candidate skills and experience
# - Education and qualifications  
# - Work history and roles
# - Comparing candidates
# - Answer ONLY questions relevant to recruitment decisions (skills, experience, education)
# - Do NOT volunteer candidate personal details (email, phone, address) unless explicitly asked
# - Do NOT reveal candidate names unless directly asked about a specific person
# - If asked for contact details, say: "Please access candidate contact info through the official profile page"
# - If the answer is not found in the resumes, say: "Not found in the uploaded resumes."

# If the question is not related to the resume data provided, politely explain what types of questions you can answer.
# If the answer is not found in the resumes, say: "Not found in the uploaded resumes."

# Context:
# {context}

# Question:
# {question}
# """
#     # result = model.generate_content(prompt, stream=True)
#     result = model.generate_content(prompt)
#     return result.text.strip()
#     # return result


# # -----------------------------
# # NEW: Sidebar & Session APIs
# # -----------------------------
# @frappe.whitelist()
# def get_chat_sessions(search_text=None):
#     """Returns a list of past chats for the sidebar, specific to the logged-in HR user."""
#     # Ensure guest cannot see chats
#     if frappe.session.user == "Guest":
#         frappe.throw("Authentication required", frappe.AuthenticationError)
        
#     filters = {"user": frappe.session.user}
#     if search_text:
#         filters["title"] = ["like", f"%{search_text}%"]

#     sessions = frappe.get_all(
#         "AI Chat Session",
#         filters=filters,
#         fields=["name", "title", "creation", "is_pinned"],
#         # Order by Pinned first, then newest creation date
#         order_by="is_pinned desc, creation desc"
#     )
#     return {"success": True, "sessions": sessions}

# @frappe.whitelist()
# def toggle_pin_session(session_id):
#     doc = frappe.get_doc("AI Chat Session", session_id)
#     if doc.user != frappe.session.user:
#         frappe.throw("Not permitted", frappe.PermissionError)
    
#     doc.is_pinned = 0 if doc.is_pinned else 1
#     doc.save(ignore_permissions=True)
#     return {"success": True, "is_pinned": doc.is_pinned}

# @frappe.whitelist()
# def delete_session(session_id):
#     doc = frappe.get_doc("AI Chat Session", session_id)
#     if doc.user != frappe.session.user:
#         frappe.throw("Not permitted", frappe.PermissionError)
    
#     frappe.delete_doc("AI Chat Session", session_id)
#     return {"success": True}

# @frappe.whitelist()
# def get_session_history(session_id):
#     """Loads the full message history when a user clicks a chat in the sidebar."""
#     if not frappe.db.exists("AI Chat Session", session_id):
#         return {"success": False, "error": "Session not found"}
        
#     doc = frappe.get_doc("AI Chat Session", session_id)
    
#     # Security check: Ensure the HR user owns this chat
#     if doc.user != frappe.session.user:
#         frappe.throw("Not permitted", frappe.PermissionError)

#     messages = json.loads(doc.messages or "[]")
#     return {"success": True, "messages": messages, "title": doc.title}

# # -----------------------------
# # 2️⃣ Main API Endpoint
# # -----------------------------
# @frappe.whitelist(allow_guest=True)
# # @frappe.validate_and_sanitize_search_inputs
# # @frappe.whitelist()
# def chat_query(question=None, filters=None, response_format="text", history=None, session_id=None):
#     try:
#         # -----------------------------
#         # Normalize inputs
#         # -----------------------------
#         if isinstance(filters, str):
#             filters = json.loads(filters)
            
#         if isinstance(history, str):
#             history = json.loads(history)
            
#         filters = filters or {}

#         if not question:
#             return {"success": False, "error": "Question is required"}

#         # -----------------------------
#         # Database Filtering (List Queries)
#         # -----------------------------
#         # Detect if user wants a list instead of an AI text answer
#         is_list_query = any(word in question.lower() for word in ["find all", "show me all", "list candidates", "how many"])
        
#         # Example: Direct DB query for "React"
#         if is_list_query and "react" in question.lower():
#             # Get all resumes
#             resumes = frappe.get_all("Resume", fields=["name", "parsed_json"])
            
#             rows = []
#             for r in resumes:
#                 parsed = json.loads(r.get("parsed_json") or "{}")
#                 skills = [s.get("skill_name", "").lower() for s in parsed.get("skills", [])]
                
#                 if "react" in skills or "react js" in skills:
#                     first_name = parsed.get("first_name", "")
#                     last_name = parsed.get("last_name", "")
                    
#                     rows.append({
#                         "Name": f"{first_name} {last_name}".strip() or "Unknown",
#                         "Email": parsed.get("email", "N/A"),
#                         "Phone": parsed.get("phone", "N/A"),
#                         "Match": "React JS"
#                     })
                    
#             return {
#                 "success": True,
#                 "format": "table",
#                 "answer": f"I found {len(rows)} candidates matching your criteria.",
#                 "rows": rows
#             }

#         # -----------------------------
#         # Vector Store Search (Semantic AI Queries)
#         # -----------------------------
#         query_vector = embed_texts([question])[0]
#         matches = search_similar(query_vector, top_k=10)

#         if not matches:
#             return {
#                 "success": True,
#                 "answer": "No relevant information found in the uploaded resumes.",
#                 "sources": []
#             }

#         # Fetch the chunks based on FAISS matches
#         chunk_ids = [m["resume_chunk"] for m in matches]
#         chunks = frappe.get_all(
#             "Resume Chunk",
#             filters={"name": ["in", chunk_ids]},
#             fields=["chunk_text", "resume_id"] # Fetching by resume_id instead of profile
#         )

       
#         # -----------------------------
#         # Download Intent Filter
#         # -----------------------------
#         download_keywords = ["download", "pdf", "file", "provide", "share", "get", "contact", "email", "phone"]
#         question_lower = question.lower()
#         user_wants_file = any(word in question.lower() for word in download_keywords)

#         # -----------------------------
#         # Build Context & Source Links
#         # -----------------------------
#         raw_sources = {}
#         context_parts = []
#         mentioned_resume_ids = set() # Track if the user explicitly asked for a specific person

#         for c in chunks:
#             resume_id = c["resume_id"]
            
#             resume_doc = frappe.db.get_value(
#                 "Resume", 
#                 resume_id, 
#                 ["resume_file", "parsed_json"], 
#                 as_dict=True
#             )

#             if resume_doc:
#                 parsed = json.loads(resume_doc.parsed_json or "{}")
#                 first_name = parsed.get("first_name", "")
#                 last_name = parsed.get("last_name", "")
#                 candidate_name = f"{first_name} {last_name}".strip() or "Unknown Candidate"
                
#                 # NEW: Check if this specific candidate's name is in the user's prompt
#                 if (first_name and first_name.lower() in question_lower) or (last_name and last_name.lower() in question_lower):
#                     mentioned_resume_ids.add(resume_id)

#                 # Always add the text to the context so the AI can answer the question
#                 context_parts.append(f"Candidate: {candidate_name}\n{c['chunk_text']}")

#                 # NEW: ONLY add data to the sources array if they want the file
#                 # Otherwise, it stays completely empty and hides the UI options!
#                 if user_wants_file:
#                     raw_sources[resume_id] = {
#                         "candidate": candidate_name,
#                         "download_url": resume_doc.resume_file
#                     }

#         # -----------------------------
#         # Filter Sources before sending to UI
#         # -----------------------------
#         unique_sources = {}
#         if user_wants_file:
#             for rid, source_data in raw_sources.items():
#                 # If the user typed specific names (like "Rani"), ONLY show buttons for them
#                 if len(mentioned_resume_ids) > 0:
#                     if rid in mentioned_resume_ids:
#                         unique_sources[rid] = source_data
#                 # If they didn't specify a name (e.g., "provide resumes of all React devs"), show all retrieved
#                 else:
#                     unique_sources[rid] = source_data
#         # -----------------------------
#         # Generate Final Answer
#         # -----------------------------
#         context = "\n\n".join(context_parts)
#         answer = chat_with_llm(context, question, history=history)
        
#         # 1. Prepare the new Assistant message object
#         assistant_message = {
#             "role": "assistant",
#             "content": answer,
#             "sources": list(unique_sources.values())
#         }
        
#         # 2. Database Persistence Logic
#         if not session_id:
#             # Create a brand new session if this is the first message
#             # Create a short title based on the first question (first 30 chars)
#             short_title = question[:30] + "..." if len(question) > 30 else question
            
#             new_session = frappe.get_doc({
#                 "doctype": "AI Chat Session",
#                 "title": short_title,
#                 "user": frappe.session.user,
#                 "messages": json.dumps([
#                     {"role": "user", "content": question},
#                     assistant_message
#                 ])
#             })
#             new_session.insert(ignore_permissions=True)
#             session_id = new_session.name
#         else:
#             # Update an existing session
#             session_doc = frappe.get_doc("AI Chat Session", session_id)
#             current_messages = json.loads(session_doc.messages or "[]")
            
#             # Append both the new user question and the AI answer
#             current_messages.append({"role": "user", "content": question})
#             current_messages.append(assistant_message)
            
#             session_doc.messages = json.dumps(current_messages)
#             session_doc.save(ignore_permissions=True)

#         return {
#             "success": True,
#             "answer": answer,
#             "sources": list(unique_sources.values()),
#             "session_id": session_id # Tell the frontend what session we are in
#         }

#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "Chat API Error")
#         return {
#             "success": False,
#             "error": str(e)
#         }

import frappe
import json
from vaaman_ats_ai.api.resume.embedder import embed_texts
from vaaman_ats_ai.api.resume.vector_store import search_similar
from vaaman_ats_ai.api.resume.gemini import get_gemini

# -----------------------------
# 1️⃣ LLM Generation Function
# -----------------------------
def chat_with_llm(context, question, history=None):
    model = get_gemini()

    # Format the history into a string
    history_text = ""
    if history:
        for msg in history:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_text += f"{role}: {msg.get('content')}\n"

    prompt = f"""
You are an resume intelligence AI assistant. You help recruiters find and evaluate candidates based on their resumes.

You can answer questions about:
- Candidate skills and experience
- Education and qualifications  
- Work history and roles
- Comparing candidates
- Answer ONLY questions relevant to recruitment decisions (skills, experience, education)
- Do NOT volunteer candidate personal details (email, phone, address) unless explicitly asked
- Do NOT reveal candidate names unless directly asked about a specific person
- If asked for contact details, say: "Please access candidate contact info through the official profile page"
- If the answer is not found in the resumes, say: "Not found in the uploaded resumes."

If the question is not related to the resume data provided, politely explain what types of questions you can answer.
If the answer is not found in the resumes, say: "Not found in the uploaded resumes."

Context:
{context}

Question:
{question}
"""
    # result = model.generate_content(prompt, stream=True)
    result = model.generate_content(prompt)
    return result.text.strip()
    # return result


# -----------------------------
# NEW: Sidebar & Session APIs
# -----------------------------
@frappe.whitelist()
def get_chat_sessions(search_text=None):
    """Returns a list of past chats for the sidebar, specific to the logged-in HR user."""
    # Ensure guest cannot see chats
    if frappe.session.user == "Guest":
        frappe.throw("Authentication required", frappe.AuthenticationError)
        
    filters = {"user": frappe.session.user}
    if search_text:
        filters["title"] = ["like", f"%{search_text}%"]

    sessions = frappe.get_all(
        "AI Chat Session",
        filters=filters,
        fields=["name", "title", "creation", "is_pinned"],
        # Order by Pinned first, then newest creation date
        order_by="is_pinned desc, creation desc"
    )
    return {"success": True, "sessions": sessions}

@frappe.whitelist()
def toggle_pin_session(session_id):
    doc = frappe.get_doc("AI Chat Session", session_id)
    if doc.user != frappe.session.user:
        frappe.throw("Not permitted", frappe.PermissionError)
    
    doc.is_pinned = 0 if doc.is_pinned else 1
    doc.save(ignore_permissions=True)
    return {"success": True, "is_pinned": doc.is_pinned}

@frappe.whitelist()
def delete_session(session_id):
    doc = frappe.get_doc("AI Chat Session", session_id)
    if doc.user != frappe.session.user:
        frappe.throw("Not permitted", frappe.PermissionError)
    
    frappe.delete_doc("AI Chat Session", session_id)
    return {"success": True}

@frappe.whitelist()
def get_session_history(session_id):
    """Loads the full message history when a user clicks a chat in the sidebar."""
    if not frappe.db.exists("AI Chat Session", session_id):
        return {"success": False, "error": "Session not found"}
        
    doc = frappe.get_doc("AI Chat Session", session_id)
    
    # Security check: Ensure the HR user owns this chat
    if doc.user != frappe.session.user:
        frappe.throw("Not permitted", frappe.PermissionError)

    messages = json.loads(doc.messages or "[]")
    return {"success": True, "messages": messages, "title": doc.title}

# -----------------------------
# 2️⃣ Main API Endpoint
# -----------------------------
@frappe.whitelist(allow_guest=True)
# @frappe.validate_and_sanitize_search_inputs
# @frappe.whitelist()
def chat_query(question=None, filters=None, response_format="text", history=None, session_id=None):
    try:
        # -----------------------------
        # Normalize inputs
        # -----------------------------
        if isinstance(filters, str):
            filters = json.loads(filters)
            
        if isinstance(history, str):
            history = json.loads(history)
            
        filters = filters or {}

        if not question:
            return {"success": False, "error": "Question is required"}

        # -----------------------------
        # Database Filtering (List Queries)
        # -----------------------------
        # Detect if user wants a list instead of an AI text answer
        is_list_query = any(word in question.lower() for word in ["find all", "show me all", "list candidates", "how many"])
        
        # Example: Direct DB query for "React"
        if is_list_query and "react" in question.lower():
            # Get all resumes
            # resumes = frappe.get_all("Resume", fields=["name", "parsed_json"])
            resumes = frappe.get_all("Job Applicant", fields=["name", "custom_parsed_json"])
            
            rows = []
            for r in resumes:
                parsed = json.loads(r.get("custom_parsed_json") or "{}")
                skills = [s.get("skill_name", "").lower() for s in parsed.get("skills", [])]
                
                if "react" in skills or "react js" in skills:
                    first_name = parsed.get("first_name", "")
                    last_name = parsed.get("last_name", "")
                    
                    rows.append({
                        "Name": f"{first_name} {last_name}".strip() or "Unknown",
                        "Email": parsed.get("email_id", "N/A"),
                        "Phone": parsed.get("phone_number", "N/A"),
                        "Match": "React JS"
                    })
                    
            return {
                "success": True,
                "format": "table",
                "answer": f"I found {len(rows)} candidates matching your criteria.",
                "rows": rows
            }

        # -----------------------------
        # Vector Store Search (Semantic AI Queries)
        # -----------------------------
        query_vector = embed_texts([question])[0]
        matches = search_similar(query_vector, top_k=10)

        if not matches:
            return {
                "success": True,
                "answer": "No relevant information found in the uploaded resumes.",
                "sources": []
            }

        # Fetch the chunks based on FAISS matches
        chunk_ids = [m["resume_chunk"] for m in matches]
        chunks = frappe.get_all(
            "Resume Chunk",
            filters={"name": ["in", chunk_ids]},
            fields=["chunk_text", "resume_id"] # Fetching by resume_id instead of profile
        )

       
        # -----------------------------
        # Download Intent Filter
        # -----------------------------
        download_keywords = ["download", "pdf", "file", "provide", "share", "get", "contact", "email", "phone"]
        question_lower = question.lower()
        user_wants_file = any(word in question.lower() for word in download_keywords)

        # -----------------------------
        # Build Context & Source Links
        # -----------------------------
        raw_sources = {}
        context_parts = []
        mentioned_resume_ids = set() # Track if the user explicitly asked for a specific person

        for c in chunks:
            resume_id = c["resume_id"]
            
            resume_doc = frappe.db.get_value(
                "Job Applicant", 
                resume_id, 
                ["resume_attachment", "custom_parsed_json"], 
                as_dict=True
            )

            if resume_doc:
                parsed = json.loads(resume_doc.custom_parsed_json or "{}")
                first_name = parsed.get("first_name", "")
                last_name = parsed.get("last_name", "")
                candidate_name = f"{first_name} {last_name}".strip() or "Unknown Candidate"
                
                # NEW: Check if this specific candidate's name is in the user's prompt
                if (first_name and first_name.lower() in question_lower) or (last_name and last_name.lower() in question_lower):
                    mentioned_resume_ids.add(resume_id)

                # Always add the text to the context so the AI can answer the question
                context_parts.append(f"Candidate: {candidate_name}\n{c['chunk_text']}")

                # NEW: ONLY add data to the sources array if they want the file
                # Otherwise, it stays completely empty and hides the UI options!
                if user_wants_file:
                    raw_sources[resume_id] = {
                        "candidate": candidate_name,
                        "download_url": resume_doc.resume_attachment
                    }

        # -----------------------------
        # Filter Sources before sending to UI
        # -----------------------------
        unique_sources = {}
        if user_wants_file:
            for rid, source_data in raw_sources.items():
                # If the user typed specific names (like "Rani"), ONLY show buttons for them
                if len(mentioned_resume_ids) > 0:
                    if rid in mentioned_resume_ids:
                        unique_sources[rid] = source_data
                # If they didn't specify a name (e.g., "provide resumes of all React devs"), show all retrieved
                else:
                    unique_sources[rid] = source_data
        # -----------------------------
        # Generate Final Answer
        # -----------------------------
        context = "\n\n".join(context_parts)
        answer = chat_with_llm(context, question, history=history)
        
        # 1. Prepare the new Assistant message object
        assistant_message = {
            "role": "assistant",
            "content": answer,
            "sources": list(unique_sources.values())
        }
        
        # 2. Database Persistence Logic
        if not session_id:
            # Create a brand new session if this is the first message
            # Create a short title based on the first question (first 30 chars)
            short_title = question[:30] + "..." if len(question) > 30 else question
            
            new_session = frappe.get_doc({
                "doctype": "AI Chat Session",
                "title": short_title,
                "user": frappe.session.user,
                "messages": json.dumps([
                    {"role": "user", "content": question},
                    assistant_message
                ])
            })
            new_session.insert(ignore_permissions=True)
            session_id = new_session.name
        else:
            # Update an existing session
            session_doc = frappe.get_doc("AI Chat Session", session_id)
            current_messages = json.loads(session_doc.messages or "[]")
            
            # Append both the new user question and the AI answer
            current_messages.append({"role": "user", "content": question})
            current_messages.append(assistant_message)
            
            session_doc.messages = json.dumps(current_messages)
            session_doc.save(ignore_permissions=True)

        return {
            "success": True,
            "answer": answer,
            "sources": list(unique_sources.values()),
            "session_id": session_id # Tell the frontend what session we are in
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Chat API Error")
        return {
            "success": False,
            "error": str(e)
        }