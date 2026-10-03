# import frappe
# import json

# @frappe.whitelist(allow_guest=True)
# def search_candidates(filters=None):
#     # return "search_candidates API called with filters: "
#     if isinstance(filters, str):
#         filters = json.loads(filters)
        
#     # ✅ FIX 2: Handle None
#     if not filters:
#         filters = {}

#     resumes = frappe.get_all(
#         "Resume",
#         fields=["name", "parsed_json"]
#     )

#     results = []

#     for r in resumes:
#         if not r.parsed_json:
#             continue

#         data = json.loads(r.parsed_json)

#         # 🔹 Experience Filter
#         exp = data.get("experience_years", 0)
#         if filters.get("min_exp") and exp < filters["min_exp"]:
#             continue
#         if filters.get("max_exp") and exp > filters["max_exp"]:
#             continue

#         # 🔹 Skills Filter
#         if filters.get("skills"):
#             candidate_skills = [s["skill_name"].lower() for s in data.get("skills", [])]

#             if not any(skill.lower() in candidate_skills for skill in filters["skills"]):
#                 continue

#         # 🔹 Degree Filter
#         if filters.get("degree"):
#             degrees = [e["degree"].lower() for e in data.get("education", [])]

#             if not any(filters["degree"].lower() in d for d in degrees):
#                 continue

#         # 🔹 Role Filter
#         if filters.get("role"):
#             roles = [exp["role"].lower() for exp in data.get("experience", [])]

#             if not any(filters["role"].lower() in r for r in roles):
#                 continue

#         results.append({
#             "id": r.name,
#             "name": f"{data.get('first_name', '')} {data.get('last_name', '')}",
#             "experience": exp,
#             "skills": [s["skill_name"] for s in data.get("skills", [])][:6],
#             "current_role": data.get("experience", [{}])[0].get("role", "")
#         })

#     return results

import json
import os
import re

import frappe


DEGREE_SYNONYMS = {
    "be": ["be", "b e", "b.e", "b.e.", "bachelor of engineering"],
    "btech": ["btech", "b tech", "b.tech", "bachelor of technology"],
    "me": ["me", "m e", "m.e", "master of engineering"],
    "mtech": ["mtech", "m tech", "m.tech", "master of technology"],
    "mba": ["mba", "master of business administration"],
    "pgdm": ["pgdm", "post graduate diploma in management"],
    "bcom": ["bcom", "b com", "b.com", "bachelor of commerce"],
    "mcom": ["mcom", "m com", "m.com", "master of commerce"],
    "ca": ["ca", "chartered accountant"],
    "cs": ["cs", "company secretary"],
    "cfa": ["cfa", "chartered financial analyst"],
    "bca": ["bca", "bachelor of computer application"],
    "mca": ["mca", "master of computer application"],
    "bsc_it": ["bsc it", "b.sc it", "bachelor of science in it"],
    "msc_it": ["msc it", "m.sc it", "master of science in it"],
    "bsc": ["bsc", "b.sc", "bachelor of science"],
    "msc": ["msc", "m.sc", "master of science"],
    "ba": ["ba", "b.a", "bachelor of arts"],
    "ma": ["ma", "m.a", "master of arts"],
    "llb": ["llb", "bachelor of law"],
    "llm": ["llm", "master of law"],
    "mbbs": ["mbbs", "bachelor of medicine"],
    "bds": ["bds", "bachelor of dental surgery"],
    "md": ["md", "doctor of medicine"],
    "diploma": ["diploma", "polytechnic diploma"],
    "phd": ["phd", "doctor of philosophy"],
}


def _safe_float(value, default):
    try:
        if value in (None, ""):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _normalize_degree(value):
    text = _normalize_text(value).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_filters(raw_filters):
    filters = raw_filters
    for _ in range(3):
        if isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except Exception:
                return {}
        if isinstance(filters, dict) and "filters" in filters:
            filters = filters.get("filters")
            continue
        break
    return filters if isinstance(filters, dict) else {}


