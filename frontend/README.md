# myRAG Frontend

The myRAG chatbot UI — built with **Next.js 15 App Router**, TypeScript, and Tailwind CSS.

## Stack

| Tool | Version | Purpose |
|------|---------|---------|
| Next.js | 15 | React framework + App Router |
| TypeScript | 5 | Type safety |
| Tailwind CSS | 4 | Utility-first styling |
| clsx + tailwind-merge | — | Safe class merging |

## Project structure

```
src/
├── app/              Next.js App Router pages and layout
├── components/
│   ├── chat/         ChatWindow, MessageBubble, ChatInput, CitationCard, EmptyState
│   ├── documents/    UploadZone, DocumentStatusBadge
│   ├── layout/       Sidebar
│   └── ui/           LoadingDots, Badge (primitives)
├── hooks/            useChat, useDocumentUpload
├── services/         api.ts (base client), chat.ts, documents.ts
├── types/            Shared TypeScript interfaces
└── lib/              utils.ts (cn, formatDate, truncate)
```

## Environment variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend API base URL |

## Running locally

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
npm run lint     # lint check
```

## Mock mode

`src/services/api.ts` exports `MOCK_MODE = true`.  
All service functions return mock data while the backend is not connected.  
To connect to the real backend: set `MOCK_MODE = false` in `api.ts`.

## What is intentionally unimplemented

- Real backend API calls (mock data returned)
- Authentication
- Streaming responses
- Loading existing conversation history from the server
- Document processing status polling
