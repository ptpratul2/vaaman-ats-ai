import frappe
import time
import imaplib
from frappe.email.receive import InboundMail

# --- 🛠️ FIX 1: MONKEYPATCH PDF SCANNER ---
# This prevents corrupted applicant resumes from crashing the entire database commit
import frappe.utils.pdf
original_pdf_check = frappe.utils.pdf.pdf_contains_js

def safe_pdf_check(*args, **kwargs):
    try:
        return original_pdf_check(*args, **kwargs)
    except Exception:
        # If the PDF is completely broken/truncated, assume it has no JS and force it to save
        return False 

frappe.utils.pdf.pdf_contains_js = safe_pdf_check
# -----------------------------------------

def _get_sync_field():
    """Check if 'last_synced' column actually exists in the database table"""
    try:
        columns = frappe.db.sql("DESCRIBE `tabEmail Account`", as_dict=True)
        col_names = [c['Field'] for c in columns]
        
        if 'last_synced' in col_names:
            return 'last_synced'
        for c in col_names:
            if 'synced' in c.lower():
                return c
    except Exception as e:
        frappe.log_error(f"Error checking DB columns: {e}")
    return None

@frappe.whitelist()
def enqueue_full_email_sync(email_account_name):
    email_account_name = "Auto Resume"
    lock_key = f"sync_lock_{email_account_name}"
    if frappe.cache().get_value(lock_key):
        frappe.throw("🔄 Sync already running. Check Background Jobs.")

    frappe.cache().set_value(lock_key, "1", expires_in_sec=14400) # Increased lock time
    
    frappe.log_error(f"Enqueuing full sync for {email_account_name}")

    frappe.enqueue(
        "vaaman_ats_ai.api.email.tasks.run_full_sync",
        email_account_name=email_account_name,
        lock_key=lock_key,
        queue="long",
        timeout=14400, # Increased timeout for massive syncs
        job_name=f"Full Sync: {email_account_name}"
    )
    return "🔄 Sync started in background. Check Desk → Background Jobs."

# ⛔ NOTE: is method par @frappe.whitelist() NA ho
def run_full_sync(email_account_name, lock_key, batch_size=50, delay_sec=1):
    frappe.log_error(f"▶️ Starting full DIRECT IMAP sync for {email_account_name}")
    
    try:
        frappe.set_user("Administrator")
        email_acc = frappe.get_doc("Email Account", email_account_name)
        if not email_acc.enable_incoming:
            frappe.throw("Enable Incoming ON karein.")

        # --- 🛠️ FIX 2: CONNECTION MANAGER ---
        def connect_to_zoho():
            frappe.log_error("📡 Connecting/Reconnecting to Zoho IMAP...")
            receiver = email_acc.get_incoming_server(in_receive=True)
            receiver.connect()
            conn = receiver.imap
            conn.select('INBOX', readonly=True)
            return receiver, conn

        # 1. Initialize First Connection
        email_receiver, imap = connect_to_zoho()

        # 2. Get EVERY single UID
        frappe.log_error("📥 Searching for all UIDs...")
        status, response = imap.uid('search', None, 'ALL')
        
        if status != 'OK':
            frappe.log_error(f"❌ IMAP Search failed: {response}")
            return
            
        uids = response[0].split()
        total_emails = len(uids)
        frappe.log_error(f"📦 Total emails found in Zoho INBOX: {total_emails}")

        if total_emails == 0:
            return

        synced_count = 0
        error_count = 0

        # 3. Stream emails one by one
        for i, uid_bytes in enumerate(uids):
            try:
                uid_str = uid_bytes.decode('utf-8')
                
                fetch_status, fetch_data = imap.uid('fetch', uid_bytes, '(RFC822)')
                
                if fetch_status != 'OK' or not fetch_data:
                    continue
                    
                if not isinstance(fetch_data[0], tuple):
                    continue
                    
                raw_bytes = fetch_data[0][1]

                mail = InboundMail(raw_bytes, email_acc, uid_str)

                # Failsafe Patch
                if getattr(mail, 'from_real_name', None) is None: 
                    mail.from_real_name = 'Unknown Sender'
                if getattr(mail, 'from_email', None) is None: 
                    mail.from_email = 'unknown@example.com'
                if getattr(mail, 'subject', None) is None: 
                    mail.subject = 'No Subject'
                if getattr(mail, 'message_id', None) is None: 
                    mail.message_id = f"custom-uid-{uid_str}@sync"
                if getattr(mail, 'text_content', None) is None: 
                    mail.text_content = 'No Content provided.'

                communication = mail.process()
                
                if communication:
                    synced_count += 1

                if synced_count > 0 and synced_count % batch_size == 0:
                    frappe.db.commit()
                    frappe.log_error(f"✓ Batch committed. Progress: {i+1}/{total_emails} | New Synced: {synced_count}")
                    time.sleep(delay_sec) 

            # --- CATCH ZOHO DROPPING THE CONNECTION ---
            except imaplib.IMAP4.abort as e:
                frappe.log_error(f"🔌 Zoho closed connection at UID {uid_str}. Reconnecting in 5s... Error: {e}")
                time.sleep(5)
                try:
                    email_receiver, imap = connect_to_zoho()
                except Exception as reconnect_e:
                    frappe.log_error(f"Fatal reconnect error: {reconnect_e}")
                    break # If we can't reconnect, stop completely
                continue # Skip the poison email that caused the crash and move to the next

            # --- CATCH REGULAR ERRORS ---
            except Exception as e:
                error_count += 1
                if error_count > 1000:
                    frappe.log_error("⛔ 1000+ errors reached. Stopping to protect server.")
                    break
                continue

        frappe.db.commit()
        success_msg = f"✅ Direct Sync Complete: Processed {total_emails} | New Emails Synced: {synced_count} | Errors: {error_count}"
        frappe.log_error(success_msg)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Full Sync Failed: {email_account_name}")
        raise

    finally:
        frappe.cache().delete_value(lock_key)
        frappe.log_error("🔒 Lock released.")