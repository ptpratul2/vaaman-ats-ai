import google.generativeai as genai
import frappe
from frappe.utils.password import get_decrypted_password


def get_configured_gemini_model():
    # Read directly from tabSingles so this works even before DocType migration.
    default_model = frappe.conf.get("gemini_model") or "gemini-2.5-flash"
    try:
        row = frappe.db.sql(
            """
            SELECT value
            FROM `tabSingles`
            WHERE doctype='ATS Settings' AND field='gemini_model'
            LIMIT 1
            """,
            as_dict=True,
        )
        if row and row[0].get("value"):
            return row[0]["value"]
    except Exception:
        pass
    return default_model


def _get_default_gemini_model():
    return get_configured_gemini_model()


def get_gemini(model_name=None):
    api_key = get_decrypted_password("ATS Settings", "ATS Settings", "gemini_api_key", raise_exception=False) or frappe.conf.get("gemini_api_key")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name or _get_default_gemini_model())
