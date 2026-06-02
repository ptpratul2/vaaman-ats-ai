import google.generativeai as genai
import frappe
from frappe.utils.password import get_decrypted_password

def get_gemini():
    api_key = get_decrypted_password("ATS Settings", "ATS Settings", "gemini_api_key", raise_exception=False) or frappe.conf.get("gemini_api_key")
    genai.configure(api_key=api_key)
    # return genai.GenerativeModel("gemini-2.5-pro")
    return genai.GenerativeModel("gemini-2.5-flash")