@frappe.whitelist(allow_guest=True)
def search_candidates(filters=None):
    try:
        filters = _parse_filters(filters)

        min_exp = _safe_float(filters.get("min_exp"), 0)
        max_exp = _safe_float(filters.get("max_exp"), 100)
        if min_exp > max_exp:
            min_exp, max_exp = max_exp, min_exp

        has_custom_exp = frappe.db.has_column("Job Applicant", "custom_experience_years")
        has_custom_total_exp = frappe.db.has_column("Job Applicant", "custom_total_experience")
        has_custom_role = frappe.db.has_column("Job Applicant", "custom_current_role")
        has_custom_degree = frappe.db.has_column("Job Applicant", "custom_degree")
        has_custom_skills = frappe.db.has_column("Job Applicant", "custom_skills")
        has_current_location = frappe.db.has_column("Job Applicant", "current_location")
        has_custom_location = frappe.db.has_column("Job Applicant", "custom_location")

        db_filters = []
        or_filters = []

        if has_custom_exp and (min_exp != 0 or max_exp != 100):
            db_filters.append(["custom_experience_years", ">=", min_exp])
            db_filters.append(["custom_experience_years", "<=", max_exp])

        role = _normalize_text(filters.get("role"))
        if role and has_custom_role:
            db_filters.append(["custom_current_role", "like", f"%{role}%"])

        degree_input = _normalize_degree(filters.get("degree"))
        if degree_input and has_custom_degree:
            matched_terms = []
            for variants in DEGREE_SYNONYMS.values():
                if degree_input in variants:
                    matched_terms = variants
                    break
            if not matched_terms:
                matched_terms = degree_input.split()
            for term in matched_terms:
                if term:
                    or_filters.append(["custom_degree", "like", f"%{term}%"])

        location = _normalize_text(filters.get("location"))
        if location:
            if has_current_location:
                db_filters.append(["current_location", "like", f"%{location}%"])
            elif has_custom_location:
                db_filters.append(["custom_location", "like", f"%{location}%"])

        skills = filters.get("skills") or []
        if isinstance(skills, str):
            skills = [skills]
        if has_custom_skills:
            for skill in skills:
                clean_skill = _normalize_text(skill)
                if clean_skill:
                    db_filters.append(["custom_skills", "like", f"%{clean_skill}%"])

        applicant_name = _normalize_text(filters.get("applicant_name"))
        if applicant_name:
            db_filters.append(["applicant_name", "like", f"%{applicant_name}%"])

        fields = ["name", "applicant_name", "resume_attachment", "email_id", "phone_number", "creation"]
        optional_fields = [
            ("custom_experience_years", has_custom_exp),
            ("custom_total_experience", has_custom_total_exp),
            ("custom_skills", has_custom_skills),
            ("custom_current_role", has_custom_role),
            ("custom_degree", has_custom_degree),
            ("current_location", has_current_location),
            ("custom_location", has_custom_location),
        ]
        fields.extend(field for field, exists in optional_fields if exists)

        records = frappe.get_all(
            "Job Applicant",
            filters=db_filters,
            or_filters=or_filters,
            fields=fields,
            limit_page_length=100,
            order_by="creation desc",
        )

        grouped = {}
        for row in records:
            key = row.get("email_id") or row.get("phone_number") or row.get("name")

            if key not in grouped:
                grouped[key] = {
                    "name": row.get("name"),
                    "applicant_name": row.get("applicant_name"),
                    "custom_experience_years": row.get("custom_experience_years"),
                    "custom_total_experience": row.get("custom_total_experience"),
                    "custom_skills": row.get("custom_skills"),
                    "custom_current_role": row.get("custom_current_role"),
                    "custom_degree": row.get("custom_degree"),
                    "current_location": row.get("current_location") or row.get("custom_location"),
                    "email_id": row.get("email_id"),
                    "phone_number": row.get("phone_number"),
                    "resumes": [],
                }

            raw_file_name = os.path.basename(row.get("resume_attachment") or "")
            # frappe.log_error("RAW FILE NAME", raw_file_name)
            # file_name_parts = raw_file_name.split("_", 1)
            # frappe.log_error("FILE NAME PARTS", str(file_name_parts))
            # file_name = file_name_parts[1] if len(file_name_parts) > 1 else file_name_parts[0]
            file_name = raw_file_name

            grouped[key]["resumes"].append(
                {
                    "resume_attachment": row.get("resume_attachment"),
                    "creation": row.get("creation"),
                    "name": row.get("name"),
                    "file_name": file_name,
                }
            )

        return list(grouped.values())
    except Exception:
        frappe.log_error(
            title="search_candidates failed",
            message=frappe.get_traceback(),
        )
        return []
# @frappe.whitelist(allow_guest=True)
# def search_candidates(filters=None):
#     if isinstance(filters, str):
#         filters = json.loads(filters)

#     if not filters:
#         filters = {}

#     # Safely parse and provide defaults
#     try:
#         min_exp = float(filters.get("min_exp") or 0)
#         max_exp = float(filters.get("max_exp") or 100)
#     except (ValueError, TypeError):
#         min_exp, max_exp = 0, 100

#     # Ensure max is at least 100 if set to 0 by user
#     if max_exp <= 0:
#         max_exp = 100

#     # Swap if user put them in wrong order
#     if min_exp > max_exp:
#         min_exp, max_exp = max_exp, min_exp

