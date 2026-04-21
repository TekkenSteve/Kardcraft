# Kardcraft

Automate flashcard production for spaced repetition workflows.

## What This Project Does

Kardcraft is a card generation system for Anki-style spaced repetition.
It converts raw learning inputs (notes, PDFs, lecture material, highlights, Q&A context) into flashcards that can be reviewed directly.

Core idea: automate card authoring, then improve output quality over time using review feedback.

## Why This Project Is Worth Building

### 1. Clear Time Savings

Manual card authoring is slow.
Automation reduces authoring time from hours to minutes for large note sets.

### 2. Better Models Improve Output

Model upgrades are more likely to help this project than replace it.
The model is only one layer; the product value also depends on ingestion workflow, card quality rules, review integration, and user-specific adaptation.
When models improve, the same pipeline usually gets better card extraction, summarization, and difficulty control with lower engineering cost.

### 3. Fast Quality Signal

Most AI content is used once and then ignored.
Flashcards are different: users must read them during review, otherwise they cannot pass recall.
If a card is bad, users immediately show it by editing it, skipping it, or failing recall.
Those signals arrive daily and can be mapped to concrete generation problems, so quality iteration is fast.

### 4. Personalized Adaptation Over Time

Each remember/forget event is useful signal.
The system can learn user-specific memory patterns and adjust future card generation.

## Project Status

This project is actively under development.  
Modules may be refactored at any time.  
Do **not** use it directly in production yet.

## Quick Start

### 1. Prepare Environment Files

Fill every required `.env.*.example` file, then copy them by removing the `.example` suffix.

```bash
# examples
cp .env.example .env
cp .env.lightrag.example .env.lightrag
cp .env.llm.example .env.llm
cp frontend/.env.local.example frontend/.env.local
```

### 2. Start Backend Services (from project root)

```bash
docker compose up -d
```

### 3. Start Frontend Dev Server

```bash
cd frontend
npm install
npm run dev
```

## Repository Layout

```text
backend/         Backend services and core business modules
frontend/        Web/Desktop frontend (Next.js + Tauri related code)
infrastructure/  Infra scripts and environment helpers
```

## Operational Notes

- Keep backend bootstrapped with Docker Compose from the repository root.
- Keep frontend development inside `frontend/`.
- Expect frequent interface and module boundary changes while the project stabilizes.

## License

Apache-2.0. See `LICENSE`.
