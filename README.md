# Kardcraft

Automate flashcard production for spaced repetition workflows.

## What This Project Does

Kardcraft is a dual-mode, conversation-driven flashcard crafting system for spaced repetition. It supports both topic-driven generation—where users provide a subject and the system auto-researches and synthesizes cards—and content-driven generation—converting raw learning inputs (notes, PDFs, lecture material, highlights) into flashcards. Its defining feature is a multi-turn conversational interface that lets users iteratively refine cards through dialogue: editing content, adjusting difficulty, restructuring formats, or requesting elaboration, until each card meets their exact learning needs.

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

`make` checks for Buf before it starts Docker. If Buf is missing, it prints the
installation link and stops before the image build.

```bash
make
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
