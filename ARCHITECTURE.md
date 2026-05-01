# 🚀 Vaaman ATS AI (Frappe App)

AI-powered resume parsing, job matching, and candidate processing for Frappe/ERPNext.

This app automatically:

* 📄 Extracts structured data from resumes (PDF/DOC/DOCX)
* 🤖 Matches candidates to job openings using AI
* ⚡ Uses **local AI (Ollama)** + **Gemini fallback**
* 🧠 Generates embeddings for advanced search & ranking

---

# ✨ Key Features

* ✅ Automatic resume parsing (no manual input)
* ✅ AI-based job matching (email + resume context)
* ✅ Hybrid AI system:

  * 🟢 Local (Ollama) → Free & fast
  * 🔵 Cloud (Gemini) → Fallback for accuracy
* ✅ Safe fallback (never crashes your system)
* ✅ Works even if AI is not configured
* ✅ Background processing (non-blocking)

---

# 📦 Installation

```bash
bench get-app vaaman_ats_ai
bench install-app vaaman_ats_ai
```

That’s it. No additional setup required.

---

# 🧠 How It Works

```text
Email Received
    ↓
Resume Extracted
    ↓
AI Matching Engine
    ↓
 ┌───────────────┐
 │  Ollama (Local) │
 └───────┬───────┘
         ↓ (if fail / weak)
 ┌───────────────┐
 │ Gemini (Cloud) │
 └───────────────┘
         ↓
Final Decision Stored
```

---

# ⚙️ AI Modes

You can control behavior via `site_config.json`:

```json
{
  "ai_mode": "hybrid",   // "ollama" | "gemini" | "hybrid"
  "ollama_model": "gemma4:e2b",
  "ollama_host": "http://localhost:11434",
  "gemini_api_key": "YOUR_API_KEY",
  "email_account": "YOUR_EMAIL_ACCOUNT"
}
```

### Modes Explained

| Mode   | Behavior                                     |
| ------ | -------------------------------------------- |
| hybrid | Ollama first → Gemini fallback (Recommended) |
| ollama | Only local AI                                |
| gemini | Only Gemini API                              |

---

# 🤖 Ollama Setup (Optional)

If you want **free local AI**, install Ollama:

### Linux / Mac

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e2b
```

### Windows

Download from: https://ollama.com/download

---

# 🔵 Gemini Setup (Optional but Recommended)

Add API key in:

```bash
site_config.json
```

```json
{
  "gemini_api_key": "YOUR_API_KEY"
}
```

Get API key from:
👉 https://makersuite.google.com/app

---

# 🛡️ Smart Fallback System

The system automatically handles failures:

| Scenario             | Behavior                 |
| -------------------- | ------------------------ |
| Ollama not installed | Uses Gemini              |
| Ollama fails         | Uses Gemini              |
| Gemini fails         | Safe fallback (no crash) |
| Both fail            | Still creates applicant  |

---

# 🧪 Health Check (Optional)

You can check Ollama status:

```python
frappe.call("vaaman_ats_ai.api.resume.resume.check_ollama_health")
```

---

# 📁 Data Flow

* Email → Communication Doctype
* Attachments → Resume parsing
* Output → Job Applicant
* AI Match → Job Opening
* Embeddings → Resume Chunk + Vector Store

---

# ⚡ Performance Design

* Background jobs via `frappe.enqueue`
* Non-blocking email processing
* Chunking + embeddings for fast search
* Retry + fallback logic

---

# 🧩 Developer Notes

### Important Functions

* `match_job_opening_with_ai()` → Ollama
* `match_job_opening_with_gemini()` → Gemini
* `match_job_opening_hybrid()` → Smart orchestrator
* `create_resume_from_upload()` → Embeddings
* `fetch_email_resumes()` → Entry point

---

# 🚨 Common Issues

### ❌ "Ollama not found"

✔️ Install Ollama OR ignore (Gemini will be used)

---

### ❌ "Invalid JSON from AI"

✔️ Already handled internally (auto-clean + retry)

---

### ❌ "Job match not working"

✔️ Check:

* Job Openings exist
* AI mode config
* Logs (`frappe.log_error`)

---

# 📊 Logging

AI decisions are logged:

* Ollama result
* Gemini result
* Final selected output

Useful for debugging and audits.

---

# 🔒 Safety

* No system crash on AI failure
* Graceful degradation
* Input validation
* JSON sanitization

---

# 🚀 Roadmap (Planned)

* 📊 Admin AI dashboard
* 🎯 Candidate ranking system
* 🧠 Multi-job matching (top 3)
* 📈 AI analytics
* 🌐 Multi-language resume parsing

---

# 👨‍💻 Author

Built for scalable AI-powered recruitment inside Frappe.

---

# ⭐ Recommendation

Use **Hybrid Mode**:

```json
"ai_mode": "hybrid"
```

✔ Best balance of cost + performance + reliability

---

# 📞 Support

If something breaks:

* Check logs
* Verify AI config
* Restart bench

```bash
bench restart
```

---

Enjoy building 🚀
