import frappe
import requests
import random
import string

def setup_user_roles(login_manager):
    user = login_manager.user
    if not user or user in ["Guest", "Administrator"]:
        return

    try:
        # 1. Single DocType (ATS Settings) se configuration fetch karein
        settings = frappe.get_single("ATS Settings")

        # Agar admin ne UI se sync band (disable) kar rakha hai toh wahin se return ho jaye
        if not settings.enable_sync:
            return

        vidhi_url = (settings.base_url or "").rstrip("/")
        api_key = settings.get_password("api_key")
        # Password field ko decrypt karne ke liye get_password() zaroori hai
        api_secret = settings.get_password("api_secret")

        if not (vidhi_url and api_key and api_secret):
            frappe.log_error(
                "Vidhi Base URL, API Key, or Secret is missing in ATS Settings",
                "Vidhi Role Sync"
            )
            return

        headers = {
            "Authorization": f"token {api_key}:{api_secret}",
            "Content-Type": "application/json"
        }

        # 2. Vidhi server se User ka data fetch karein
        user_res = requests.get(
            f"{vidhi_url}/api/resource/User/{user}",
            headers=headers,
            timeout=10
        )

        if user_res.status_code != 200:
            frappe.log_error(
                f"Could not fetch user {user} from Vidhi: {user_res.text}",
                "Vidhi Role Sync"
            )
            return

        vidhi_user_data = user_res.json().get("data", {})
        vidhi_roles = [r.get("role") for r in vidhi_user_data.get("roles", []) if r.get("role")]

        # 3. ATS Server par User Doc update karein
        user_doc = frappe.get_doc("User", user)
        
        # Simple aur 100% working check: 
        # Agar user ka creation time pichle 1 minute ke andar ka hai, toh yeh pehli baar bana hai!
        from frappe.utils import now_datetime, get_datetime
        
        is_first_login = False
        if user_doc.creation:
            creation_time = get_datetime(user_doc.creation)
            time_diff = (now_datetime() - creation_time).total_seconds()
            # Agar user abhi pichle 60 seconds mein create hua hai toh email bhej do
            if time_diff < 60:
                is_first_login = True
        
        modified = False

        # User Type sync karein (e.g., System User)
        vidhi_user_type = vidhi_user_data.get("user_type", "System User")
        if user_doc.user_type != vidhi_user_type:
            user_doc.user_type = vidhi_user_type
            modified = True

        # Sirf wahi roles filter karein jo ATS server ke DB mein exist karte hain
        valid_ats_roles = set(frappe.get_all("Role", pluck="name"))
        roles_to_assign = set(vidhi_roles).intersection(valid_ats_roles)

        # System default roles ko ignore karein comparison ke waqt
        system_defaults = {"All", "Guest", "Desk User"}
        current_roles = {r.role for r in user_doc.roles} - system_defaults

        # Agar roles mein koi bhi fark hai toh exact sync kar dein
        if current_roles != roles_to_assign:
            user_doc.set("roles", [])
            for r in roles_to_assign:
                user_doc.append("roles", {"role": r})
            modified = True

        if modified:
            user_doc.flags.ignore_permissions = True
            user_doc.save()

        # 4. Agar Settings mein 'Sync User Permissions' checked hai toh permissions bhi sync karein
        if settings.get("sync_user_permissions"):
            sync_user_permissions(user, vidhi_url, headers)

        frappe.db.commit()
        
        # Agar pehla login hai toh password reset email bhej do, warna nahi
        if is_first_login:
            try:
                user_doc.reset_password(send_email=True)
            except Exception as mail_err:
                frappe.log_error(f"Failed to send welcome email to {user}: {mail_err}", "SSO Welcome Email Error")

    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Error in setup_user_roles for {user}")


def sync_user_permissions(user, vidhi_url, headers):
    """Vidhi server ki User Permissions ko ATS par sync karta hai."""
    try:
        perm_url = (
            f'{vidhi_url}/api/resource/User Permission'
            f'?filters=[["user","=","{user}"]]'
            f'&fields=["allow","for_value","applicable_for","apply_to_all_doctypes","is_default"]'
            f'&limit_page_length=500'
        )
        perm_res = requests.get(perm_url, headers=headers, timeout=10)

        if perm_res.status_code != 200:
            return

        vidhi_perms = perm_res.json().get("data", [])

        for p in vidhi_perms:
            allow_doctype = p.get("allow")
            for_value = p.get("for_value")

            if frappe.db.exists("DocType", allow_doctype) and frappe.db.exists(allow_doctype, for_value):
                exists = frappe.db.exists("User Permission", {
                    "user": user,
                    "allow": allow_doctype,
                    "for_value": for_value,
                    "applicable_for": p.get("applicable_for") or ""
                })

                if not exists:
                    perm_doc = frappe.get_doc({
                        "doctype": "User Permission",
                        "user": user,
                        "allow": allow_doctype,
                        "for_value": for_value,
                        "applicable_for": p.get("applicable_for"),
                        "apply_to_all_doctypes": p.get("apply_to_all_doctypes", 1),
                        "is_default": p.get("is_default", 0)
                    })
                    perm_doc.flags.ignore_permissions = True
                    perm_doc.insert()

    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Permission Sync Failed for {user}")

@frappe.whitelist(allow_guest=True)
def sso_logout():
    # 1. ATS ka local session khatam karein
    if frappe.session.user and frappe.session.user != "Guest":
        frappe.local.login_manager.logout()
        frappe.db.commit()

    # 2. vidhi server ka URL uthayein
    settings = frappe.get_single("ATS Settings")
    vidhi_url = (settings.base_url or "https://vidhi.vaaman.in").rstrip("/")
    
    # 3. ATS ka login URL dynamically query parameter ke roop mein bhej dein
    ats_login_url = settings.redirect_url
    logout_redirect_url = f"{vidhi_url}/api/method/ats_sso.api.api.sso_logout?redirect_to={ats_login_url}"

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = logout_redirect_url