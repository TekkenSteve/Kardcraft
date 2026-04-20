# Kardcraft

Build knowledge workflows, not glue scripts.

## What This Project Does

Kardcraft is an AI-native cardcrafting system for Anki-style spaced repetition.
It turns messy learning inputs (notes, PDFs, lecture material, highlights, Q&A context) into high-quality flashcards that are review-ready.

Core idea: automate the expensive part of learning infrastructure, then keep improving card quality from review feedback over time.

## Why This Bet Is Strong

### 1. Time Leverage

This is not about saving a few minutes.  
It compresses hours of manual card authoring into minutes, while the value compounds across hundreds of future review sessions.

### 2. Foundation Models Are Ammunition, Not a Threat

Model upgrades do not kill this product category.  
They make the agent better at extraction, abstraction, difficulty calibration, and format control.

### 3. Dense Quality Feedback Loop

Users are forced to evaluate output daily during review.  
Bad cards cause immediate pain and churn. Good cards create flow, trust, and long-term retention.

### 4. Data Flywheel

Every remember/forget event is training signal.  
The system learns how each user encodes memory and adapts card generation. Usage builds defensibility.

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
