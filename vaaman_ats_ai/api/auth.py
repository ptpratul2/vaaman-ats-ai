import frappe
import requests

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

        prayog_url = (settings.prayog_base_url or "").rstrip("/")
        api_key = settings.prayog_api_key
        # Password field ko decrypt karne ke liye get_password() zaroori hai
        api_secret = settings.get_password("prayog_api_secret")

        if not (prayog_url and api_key and api_secret):
            frappe.log_error(
                "Prayog Base URL, API Key, or Secret is missing in ATS Settings",
                "Prayog Role Sync"
            )
            return

        headers = {
            "Authorization": f"token {api_key}:{api_secret}",
            "Content-Type": "application/json"
        }

        # 2. Prayog server se User ka data fetch karein
        user_res = requests.get(
            f"{prayog_url}/api/resource/User/{user}",
            headers=headers,
            timeout=10
        )

        if user_res.status_code != 200:
            frappe.log_error(
                f"Could not fetch user {user} from Prayog: {user_res.text}",
                "Prayog Role Sync"
            )
            return

        prayog_user_data = user_res.json().get("data", {})
        prayog_roles = [r.get("role") for r in prayog_user_data.get("roles", []) if r.get("role")]

        # 3. ATS Server par User Doc update karein
        user_doc = frappe.get_doc("User", user)
        modified = False

        # User Type sync karein (e.g., System User)
        prayog_user_type = prayog_user_data.get("user_type", "System User")
        if user_doc.user_type != prayog_user_type:
            user_doc.user_type = prayog_user_type
            modified = True

        # Sirf wahi roles filter karein jo ATS server ke DB mein exist karte hain
        valid_ats_roles = set(frappe.get_all("Role", pluck="name"))
        roles_to_assign = set(prayog_roles).intersection(valid_ats_roles)

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
            sync_user_permissions(user, prayog_url, headers)

        frappe.db.commit()

    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Error in setup_user_roles for {user}")


def sync_user_permissions(user, prayog_url, headers):
    """Prayog server ki User Permissions ko ATS par sync karta hai."""
    try:
        perm_url = (
            f'{prayog_url}/api/resource/User Permission'
            f'?filters=[["user","=","{user}"]]'
            f'&fields=["allow","for_value","applicable_for","apply_to_all_doctypes","is_default"]'
            f'&limit_page_length=500'
        )
        perm_res = requests.get(perm_url, headers=headers, timeout=10)

        if perm_res.status_code != 200:
            return

        prayog_perms = perm_res.json().get("data", [])

        for p in prayog_perms:
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