# Vaaman ATS AI – Intelligent Resume Parsing & Chat System

Vaaman ATS AI is an AI-powered recruitment assistant built on **Frappe** that allows users to:

- Upload resumes (PDF/DOCX)
- Automatically parse candidate information using an open-source LLM
- Index resumes semantically using embeddings
- Chat with uploaded resumes using natural language
- Get answers grounded strictly in resume data (no hallucination)

This project implements a **RAG (Retrieval Augmented Generation)** architecture.

---

## ✨ Features

### ✅ Resume Upload & Parsing
- Upload resumes via UI or API
- Extract text from PDF/DOCX
- Parse structured data (name, skills, experience, education)
- Open-source LLM (via Ollama)

### ✅ Semantic Resume Indexing
- Resume text is split into chunks
- Each chunk is converted into embeddings
- Embeddings are stored in a FAISS vector index
- Fast and accurate semantic search

### ✅ Resume Chat (AI Recruiter Assistant)
- Ask questions like:
  - "Who has Python and Frappe experience?"
  - "Summarize the candidate"
  - "Who has frontend experience?"
- AI answers only from uploaded resumes
- Sources are returned for transparency

---

## 🧠 Architecture Overview

Resume Upload
↓
Text Extraction
↓
LLM Parsing
↓
Chunking
↓
Embeddings
↓
FAISS Vector Store
↓
Chat Query
↓
LLM Answer (Grounded)


- **Frappe** → business logic, APIs, UI
- **FAISS** → vector search
- **Sentence Transformers** → embeddings
- **Ollama (LLaMA3)** → LLM

---

## 🗂️ Project Structure

vaaman_ats_ai/
├── parse_resume.py # Resume upload & parsing API
├── chat_api.py # Chat query API
├── chunker.py # Resume chunking logic
├── embedder.py # Embedding generation
├── vector_store.py # FAISS index handling
├── faiss.index # Auto-generated (runtime)
├── metadata.json # Auto-generated (runtime)


> ⚠️ `faiss.index` and `metadata.json` are **runtime files** and should NOT be committed.

---

## 🚀 Getting Started

### 1️⃣ Prerequisites

- Python 3.10+
- Frappe Bench
- Ollama installed and running
- Model pulled:
  ```bash
  ollama pull llama3


2️⃣ Install Dependencies

Inside frappe-bench:

bench pip install -r requirements.txt

3️⃣ Run Frappe

bench start


🧪 Testing the System
Resume Upload UI

/resume-upload

Resume Chat UI

/resume-chat

Ask questions like:

"Who knows Python?"

"Summarize the candidate"



API Testing (Chat)

POST /api/method/vaaman_ats_ai.chat_api.chat_query

{
  "question": "Who has backend experience?"
}


🧹 Reset Vector Index (Optional)

To rebuild AI memory:

rm apps/vaaman_ats_ai/vaaman_ats_ai/faiss.index
rm apps/vaaman_ats_ai/vaaman_ats_ai/metadata.json


✅ How Frappe uses this file (important)

Frappe does NOT automatically install app requirements unless you tell it to.

After adding requirements.txt, you must run:

bench setup requirements


or (safe alternative):

bench pip install -r apps/vaaman_ats_ai/requirements.txt


✅ This installs dependencies into the bench virtualenv.

✅ How to verify it worked
bench --site cnd.octavision.in console


Then:

import faiss
import sentence_transformers
import pdfplumber
import docx


If no error → ✅ all good.