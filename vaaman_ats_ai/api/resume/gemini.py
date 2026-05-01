import google.generativeai as genai
import frappe

def get_gemini():
    api_key = frappe.conf.get("gemini_api_key")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-pro")
