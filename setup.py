import frappe

def after_install():
    set_site_config_defaults()                                          
    check_gemini_config()               

def set_site_config_defaults():
    config_updates = {
        "ai_mode": "gemini",
        "gemini_model": "gemini-2.5-flash",
        "job_matching_model": "gemini-1.5-flash",
        "email_account": "YOUR_EMAIL_ACCOUNT"
    }

    for key, value in config_updates.items():
        # Only set if not already present
        if not frappe.conf.get(key):
            frappe.utils.set_site_config(key, value)

    frappe.log_error("Setup", "AI config added to site_config.json")


def check_gemini_config():
    if not frappe.conf.get("gemini_api_key"):
        frappe.log_error(
            "Gemini Setup",
            "Gemini API key missing. Please add in site_config.json"
        )