#     # Use a tuple for the between range
#     # db_filters = {
#     #     "experience_years": ["between", (min_exp, max_exp)]
#     # }
#     db_filters = {
#         "experience_years": ["=", (min_exp, max_exp)]
#     }
    
#     # db_filters = [
#     #     ["Resume", "experience_years", "between", [min_exp, max_exp]]
#     # ]

#     return frappe.get_all(
#         "Resume",
#         # filters=db_filters,
#         filters=db_filters,
#         # fields=["*"],
#         fields=[
#             "name",
#             "candidate_name",
#             "experience_years",
#             "skills",
#             "current_role"
#         ],
#         order_by="modified desc"
#         # order_by="`tabResume`.`modified` DESC"  # safer
#     )

# @frappe.whitelist(allow_guest=True)
# def search_candidates(filters=None):

#     # ✅ Convert incoming filters
#     if isinstance(filters, str):
#         filters = json.loads(filters)

#     if not filters:
#         filters = {}

#     # ✅ DEBUG (ADD THIS)
#     frappe.log_error("RAW FILTERS", str(filters))

#     # ✅ Extract safely
#     min_exp = float(filters.get("min_exp") or 0)
#     max_exp = float(filters.get("max_exp") or 100)

#     # ✅ FORCE FIX (IMPORTANT)
#     if max_exp is None or max_exp == 0:
#         max_exp = 100

#     if min_exp > max_exp:
#         min_exp, max_exp = max_exp, min_exp

#     # ✅ DEBUG AGAIN
#     frappe.log_error("FINAL VALUES", f"{min_exp} → {max_exp}")

#     # db_filters = {
#     #     "experience_years": ["between", [min_exp, max_exp]]
#     # }
#     # To this:
#     db_filters = {
#         "experience_years": ["between", (min_exp, max_exp)]
#     }
#     # return frappe.get_all(
#     #     "Resume",
#     #     filters=db_filters,
#     #     fields=[
#     #         "name",
#     #         "candidate_name",
#     #         "experience_years",
#     #         "skills",
#     #         "current_role"
#     #     ],
#     #     order_by="`tabResume`.`modified` DESC"  # safer
#     # )
#     return frappe.get_all(
#         "Resume",
#         filters=db_filters,
#         fields=[
#             "name",
#             "candidate_name",
#             "experience_years",
#             "skills",
#             "current_role"
#         ],
#         order_by="modified desc"
#     )

# @frappe.whitelist()
# def search_candidates(filters=None):

#     # ✅ Convert filters safely
#     if isinstance(filters, str):
#         filters = json.loads(filters)

#     if not filters:
#         filters = {}

#     # ✅ Convert numeric filters
#     min_exp = float(filters.get("min_exp") or 0)
#     max_exp = float(filters.get("max_exp") or 100)

#     skills_filter = filters.get("skills") or []
#     degree_filter = (filters.get("degree") or "").lower()
#     role_filter = (filters.get("role") or "").lower()

#     resumes = frappe.get_all(
#         "Resume",
#         fields=["name", "parsed_json"],
#         limit_page_length=200   # ⚡ safety limit
#     )

#     results = []

#     for r in resumes:
#         try:
#             if not r.parsed_json:
#                 continue

#             data = json.loads(r.parsed_json)

#             # ✅ Experience
#             exp = float(data.get("experience_years", 0))

#             if exp < min_exp:
#                 continue
#             if exp > max_exp:
#                 continue

#             # ✅ Skills
#             if skills_filter:
#                 candidate_skills = [
#                     s.get("skill_name", "").lower()
#                     for s in data.get("skills", [])
#                 ]

#                 if not any(skill.lower() in candidate_skills for skill in skills_filter):
#                     continue

#             # ✅ Degree
#             if degree_filter:
#                 degrees = [
#                     e.get("degree", "").lower()
#                     for e in data.get("education", [])
#                 ]

#                 if not any(degree_filter in d for d in degrees):
#                     continue

#             # ✅ Role
#             if role_filter:
#                 roles = [
#                     exp_item.get("role", "").lower()
#                     for exp_item in data.get("experience", [])
#                 ]

#                 if not any(role_filter in r for r in roles):
#                     continue

#             # ✅ Final result object
#             results.append({
#                 "id": r.name,
#                 "name": f"{data.get('first_name', '')} {data.get('last_name', '')}",
#                 "experience": exp,
#                 "skills": [s.get("skill_name") for s in data.get("skills", [])][:6],
#                 "current_role": data.get("experience", [{}])[0].get("role", "")
#             })

#         except Exception as e:
#             frappe.log_error("Candidate Filter Error", str(e))
#             continue

#     return results


@frappe.whitelist(allow_guest=True)
def get_designations():
    return frappe.get_all(
        "Designation",
        pluck="name",
        order_by="name asc",
        limit_page_length=0,  # saare designations
    )
