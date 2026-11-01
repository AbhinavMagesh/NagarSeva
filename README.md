# 🏛️ NagarSeva — Transparent Civic Grievance & Infrastructure Triage System

> An AI-powered open platform where citizens submit visual or audio reports of civic issues. The system automatically evaluates severity, routes issues to relevant authorities, and maintains public accountability dashboards.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Directory Structure](#4-directory-structure)
5. [Database Schema](#5-database-schema)
6. [AI Agent Pipeline — Detailed Design](#6-ai-agent-pipeline--detailed-design)
7. [API Endpoints](#7-api-endpoints)
8. [Frontend Dashboard](#8-frontend-dashboard)
9. [Real-Time Data Sources & APIs](#9-real-time-data-sources--apis)
10. [Setup & Installation](#10-setup--installation)
11. [Deployment](#11-deployment)
12. [Demo Script](#12-demo-script)

---

## Running implementation (Windows)

The runnable implementation is in `backend/` and `frontend/`. It uses the real PostGIS database and external services configured below; it does not generate sample grievances. An external-service or database error is recorded against the report and shown to the citizen.

1. Install Docker Desktop, Python 3.11 or newer, and Node.js 20 or newer. Start Docker Desktop.
2. From the project root, start PostGIS:

   ```powershell
   docker compose up -d db
   ```

3. Copy `backend/.env.example` to `backend/.env`. Add the Gemini, Sarvam, OpenWeatherMap, and Cloudinary credentials to that local file. Set `JWT_SECRET` to a long, random value. To enable authority account registration, set a private `ADMIN_INVITE_CODE`. Never put API credentials in source control or chat.
4. In PowerShell, install and start the API:

   ```powershell
   cd backend
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
   ```

   On first startup, the API enables PostGIS/vector and creates the application tables and department routing records. API documentation is available at `http://localhost:8000/docs`.
5. In a second PowerShell window, copy `frontend/.env.local.example` to `frontend/.env.local`, then start the web app:

   ```powershell
   cd frontend
   Copy-Item .env.local.example .env.local
   npm install
   npm run dev
   ```

   Open `http://localhost:3000`. Allow microphone/location access when using those browser features. If location permission is unavailable, include a recognizable Indian landmark in the written or spoken report.
6. To create an authority login, set `ADMIN_INVITE_CODE` in `backend/.env` and restart the API. In PowerShell, register an authority (replace the example name, email, password, and invite code):

   ```powershell
   $body = @{
     name = "Department Officer"
     email = "officer@example.org"
     password = "replace-with-a-long-password"
     role = "authority"
     department_code = "PWD"
     invite_code = "the-value-from-ADMIN_INVITE_CODE"
   } | ConvertTo-Json
   Invoke-RestMethod -Uri http://localhost:8000/api/v1/auth/register -Method Post -ContentType "application/json" -Body $body
   ```

   Use one of `PWD`, `WATER`, `SANITATION`, `ELECTRICITY`, `ENV`, or `MUNICIPAL` for `department_code`, then sign in to the Authority Desk.

Reports are submitted immediately, then progress through Cloudinary media upload, Gemini/Sarvam intake, PostGIS radius filtering plus Gemini embedding similarity checks, weather/Overpass triage, department routing, and Socket.IO updates. Embeddings are stored in PostgreSQL JSONB, so the supplied PostGIS image does not need the separate pgvector extension. Scoring uses available live sources and normalizes their weights; no population-density score is fabricated because no live Census data endpoint or dataset is configured. A report that cannot complete a required integration is marked `FAILED` with an explanation instead of being presented as successfully triaged. Authority status changes and community verification responses are audited and broadcast live. Scheduled SLA escalation runs every six hours; community verification requests are broadcast daily. Email/SMS delivery requires a separate notification-provider configuration and is not claimed by this implementation.

---

## 1. Project Overview

### The Problem
Millions of Indian citizens — especially in rural areas — face civic infrastructure issues (road damage, water leaks, pollution, broken bridges) but lack the digital literacy or tools to report them effectively. Existing grievance systems require smartphone apps, form-filling, and internet access, leaving the most affected populations voiceless.

### Our Solution: NagarSeva

**Two intake channels:**

| Channel | Target User | How It Works |
|---------|-------------|--------------|
| 🎤 **Voice Report** | Rural/digitally excluded citizens | Record voice in browser/phone with 1 tap → speak in any Indian language → AI transcribes, translates, extracts details, and files the grievance automatically |
| 📷 **Image Upload** | Smartphone users | Upload a photo of the issue via the web app → AI analyzes damage type and severity → grievance filed with auto-categorization |

**What makes us different:**
- **Voice-first accessibility** — no app download, no internet needed, any language
- **AI-powered severity triage** — multi-signal scoring (visual damage + geospatial context + weather + report frequency) — not just user opinions
- **Duplicate detection** — automatically merges repeated reports about the same issue, naturally surfacing high-frequency problems
- **Crowdsourced verification loop** — nearby users confirm if issues are resolved
- **Public accountability dashboard** — real-time transparency with heatmaps, SLA tracking, and authority response metrics
- **Autonomous escalation** — unresolved issues past SLA are auto-escalated to higher authorities

---

## 2. System Architecture

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CITIZEN INTAKE LAYER                         │
│                                                                     │
│   🎤 Browser Voice Recording           📷 Web App (Image Upload)     │
│         │  (MediaRecorder API)                 │                    │
│         ▼                                      ▼                    │
│   ┌───────────┐                        ┌──────────────┐             │
│   │ Sarvam AI │ ASR + Translation      │ Image Upload │             │
│   │ Voice API │──────────────┐         │   Endpoint   │──────┐      │
│   └───────────┘              │         └──────────────┘      │      │
│                              ▼                               ▼      │
│                    ┌──────────────────────────────┐                  │
│                    │      🤖 INTAKE AGENT         │                  │
│                    │  • Entity extraction (NER)   │                  │
│                    │  • Location geocoding        │                  │
│                    │  • Issue categorization      │                  │
│                    │  • Structured output         │                  │
│                    └─────────────┬────────────────┘                  │
└──────────────────────────────────┼──────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      AI AGENT PIPELINE (LangGraph)                   │
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐  │
│  │ DUPLICATE        │    │  TRIAGE AGENT   │    │  ROUTING AGENT   │  │
│  │ DETECTION AGENT  │───▶│                 │───▶│                  │  │
│  │                  │    │ Severity: 8/10  │    │ → PWD, Ward 12   │  │
│  │ • Geo-radius     │    │ • Image damage  │    │ • Category match │  │
│  │   matching       │    │ • Voice urgency │    │ • Jurisdiction   │  │
│  │ • Semantic       │    │ • Geo-context   │    │   lookup         │  │
│  │   similarity     │    │ • Weather data  │    │ • Fallback logic │  │
│  │ • Merge/bump     │    │ • Report freq   │    │                  │  │
│  └─────────────────┘    └─────────────────┘    └────────┬─────────┘  │
│                                                          │           │
│  ┌─────────────────────────────────────────────────────┐ │           │
│  │              ESCALATION AGENT (Scheduled)            │ │           │
│  │  • Monitors SLA compliance                          │◀┘           │
│  │  • Auto-escalates overdue issues                    │             │
│  │  • Generates authority performance reports           │             │
│  └─────────────────────────────────────────────────────┘             │
│                                                                      │
│  ┌─────────────────────────────────────────────────────┐             │
│  │            VERIFICATION AGENT (Periodic)             │             │
│  │  • Geofence query for nearby app users              │             │
│  │  • Push notification / SMS for status check          │             │
│  │  • Aggregate responses → update status              │             │
│  └─────────────────────────────────────────────────────┘             │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         DATA & STORAGE LAYER                         │
│                                                                      │
│   ┌──────────────────┐  ┌───────────────┐  ┌─────────────────────┐  │
│   │  PostgreSQL +    │  │  Redis Cache   │  │  Cloud Storage      │  │
│   │  PostGIS         │  │  (sessions,    │  │  (images, audio)    │  │
│   │  (grievances,    │  │   rate limits) │  │                     │  │
│   │   users, geo)    │  │               │  │                     │  │
│   └──────────────────┘  └───────────────┘  └─────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       FRONTEND (Next.js)                             │
│                                                                      │
│   ┌──────────────┐  ┌────────────────┐  ┌────────────────────────┐  │
│   │ Public       │  │ Grievance      │  │ Authority Admin        │  │
│   │ Dashboard    │  │ Filing Form    │  │ Panel                  │  │
│   │ • Heatmap    │  │ • Image upload │  │ • Assigned issues      │  │
│   │ • Live stats │  │ • Voice record │  │ • SLA tracking         │  │
│   │ • Severity   │  │ • Location     │  │ • Response metrics     │  │
│   │   breakdown  │  │   auto-detect  │  │ • Escalation alerts    │  │
│   └──────────────┘  └────────────────┘  └────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### Data Flow — End to End

```
1. CITIZEN REPORTS ISSUE
   ├── Via Browser Voice Recording:
   │   User clicks "Record Voice" → MediaRecorder API captures audio
   │   → Audio blob sent to backend
   │   → Sarvam ASR (speech-to-text in native language)
   │   → Sarvam Translation (→ English)
   │   → Intake Agent processes text
   │
   └── Via Web App:
       User uploads image + optional description + location
       → Image sent to Gemini Vision API
       → Intake Agent processes image analysis + description

2. INTAKE AGENT (LangGraph Node 1)
   Input: raw text/image analysis
   Tools: Nominatim Geocoding API (OpenStreetMap), Sarvam NER
   Output: Structured grievance object
   {
     "description": "Large pothole on NH-44 near district hospital",
     "category": "ROAD_DAMAGE",
     "sub_category": "POTHOLE",
     "location": { "lat": 17.385, "lng": 78.4867, "address": "..." },
     "detected_objects": ["pothole", "cracked_asphalt"],
     "urgency_cues": ["large", "near hospital"],
     "source": "VOICE_RECORDING" | "IMAGE",
     "raw_transcript": "...",
     "image_url": "..."
   }

3. DUPLICATE DETECTION AGENT (LangGraph Node 2)
   Input: structured grievance
   Tools: PostGIS spatial query, embedding similarity
   Logic:
     - Search existing open grievances within 200m radius
     - Compare semantic similarity of descriptions (cosine > 0.85)
     - If duplicate found → merge, increment report_count, recalculate severity
     - If new → create new grievance record

4. TRIAGE AGENT (LangGraph Node 3)
   Input: grievance object (new or merged)
   Tools: OpenWeatherMap API, Census Data API, PostGIS
   Output: severity_score (1-10) + explanation
   Scoring formula (see Section 6 for details)

5. ROUTING AGENT (LangGraph Node 4)
   Input: categorized + scored grievance
   Tools: Authority database lookup
   Output: assigned_authority + department + SLA deadline
   Logic:
     - Map category → department (ROAD_DAMAGE → PWD)
     - Map location → jurisdiction (ward/district/state)
     - Set SLA based on severity (critical=24h, high=72h, medium=7d, low=14d)

6. STORAGE + NOTIFICATION
   - Save to PostgreSQL
   - Notify authority via email/SMS
   - Update public dashboard in real-time (WebSocket)

7. ESCALATION AGENT (Scheduled - runs every 6 hours)
   - Query grievances past SLA deadline
   - Auto-escalate to next authority level
   - Generate alert on dashboard

8. VERIFICATION AGENT (Scheduled - runs daily)
   - For issues marked "in_progress" or older than 7 days
   - Find app users within 500m radius (PostGIS)
   - Send push notification: "Has this issue been resolved?"
   - Aggregate responses → update status
```

---

## 3. Tech Stack

| Layer | Technology | Purpose | Cost |
|-------|-----------|---------|------|
| **Voice Recording** | Browser MediaRecorder API | In-browser voice capture for grievance reports | Free |
| **Voice AI** | Sarvam AI (saaras v2) | Speech-to-text in 10+ Indian languages + translation | Free tier |
| **Vision AI** | Google Gemini 2.0 Flash | Image damage detection, object recognition, severity assessment | Free (60 RPM) |
| **LLM** | Google Gemini 2.0 Flash | Entity extraction, categorization, reasoning, report generation | Free tier |
| **Agent Framework** | LangGraph (Python) | Multi-agent orchestration with state management | Free (OSS) |
| **Embeddings** | Gemini Embedding API | Semantic similarity for duplicate detection | Free tier |
| **Backend** | FastAPI (Python 3.11+) | Async REST API + WebSocket support | Free (OSS) |
| **Database** | PostgreSQL 16 + PostGIS 3.4 | Relational data + geospatial queries | Free (OSS) |
| **Cache** | Redis | Session management, rate limiting, real-time pub/sub | Free (OSS) |
| **Object Storage** | Cloudinary | Image and audio file storage | Free (25GB) |
| **Geocoding** | Nominatim (OpenStreetMap) | Address to coordinates resolution | Free (no key) |
| **Nearby POIs** | Overpass API (OpenStreetMap) | Find hospitals, schools near grievance location | Free (no key) |
| **Weather** | OpenWeatherMap API | Weather context for severity amplification | Free (60/min) |
| **Open Data** | Data.gov.in, Census India | Population density, infrastructure data | Free |
| **Frontend** | Next.js 14 (App Router) | Dashboard, grievance form, admin panel | Free (OSS) |
| **Maps** | Leaflet.js + OpenStreetMap | Grievance heatmap, location picker | Free (OSS) |
| **Charts** | Recharts | Dashboard analytics visualizations | Free (OSS) |
| **Real-time** | Socket.IO | Live dashboard updates | Free (OSS) |
| **Auth** | NextAuth.js | User authentication (citizens + authorities) | Free (OSS) |
| **Deployment** | Railway / Render | Backend hosting | Free tier |
| **Frontend Deploy** | Vercel | Next.js frontend hosting | Free tier |
| **DB Hosting** | Supabase | PostgreSQL + PostGIS cloud hosting | Free (500MB) |

> **Total Cost: $0** — Every service used has a free tier sufficient for the hackathon.

---

## 4. Directory Structure

```
nagarseva/
│
├── README.md
│
├── backend/                          # FastAPI Backend
│   ├── main.py                       # FastAPI app entry point
│   ├── requirements.txt
│   ├── .env.example                  # Environment variables template
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py               # Pydantic settings (env vars)
│   │   └── database.py               # PostgreSQL + PostGIS connection
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── grievance.py              # Grievance SQLAlchemy model
│   │   ├── user.py                   # User model (citizen + authority)
│   │   ├── authority.py              # Authority/department model
│   │   ├── verification.py           # Verification response model
│   │   └── escalation_log.py         # Escalation history model
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── grievance.py              # Pydantic request/response schemas
│   │   ├── user.py
│   │   └── triage.py                 # Severity score schema
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── grievances.py         # CRUD + filing endpoints
│   │   │   ├── voice_upload.py       # Browser voice recording upload handler
│   │   │   ├── dashboard.py          # Public dashboard data endpoints
│   │   │   ├── auth.py               # Authentication endpoints
│   │   │   ├── admin.py              # Authority admin endpoints
│   │   │   └── verification.py       # Verification endpoints
│   │   └── websocket.py              # WebSocket for live updates
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── graph.py                  # LangGraph main pipeline definition
│   │   ├── state.py                  # Shared agent state schema
│   │   ├── intake_agent.py           # Voice/image → structured data
│   │   ├── duplicate_agent.py        # Duplicate detection + merge
│   │   ├── triage_agent.py           # Severity scoring
│   │   ├── routing_agent.py          # Authority assignment
│   │   ├── escalation_agent.py       # SLA monitoring + auto-escalate
│   │   ├── verification_agent.py     # Crowdsourced status checks
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── geocoding.py          # Nominatim (OpenStreetMap) Geocoding tool
│   │       ├── weather.py            # OpenWeatherMap tool
│   │       ├── population.py         # Census/population density tool
│   │       ├── spatial_query.py      # PostGIS nearby query tool
│   │       ├── overpass.py           # OpenStreetMap Overpass API for nearby POIs
│   │       └── sarvam_tools.py       # Sarvam ASR + translation tools
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── sarvam_service.py         # Sarvam API client
│   │   ├── gemini_service.py         # Gemini Vision + LLM client
│   │   ├── storage_service.py        # Image/audio upload to cloud
│   │   ├── notification_service.py   # Email/push notifications
│   │   └── embedding_service.py      # Text embeddings for similarity
│   │
│   ├── schedulers/
│   │   ├── __init__.py
│   │   ├── escalation_scheduler.py   # Runs escalation agent every 6h
│   │   └── verification_scheduler.py # Runs verification agent daily
│   │
│   └── utils/
│       ├── __init__.py
│       ├── geo_utils.py              # Geospatial helper functions
│       └── severity_calculator.py    # Weighted severity formula
│
├── frontend/                         # Next.js Frontend
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.js
│   ├── .env.local.example
│   │
│   ├── app/
│   │   ├── layout.tsx                # Root layout with navbar
│   │   ├── page.tsx                  # Landing page / public dashboard
│   │   │
│   │   ├── dashboard/
│   │   │   ├── page.tsx              # Main public dashboard
│   │   │   └── components/
│   │   │       ├── GrievanceHeatmap.tsx
│   │   │       ├── SeverityChart.tsx
│   │   │       ├── CategoryBreakdown.tsx
│   │   │       ├── LiveFeed.tsx
│   │   │       ├── AuthorityScorecard.tsx
│   │   │       └── StatsOverview.tsx
│   │   │
│   │   ├── report/
│   │   │   ├── page.tsx              # File grievance form
│   │   │   └── components/
│   │   │       ├── ImageUploader.tsx
│   │   │       ├── LocationPicker.tsx
│   │   │       ├── VoiceRecorder.tsx  # Browser-based voice recording
│   │   │       └── GrievanceForm.tsx
│   │   │
│   │   ├── grievance/
│   │   │   └── [id]/
│   │   │       └── page.tsx          # Individual grievance detail view
│   │   │
│   │   ├── admin/
│   │   │   ├── page.tsx              # Authority admin panel
│   │   │   └── components/
│   │   │       ├── AssignedIssues.tsx
│   │   │       ├── SLATracker.tsx
│   │   │       └── EscalationAlerts.tsx
│   │   │
│   │   ├── verify/
│   │   │   └── page.tsx              # Verification page for nearby users
│   │   │
│   │   └── api/
│   │       └── auth/
│   │           └── [...nextauth]/
│   │               └── route.ts      # NextAuth API route
│   │
│   ├── components/
│   │   ├── Navbar.tsx
│   │   ├── Footer.tsx
│   │   ├── Map.tsx                   # Reusable Leaflet map component
│   │   └── SeverityBadge.tsx
│   │
│   ├── lib/
│   │   ├── api.ts                    # API client helpers
│   │   ├── socket.ts                 # Socket.IO client setup
│   │   └── types.ts                  # TypeScript interfaces
│   │
│   └── public/
│       └── assets/
│
└── docs/
    ├── API.md                        # API documentation
    ├── AGENTS.md                     # Agent pipeline documentation
    └── DEPLOYMENT.md                 # Deployment guide
```

---

## 5. Database Schema

### PostgreSQL + PostGIS Schema

```sql
-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For text similarity

-- ============================================
-- USERS TABLE
-- ============================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number    VARCHAR(15) UNIQUE,
    email           VARCHAR(255) UNIQUE,
    name            VARCHAR(255),
    role            VARCHAR(20) NOT NULL DEFAULT 'citizen',
                    -- ENUM: 'citizen', 'authority', 'admin'
    department_id   UUID REFERENCES departments(id),  -- Only for authority users
    location        GEOGRAPHY(POINT, 4326),            -- User's last known location
    is_verified     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- DEPARTMENTS TABLE
-- ============================================
CREATE TABLE departments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
                    -- e.g., 'Public Works Department', 'Water Board',
                    -- 'Sanitation', 'Electricity Board', 'Environment'
    code            VARCHAR(50) UNIQUE NOT NULL,
                    -- e.g., 'PWD', 'WATER', 'SANITATION', 'ELECTRICITY', 'ENV'
    jurisdiction    VARCHAR(50) NOT NULL,
                    -- e.g., 'WARD', 'DISTRICT', 'STATE'
    contact_email   VARCHAR(255),
    contact_phone   VARCHAR(15),
    escalation_email VARCHAR(255),  -- Higher authority email for escalation
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- GRIEVANCES TABLE (Core)
-- ============================================
CREATE TABLE grievances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tracking_id     VARCHAR(20) UNIQUE NOT NULL,
                    -- Human-readable: "NGS-2026-00001"
    
    -- Content
    title           VARCHAR(500) NOT NULL,
    description     TEXT NOT NULL,
    raw_transcript  TEXT,                              -- Original voice transcript
    raw_language    VARCHAR(10),                       -- Original language code (hi, ta, te, etc.)
    
    -- Classification
    category        VARCHAR(50) NOT NULL,
                    -- ENUM: 'ROAD_DAMAGE', 'WATER_LEAK', 'SEWAGE',
                    -- 'ELECTRICITY', 'POLLUTION', 'BRIDGE_DAMAGE',
                    -- 'GARBAGE', 'STREETLIGHT', 'OTHER'
    sub_category    VARCHAR(100),
                    -- e.g., 'POTHOLE', 'CRACK', 'FLOODING'
    
    -- Location (PostGIS)
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    address         TEXT,
    ward            VARCHAR(100),
    district        VARCHAR(100),
    state           VARCHAR(100),
    pincode         VARCHAR(10),
    
    -- Media
    image_urls      TEXT[],                            -- Array of image URLs
    audio_url       TEXT,                              -- Voice recording URL
    
    -- Severity & Triage
    severity_score  DECIMAL(3,1) NOT NULL DEFAULT 0,   -- 0.0 to 10.0
    severity_label  VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                    -- ENUM: 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'PENDING'
    severity_explanation TEXT,                          -- AI-generated explanation
    severity_signals JSONB,                            -- Breakdown of scoring signals
    
    -- Routing
    assigned_department_id UUID REFERENCES departments(id),
    assigned_authority_id  UUID REFERENCES users(id),
    
    -- Status
    status          VARCHAR(30) NOT NULL DEFAULT 'SUBMITTED',
                    -- ENUM: 'SUBMITTED', 'TRIAGED', 'ASSIGNED',
                    -- 'IN_PROGRESS', 'RESOLVED', 'VERIFIED_RESOLVED',
                    -- 'ESCALATED', 'CLOSED', 'REJECTED'
    
    -- SLA
    sla_deadline    TIMESTAMPTZ,
    escalation_level INT DEFAULT 0,                    -- 0=normal, 1=escalated, 2=critical escalation
    
    -- Duplicate tracking
    is_duplicate    BOOLEAN DEFAULT FALSE,
    parent_grievance_id UUID REFERENCES grievances(id),
    report_count    INT DEFAULT 1,                     -- Number of merged reports
    
    -- Source
    source          VARCHAR(20) NOT NULL,
                    -- ENUM: 'VOICE_RECORDING', 'WEB_IMAGE', 'WEB_FORM', 'APP'
    reporter_id     UUID REFERENCES users(id),
    reporter_phone  VARCHAR(15),                       -- For anonymous voice reports
    
    -- Embeddings for similarity search
    description_embedding VECTOR(768),                 -- For duplicate detection
    
    -- Timestamps
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    
    -- Indexes
    CONSTRAINT valid_severity CHECK (severity_score >= 0 AND severity_score <= 10)
);

-- Spatial index for location-based queries
CREATE INDEX idx_grievances_location ON grievances USING GIST (location);
-- Index for status queries
CREATE INDEX idx_grievances_status ON grievances (status);
-- Index for category queries
CREATE INDEX idx_grievances_category ON grievances (category);
-- Index for SLA monitoring
CREATE INDEX idx_grievances_sla ON grievances (sla_deadline) WHERE status NOT IN ('RESOLVED', 'CLOSED');
-- Index for duplicate detection
CREATE INDEX idx_grievances_embedding ON grievances USING ivfflat (description_embedding vector_cosine_ops);

-- ============================================
-- GRIEVANCE TIMELINE (Audit Log)
-- ============================================
CREATE TABLE grievance_timeline (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grievance_id    UUID NOT NULL REFERENCES grievances(id),
    action          VARCHAR(50) NOT NULL,
                    -- e.g., 'CREATED', 'TRIAGED', 'ASSIGNED', 'ESCALATED',
                    -- 'STATUS_CHANGED', 'SEVERITY_UPDATED', 'DUPLICATE_MERGED',
                    -- 'VERIFICATION_SENT', 'RESOLVED', 'COMMENT_ADDED'
    old_value       TEXT,
    new_value       TEXT,
    performed_by    VARCHAR(50),  -- 'SYSTEM', 'INTAKE_AGENT', 'TRIAGE_AGENT', user_id
    details         JSONB,        -- Additional context
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_timeline_grievance ON grievance_timeline (grievance_id);

-- ============================================
-- VERIFICATION RESPONSES
-- ============================================
CREATE TABLE verification_responses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grievance_id    UUID NOT NULL REFERENCES grievances(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    is_resolved     BOOLEAN NOT NULL,
    comment         TEXT,
    photo_url       TEXT,            -- Optional verification photo
    responded_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_verification_grievance ON verification_responses (grievance_id);

-- ============================================
-- AUTHORITY PERFORMANCE METRICS
-- ============================================
CREATE VIEW authority_performance AS
SELECT
    d.id AS department_id,
    d.name AS department_name,
    COUNT(g.id) AS total_assigned,
    COUNT(g.id) FILTER (WHERE g.status = 'RESOLVED' OR g.status = 'VERIFIED_RESOLVED') AS total_resolved,
    COUNT(g.id) FILTER (WHERE g.status = 'ESCALATED') AS total_escalated,
    COUNT(g.id) FILTER (WHERE g.sla_deadline < NOW() AND g.status NOT IN ('RESOLVED', 'CLOSED')) AS sla_breached,
    AVG(EXTRACT(EPOCH FROM (g.resolved_at - g.created_at)) / 3600)
        FILTER (WHERE g.resolved_at IS NOT NULL) AS avg_resolution_hours,
    ROUND(
        COUNT(g.id) FILTER (WHERE g.status IN ('RESOLVED', 'VERIFIED_RESOLVED'))::DECIMAL /
        NULLIF(COUNT(g.id), 0) * 100, 1
    ) AS resolution_rate_pct
FROM departments d
LEFT JOIN grievances g ON g.assigned_department_id = d.id
GROUP BY d.id, d.name;
```

---

## 6. AI Agent Pipeline — Detailed Design

### 6.1 LangGraph Pipeline Definition

The entire agent pipeline is orchestrated using **LangGraph**, which provides:
- Explicit state management between agents
- Conditional routing (e.g., skip duplicate agent if image-only report)
- Error recovery and retry logic
- Observability and logging

#### Shared State Schema

```python
# backend/agents/state.py
from typing import TypedDict, Optional, Literal
from dataclasses import dataclass, field

class GrievanceState(TypedDict):
    """Shared state passed between all agents in the pipeline."""
    
    # --- Input (set at pipeline start) ---
    source: Literal["VOICE_RECORDING", "WEB_IMAGE", "WEB_FORM"]
    raw_audio_url: Optional[str]        # For voice reports
    raw_image_urls: list[str]           # For image reports
    raw_text: Optional[str]             # User-typed description
    reporter_phone: Optional[str]
    reporter_id: Optional[str]
    reporter_location: Optional[dict]   # {"lat": float, "lng": float}
    
    # --- Intake Agent Output ---
    transcript: Optional[str]           # Transcribed text (from voice)
    translated_text: Optional[str]      # English translation
    original_language: Optional[str]    # Detected language
    title: Optional[str]
    description: str
    category: Optional[str]
    sub_category: Optional[str]
    location: Optional[dict]            # {"lat": float, "lng": float, "address": str}
    detected_objects: list[str]         # From image analysis
    urgency_cues: list[str]            # From text/image analysis
    image_analysis: Optional[dict]      # Full Gemini vision output
    
    # --- Duplicate Agent Output ---
    is_duplicate: bool
    parent_grievance_id: Optional[str]
    merged_report_count: Optional[int]
    similarity_score: Optional[float]
    
    # --- Triage Agent Output ---
    severity_score: Optional[float]     # 0.0 - 10.0
    severity_label: Optional[str]       # CRITICAL/HIGH/MEDIUM/LOW
    severity_explanation: Optional[str]
    severity_signals: Optional[dict]    # Breakdown of all signals
    
    # --- Routing Agent Output ---
    assigned_department: Optional[str]
    assigned_department_id: Optional[str]
    assigned_authority_id: Optional[str]
    sla_deadline: Optional[str]         # ISO datetime
    routing_explanation: Optional[str]
    
    # --- Pipeline metadata ---
    grievance_id: Optional[str]         # Created after storage
    tracking_id: Optional[str]          # Human-readable ID
    errors: list[str]                   # Accumulated errors
    pipeline_status: str                # "processing", "completed", "failed"
```

#### Graph Definition

```python
# backend/agents/graph.py
from langgraph.graph import StateGraph, END
from agents.state import GrievanceState
from agents.intake_agent import intake_node
from agents.duplicate_agent import duplicate_detection_node
from agents.triage_agent import triage_node
from agents.routing_agent import routing_node

def build_grievance_pipeline() -> StateGraph:
    """Build the main grievance processing pipeline."""
    
    workflow = StateGraph(GrievanceState)
    
    # Add nodes
    workflow.add_node("intake", intake_node)
    workflow.add_node("duplicate_detection", duplicate_detection_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("routing", routing_node)
    workflow.add_node("save_grievance", save_grievance_node)
    workflow.add_node("notify", notification_node)
    
    # Define edges
    workflow.set_entry_point("intake")
    workflow.add_edge("intake", "duplicate_detection")
    
    # Conditional: if duplicate, skip triage (use parent's severity)
    workflow.add_conditional_edges(
        "duplicate_detection",
        lambda state: "merge_and_end" if state["is_duplicate"] else "triage",
        {
            "triage": "triage",
            "merge_and_end": "save_grievance"
        }
    )
    
    workflow.add_edge("triage", "routing")
    workflow.add_edge("routing", "save_grievance")
    workflow.add_edge("save_grievance", "notify")
    workflow.add_edge("notify", END)
    
    return workflow.compile()
```

---

### 6.2 Intake Agent — Detailed Implementation

The Intake Agent is the first node. It handles **two completely different input types** (voice and image) and produces a unified structured output.

#### Voice Intake Flow

```python
# backend/agents/intake_agent.py

async def intake_node(state: GrievanceState) -> GrievanceState:
    """
    Process raw citizen input (voice or image) into structured grievance data.
    
    Voice flow:  audio → Sarvam ASR → Sarvam Translate → Gemini NER → structured output
    Image flow:  image → Gemini Vision → Gemini NER → structured output
    """
    
    if state["source"] == "VOICE_RECORDING":
        return await _process_voice_input(state)
    else:
        return await _process_image_input(state)


async def _process_voice_input(state: GrievanceState) -> GrievanceState:
    """
    Step 1: Sarvam ASR — Transcribe audio in native language
    Step 2: Sarvam Translate — Translate to English
    Step 3: Gemini LLM — Extract entities + categorize
    Step 4: Nominatim (OpenStreetMap) — Geocode any mentioned location
    """
    
    # Step 1: Speech-to-Text using Sarvam
    # API: POST https://api.sarvam.ai/speech-to-text
    transcript_result = await sarvam_service.speech_to_text(
        audio_url=state["raw_audio_url"],
        model="saaras:v2",
        language_code="auto"  # Auto-detect language
    )
    # Returns: {"transcript": "सड़क पर बहुत बड़ा गड्ढा है...", "language": "hi"}
    
    original_language = transcript_result["language"]
    raw_transcript = transcript_result["transcript"]
    
    # Step 2: Translation to English using Sarvam
    # API: POST https://api.sarvam.ai/translate
    if original_language != "en":
        translation = await sarvam_service.translate(
            text=raw_transcript,
            source_language=original_language,
            target_language="en"
        )
        english_text = translation["translated_text"]
    else:
        english_text = raw_transcript
    
    # Step 3: Entity extraction + categorization using Gemini
    extraction_prompt = f"""
    You are a civic grievance intake processor. Extract structured information 
    from this citizen's complaint.
    
    Citizen's report (translated to English):
    "{english_text}"
    
    Extract the following in JSON format:
    {{
        "title": "Brief title (max 100 chars)",
        "description": "Detailed description of the issue",
        "category": "One of: ROAD_DAMAGE, WATER_LEAK, SEWAGE, ELECTRICITY, 
                     POLLUTION, BRIDGE_DAMAGE, GARBAGE, STREETLIGHT, OTHER",
        "sub_category": "Specific sub-type (e.g., POTHOLE, CRACK, FLOODING)",
        "mentioned_location": "Any location/landmark mentioned",
        "urgency_cues": ["list", "of", "urgency", "indicators"],
        "affected_infrastructure": "What infrastructure is affected"
    }}
    """
    
    extracted = await gemini_service.generate_structured(
        prompt=extraction_prompt,
        response_schema=IntakeExtractionSchema
    )
    
    # Step 4: Geocoding — resolve location using Nominatim (OpenStreetMap)
    location = None
    if extracted.get("mentioned_location"):
        geocode_result = await geocoding_tool.geocode(
            address=extracted["mentioned_location"]
        )
        location = {
            "lat": geocode_result["lat"],
            "lng": geocode_result["lng"],
            "address": geocode_result["formatted_address"],
            "ward": geocode_result.get("ward"),
            "district": geocode_result.get("district"),
            "state": geocode_result.get("state"),
            "pincode": geocode_result.get("pincode")
        }
    elif state.get("reporter_location"):
        # Fallback: use caller's location if available
        location = state["reporter_location"]
    
    # Update state
    return {
        **state,
        "transcript": raw_transcript,
        "translated_text": english_text,
        "original_language": original_language,
        "title": extracted["title"],
        "description": extracted["description"],
        "category": extracted["category"],
        "sub_category": extracted.get("sub_category"),
        "location": location,
        "urgency_cues": extracted.get("urgency_cues", []),
        "detected_objects": [],
    }
```

#### Image Intake Flow

```python
async def _process_image_input(state: GrievanceState) -> GrievanceState:
    """
    Step 1: Gemini Vision — Analyze image for damage type, severity cues, objects
    Step 2: Gemini LLM — Combine image analysis + user text into structured output
    Step 3: Nominatim (OpenStreetMap) — Geocode location (from EXIF, user input, or image analysis)
    """
    
    # Step 1: Image Analysis using Gemini Vision
    vision_prompt = """
    Analyze this image of a civic infrastructure issue. Provide a detailed assessment:
    
    {
        "damage_type": "Type of damage/issue visible",
        "detected_objects": ["list of objects/issues detected"],
        "severity_visual_cues": {
            "damage_extent": "minor/moderate/severe/critical",
            "area_affected": "small/medium/large",
            "structural_risk": "none/low/medium/high",
            "safety_hazard": "none/low/medium/high/immediate"
        },
        "description": "Detailed description of what is visible",
        "suggested_category": "ROAD_DAMAGE/WATER_LEAK/SEWAGE/ELECTRICITY/POLLUTION/BRIDGE_DAMAGE/GARBAGE/STREETLIGHT/OTHER",
        "suggested_sub_category": "Specific sub-type",
        "landmarks_visible": ["any visible landmarks or location clues"],
        "confidence": 0.0 to 1.0
    }
    """
    
    image_analysis = await gemini_service.analyze_image(
        image_urls=state["raw_image_urls"],
        prompt=vision_prompt,
        response_schema=ImageAnalysisSchema
    )
    
    # Step 2: Combine image analysis with any user-provided text
    user_text = state.get("raw_text", "")
    combined_prompt = f"""
    Combine this image analysis with the user's description to create a 
    structured grievance report.
    
    Image Analysis: {json.dumps(image_analysis)}
    User Description: "{user_text}"
    
    Output:
    {{
        "title": "Brief title (max 100 chars)",
        "description": "Comprehensive description combining visual and textual info",
        "category": "Final category",
        "sub_category": "Final sub-category",
        "urgency_cues": ["combined urgency indicators from both sources"]
    }}
    """
    
    structured = await gemini_service.generate_structured(
        prompt=combined_prompt,
        response_schema=IntakeExtractionSchema
    )
    
    # Step 3: Location resolution
    location = state.get("reporter_location")  # From browser geolocation
    if not location and image_analysis.get("landmarks_visible"):
        # Try geocoding from visible landmarks
        landmark_text = ", ".join(image_analysis["landmarks_visible"])
        geocode_result = await geocoding_tool.geocode(address=landmark_text)
        if geocode_result:
            location = {
                "lat": geocode_result["lat"],
                "lng": geocode_result["lng"],
                "address": geocode_result["formatted_address"]
            }
    
    return {
        **state,
        "title": structured["title"],
        "description": structured["description"],
        "category": structured["category"],
        "sub_category": structured.get("sub_category"),
        "location": location,
        "detected_objects": image_analysis.get("detected_objects", []),
        "urgency_cues": structured.get("urgency_cues", []),
        "image_analysis": image_analysis,
    }
```

---

### 6.3 Duplicate Detection Agent — Detailed Implementation

```python
# backend/agents/duplicate_agent.py

async def duplicate_detection_node(state: GrievanceState) -> GrievanceState:
    """
    Check if this grievance is a duplicate of an existing open issue.
    
    Strategy:
    1. Spatial filter: Find open grievances within 200m radius
    2. Category filter: Same category
    3. Semantic filter: Description embedding cosine similarity > 0.85
    4. If duplicate → merge into parent, increment report_count
    """
    
    location = state.get("location")
    if not location:
        # Can't do duplicate detection without location
        return {**state, "is_duplicate": False}
    
    # Step 1: Spatial + Category query using PostGIS
    nearby_query = """
        SELECT id, description, category, description_embedding, 
               report_count, severity_score,
               ST_Distance(
                   location::geography,
                   ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
               ) as distance_meters
        FROM grievances 
        WHERE status NOT IN ('RESOLVED', 'CLOSED', 'REJECTED')
          AND category = %s
          AND ST_DWithin(
              location::geography,
              ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
              200  -- 200 meter radius
          )
        ORDER BY distance_meters ASC
        LIMIT 10;
    """
    
    nearby_grievances = await db.fetch_all(
        nearby_query, 
        [location["lng"], location["lat"], state["category"],
         location["lng"], location["lat"]]
    )
    
    if not nearby_grievances:
        return {**state, "is_duplicate": False}
    
    # Step 2: Generate embedding for new description
    new_embedding = await embedding_service.get_embedding(state["description"])
    
    # Step 3: Compare semantic similarity
    best_match = None
    best_similarity = 0.0
    
    for grievance in nearby_grievances:
        if grievance["description_embedding"]:
            similarity = cosine_similarity(
                new_embedding, 
                grievance["description_embedding"]
            )
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = grievance
    
    # Step 4: Threshold check
    SIMILARITY_THRESHOLD = 0.85
    
    if best_match and best_similarity >= SIMILARITY_THRESHOLD:
        # This is a duplicate — merge into parent
        new_count = best_match["report_count"] + 1
        
        # Update parent grievance report count
        await db.execute(
            "UPDATE grievances SET report_count = %s, updated_at = NOW() WHERE id = %s",
            [new_count, best_match["id"]]
        )
        
        # Log the merge
        await db.execute(
            """INSERT INTO grievance_timeline 
               (grievance_id, action, details, performed_by)
               VALUES (%s, 'DUPLICATE_MERGED', %s, 'DUPLICATE_AGENT')""",
            [best_match["id"], json.dumps({
                "merged_description": state["description"],
                "similarity_score": best_similarity,
                "new_report_count": new_count,
                "reporter_phone": state.get("reporter_phone")
            })]
        )
        
        return {
            **state,
            "is_duplicate": True,
            "parent_grievance_id": str(best_match["id"]),
            "merged_report_count": new_count,
            "similarity_score": best_similarity,
            "severity_score": best_match["severity_score"],  # Use parent's severity
        }
    
    return {**state, "is_duplicate": False}
```

---

### 6.4 Triage Agent — Detailed Severity Scoring

This is the **most critical agent** — it's where the core AI reasoning happens.

#### Severity Scoring Formula

```
SEVERITY_SCORE = (
    W1 × Visual_Damage_Score +
    W2 × Urgency_Text_Score +
    W3 × Category_Risk_Score +
    W4 × Geospatial_Context_Score +
    W5 × Population_Impact_Score +
    W6 × Weather_Amplification +
    W7 × Report_Frequency_Score +
    W8 × Recency_Decay_Score
)

Where weights:
W1 = 0.25  (Visual damage — highest for image reports)
W2 = 0.15  (Text urgency — highest for voice reports)
W3 = 0.15  (Category inherent risk)
W4 = 0.15  (Geospatial context — near critical infrastructure)
W5 = 0.10  (Population density impact)
W6 = 0.08  (Weather conditions amplification)
W7 = 0.07  (Report frequency — community signal)
W8 = 0.05  (Time-based urgency)

All sub-scores normalized to 0-10 scale.
Final score clamped to [1.0, 10.0].
```

#### Full Triage Agent Implementation

```python
# backend/agents/triage_agent.py

async def triage_node(state: GrievanceState) -> GrievanceState:
    """
    Multi-signal severity assessment.
    
    Combines 8 different signals using weighted scoring.
    Uses Gemini for reasoning over ambiguous cases.
    Produces explainable severity with full signal breakdown.
    """
    
    signals = {}
    
    # ──────────────────────────────────────────────
    # Signal 1: VISUAL DAMAGE SCORE (weight: 0.25)
    # ──────────────────────────────────────────────
    if state.get("image_analysis"):
        visual_cues = state["image_analysis"].get("severity_visual_cues", {})
        
        damage_scores = {
            "minor": 2, "moderate": 5, "severe": 7.5, "critical": 10
        }
        area_scores = {
            "small": 2, "medium": 5, "large": 8
        }
        structural_scores = {
            "none": 0, "low": 3, "medium": 6, "high": 9
        }
        safety_scores = {
            "none": 0, "low": 2, "medium": 5, "high": 8, "immediate": 10
        }
        
        visual_score = (
            damage_scores.get(visual_cues.get("damage_extent", "moderate"), 5) * 0.3 +
            area_scores.get(visual_cues.get("area_affected", "medium"), 5) * 0.2 +
            structural_scores.get(visual_cues.get("structural_risk", "low"), 3) * 0.25 +
            safety_scores.get(visual_cues.get("safety_hazard", "low"), 2) * 0.25
        )
        signals["visual_damage"] = round(visual_score, 1)
    else:
        # No image — use Gemini to estimate from text description
        text_severity_prompt = f"""
        Rate the physical severity of this civic issue from 0-10 based only on 
        the description. Consider structural risk and safety hazard.
        
        Description: "{state['description']}"
        Category: {state['category']}
        
        Return just a JSON: {{"score": float, "reasoning": "brief explanation"}}
        """
        result = await gemini_service.generate_structured(
            prompt=text_severity_prompt,
            response_schema={"score": float, "reasoning": str}
        )
        signals["visual_damage"] = result["score"]
    
    # ──────────────────────────────────────────────
    # Signal 2: TEXT URGENCY SCORE (weight: 0.15)
    # ──────────────────────────────────────────────
    urgency_prompt = f"""
    Analyze the urgency level of this civic complaint. 
    Consider: immediacy of danger, emotional urgency, explicit urgency words.
    
    Text: "{state.get('translated_text') or state['description']}"
    Urgency cues detected: {state.get('urgency_cues', [])}
    
    Return JSON: {{"score": 0-10, "reasoning": "explanation"}}
    
    Guidelines:
    - 9-10: Immediate danger to life ("bridge collapsing", "live wire")
    - 7-8: Serious risk ("deep pothole on highway", "sewage in drinking water") 
    - 5-6: Significant inconvenience ("road flooded", "no water for 3 days")
    - 3-4: Moderate issue ("streetlight broken", "garbage not collected")
    - 1-2: Minor ("small crack", "faded road markings")
    """
    urgency_result = await gemini_service.generate_structured(
        prompt=urgency_prompt,
        response_schema={"score": float, "reasoning": str}
    )
    signals["text_urgency"] = urgency_result["score"]
    
    # ──────────────────────────────────────────────
    # Signal 3: CATEGORY RISK SCORE (weight: 0.15)
    # ──────────────────────────────────────────────
    category_risk_map = {
        "BRIDGE_DAMAGE":  9.0,   # Structural failure risk
        "ELECTRICITY":    8.0,   # Electrocution risk
        "WATER_LEAK":     6.5,   # Resource waste + flooding
        "SEWAGE":         7.0,   # Health hazard
        "POLLUTION":      6.0,   # Environmental + health
        "ROAD_DAMAGE":    5.5,   # Accident risk
        "GARBAGE":        4.0,   # Sanitation
        "STREETLIGHT":    3.5,   # Safety at night
        "OTHER":          5.0,   # Default moderate
    }
    signals["category_risk"] = category_risk_map.get(state["category"], 5.0)
    
    # ──────────────────────────────────────────────
    # Signal 4: GEOSPATIAL CONTEXT (weight: 0.15)
    # ──────────────────────────────────────────────
    if state.get("location"):
        lat, lng = state["location"]["lat"], state["location"]["lng"]
        
        # Check proximity to critical infrastructure using OpenStreetMap Overpass API
        nearby_critical = await check_nearby_critical_places(lat, lng, radius=500)
        # Returns: {"hospital": 150m, "school": 300m, "highway": 50m}
        # Uses free Overpass API — no API key needed
        
        geo_score = 3.0  # Base score
        
        critical_multipliers = {
            "hospital": 2.5,
            "school": 2.0,
            "railway_station": 2.0,
            "bus_station": 1.5,
            "highway": 2.0,
            "bridge": 2.5,
            "government_building": 1.5,
            "market": 1.5,
            "temple": 1.0,      # Place of worship / gathering
        }
        
        for place_type, distance in nearby_critical.items():
            multiplier = critical_multipliers.get(place_type, 1.0)
            # Closer = higher score, diminishes with distance
            proximity_factor = max(0, 1 - (distance / 500))
            geo_score += multiplier * proximity_factor
        
        signals["geospatial_context"] = min(10.0, round(geo_score, 1))
    else:
        signals["geospatial_context"] = 5.0  # Unknown location, neutral
    
    # ──────────────────────────────────────────────
    # Signal 5: POPULATION IMPACT (weight: 0.10)
    # ──────────────────────────────────────────────
    if state.get("location"):
        # Fetch population density from Census India / Data.gov.in
        pop_density = await get_population_density(
            state["location"].get("district"),
            state["location"].get("state")
        )
        # Normalize: India avg ~400/km², max urban ~30000/km²
        if pop_density:
            normalized = min(10.0, (pop_density / 3000) * 10)
            signals["population_impact"] = round(normalized, 1)
        else:
            signals["population_impact"] = 5.0
    else:
        signals["population_impact"] = 5.0
    
    # ──────────────────────────────────────────────
    # Signal 6: WEATHER AMPLIFICATION (weight: 0.08)
    # ──────────────────────────────────────────────
    if state.get("location"):
        weather = await weather_tool.get_current_weather(
            lat=state["location"]["lat"],
            lon=state["location"]["lng"]
        )
        # API: https://api.openweathermap.org/data/2.5/weather
        
        weather_score = 3.0  # Base neutral
        
        # Weather amplification rules
        if state["category"] == "ROAD_DAMAGE":
            if weather.get("rain_mm", 0) > 10:
                weather_score = 8.0  # Rain + road damage = flooding/accident risk
            elif weather.get("rain_mm", 0) > 5:
                weather_score = 6.0
                
        elif state["category"] == "WATER_LEAK":
            if weather.get("temp_celsius", 25) > 40:
                weather_score = 8.5  # Water leak in extreme heat = critical
            elif weather.get("rain_forecast_48h", False):
                weather_score = 7.0  # Leak + rain = flooding
                
        elif state["category"] == "ELECTRICITY":
            if weather.get("rain_mm", 0) > 0:
                weather_score = 9.0  # Electrical issue in rain = electrocution risk
            if weather.get("wind_speed_kmh", 0) > 50:
                weather_score = 8.0
                
        elif state["category"] == "SEWAGE":
            if weather.get("rain_mm", 0) > 5:
                weather_score = 8.5  # Sewage + rain = overflow + contamination
                
        elif state["category"] == "POLLUTION":
            if weather.get("wind_speed_kmh", 0) < 5:
                weather_score = 7.0  # Low wind = pollution stays concentrated
        
        signals["weather_amplification"] = weather_score
    else:
        signals["weather_amplification"] = 3.0
    
    # ──────────────────────────────────────────────
    # Signal 7: REPORT FREQUENCY (weight: 0.07)
    # ──────────────────────────────────────────────
    report_count = state.get("merged_report_count", 1)
    # Logarithmic scaling: 1 report = 2, 5 reports = 5, 20+ reports = 9
    frequency_score = min(10.0, 2.0 + 3.0 * math.log2(max(1, report_count)))
    signals["report_frequency"] = round(frequency_score, 1)
    
    # ──────────────────────────────────────────────
    # Signal 8: RECENCY DECAY (weight: 0.05)
    # ──────────────────────────────────────────────
    # For new reports, this is always 5.0 (neutral)
    # For existing reports that are re-evaluated, older = higher urgency
    signals["recency_decay"] = 5.0  # New report default
    
    # ──────────────────────────────────────────────
    # CALCULATE FINAL WEIGHTED SCORE
    # ──────────────────────────────────────────────
    weights = {
        "visual_damage": 0.25,
        "text_urgency": 0.15,
        "category_risk": 0.15,
        "geospatial_context": 0.15,
        "population_impact": 0.10,
        "weather_amplification": 0.08,
        "report_frequency": 0.07,
        "recency_decay": 0.05,
    }
    
    final_score = sum(
        signals[key] * weights[key] for key in weights
    )
    final_score = max(1.0, min(10.0, round(final_score, 1)))
    
    # Determine severity label
    if final_score >= 8.0:
        severity_label = "CRITICAL"
    elif final_score >= 6.0:
        severity_label = "HIGH"
    elif final_score >= 4.0:
        severity_label = "MEDIUM"
    else:
        severity_label = "LOW"
    
    # Generate human-readable explanation using Gemini
    explanation_prompt = f"""
    Generate a concise severity explanation for a civic grievance.
    
    Issue: {state['title']}
    Category: {state['category']}
    Severity Score: {final_score}/10 ({severity_label})
    
    Signal breakdown:
    {json.dumps(signals, indent=2)}
    
    Write 2-3 sentences explaining WHY this severity was assigned.
    Reference specific signals that drove the score up or down.
    """
    
    explanation = await gemini_service.generate_text(explanation_prompt)
    
    return {
        **state,
        "severity_score": final_score,
        "severity_label": severity_label,
        "severity_explanation": explanation,
        "severity_signals": signals,
    }
```

---

### 6.5 Routing Agent — Authority Assignment

```python
# backend/agents/routing_agent.py

# Category → Department mapping
CATEGORY_DEPARTMENT_MAP = {
    "ROAD_DAMAGE":    "PWD",          # Public Works Department
    "BRIDGE_DAMAGE":  "PWD",
    "WATER_LEAK":     "WATER",        # Water Board / Jal Board
    "SEWAGE":         "SANITATION",   # Municipal Sanitation
    "ELECTRICITY":    "ELECTRICITY",  # Electricity Board (DISCOM)
    "POLLUTION":      "ENV",          # Pollution Control Board
    "GARBAGE":        "SANITATION",
    "STREETLIGHT":    "ELECTRICITY",
    "OTHER":          "MUNICIPAL",    # Municipal Corporation
}

# Severity → SLA mapping
SEVERITY_SLA_MAP = {
    "CRITICAL": timedelta(hours=24),
    "HIGH":     timedelta(hours=72),
    "MEDIUM":   timedelta(days=7),
    "LOW":      timedelta(days=14),
}

async def routing_node(state: GrievanceState) -> GrievanceState:
    """
    Route grievance to the correct department and authority.
    
    Steps:
    1. Map category → department
    2. Handle ambiguous categories using Gemini reasoning
    3. Map location → jurisdiction (ward/district)
    4. Find specific authority within department + jurisdiction
    5. Set SLA deadline based on severity
    """
    
    category = state["category"]
    
    # Step 1: Determine department
    dept_code = CATEGORY_DEPARTMENT_MAP.get(category, "MUNICIPAL")
    
    # Step 2: Handle ambiguous cases
    # e.g., "sewage on road" could be SANITATION or PWD
    ambiguous_categories = {
        ("SEWAGE", "ROAD_DAMAGE"),
        ("WATER_LEAK", "ROAD_DAMAGE"),
        ("GARBAGE", "POLLUTION"),
    }
    
    if any(category in combo for combo in ambiguous_categories):
        disambiguation_prompt = f"""
        A civic grievance has been categorized as '{category}' but may involve
        multiple departments. Determine the PRIMARY responsible department.
        
        Description: "{state['description']}"
        Detected objects: {state.get('detected_objects', [])}
        
        Departments:
        - PWD: Roads, bridges, structural infrastructure
        - WATER: Water supply, pipelines, taps
        - SANITATION: Sewage, garbage collection, drains
        - ELECTRICITY: Power lines, streetlights, transformers
        - ENV: Air/water pollution, industrial waste
        - MUNICIPAL: General municipal issues
        
        Return JSON: {{"primary_department": "CODE", "secondary_department": "CODE or null", 
                       "reasoning": "why this department"}}
        """
        
        routing_decision = await gemini_service.generate_structured(
            prompt=disambiguation_prompt,
            response_schema=RoutingDecisionSchema
        )
        dept_code = routing_decision["primary_department"]
    
    # Step 3: Find department and authority for the jurisdiction
    location = state.get("location", {})
    ward = location.get("ward", "UNKNOWN")
    district = location.get("district", "UNKNOWN")
    
    department = await db.fetch_one(
        "SELECT * FROM departments WHERE code = %s", [dept_code]
    )
    
    # Step 4: Find available authority in this department + area
    authority = await db.fetch_one("""
        SELECT u.* FROM users u
        JOIN departments d ON u.department_id = d.id
        WHERE d.code = %s AND u.role = 'authority'
        ORDER BY 
            -- Prefer authority in same ward/district
            CASE WHEN u.jurisdiction_area = %s THEN 0 ELSE 1 END,
            -- Then by current workload (fewer active cases first)
            (SELECT COUNT(*) FROM grievances g 
             WHERE g.assigned_authority_id = u.id 
             AND g.status NOT IN ('RESOLVED', 'CLOSED')) ASC
        LIMIT 1
    """, [dept_code, district])
    
    # Step 5: Set SLA deadline
    sla_delta = SEVERITY_SLA_MAP.get(state["severity_label"], timedelta(days=7))
    sla_deadline = datetime.utcnow() + sla_delta
    
    return {
        **state,
        "assigned_department": dept_code,
        "assigned_department_id": str(department["id"]) if department else None,
        "assigned_authority_id": str(authority["id"]) if authority else None,
        "sla_deadline": sla_deadline.isoformat(),
        "routing_explanation": f"Routed to {dept_code} ({department['name'] if department else 'Unknown'}) "
                              f"in {district}. SLA: {sla_delta.days}d {sla_delta.seconds//3600}h "
                              f"(severity: {state['severity_label']})",
    }
```

---

### 6.6 Escalation Agent (Scheduled)

```python
# backend/agents/escalation_agent.py

async def run_escalation_check():
    """
    Scheduled job — runs every 6 hours.
    Checks for SLA breaches and auto-escalates.
    """
    
    # Find grievances past SLA deadline that aren't resolved
    overdue = await db.fetch_all("""
        SELECT g.*, d.name as dept_name, d.escalation_email,
               u.name as authority_name, u.email as authority_email
        FROM grievances g
        JOIN departments d ON g.assigned_department_id = d.id
        LEFT JOIN users u ON g.assigned_authority_id = u.id
        WHERE g.sla_deadline < NOW()
          AND g.status NOT IN ('RESOLVED', 'VERIFIED_RESOLVED', 'CLOSED')
          AND g.escalation_level < 2  -- Max 2 escalations
        ORDER BY g.severity_score DESC;
    """)
    
    for grievance in overdue:
        new_level = grievance["escalation_level"] + 1
        hours_overdue = (datetime.utcnow() - grievance["sla_deadline"]).total_seconds() / 3600
        
        # Generate escalation report using Gemini
        report_prompt = f"""
        Generate a formal escalation notice for an overdue civic grievance.
        
        Tracking ID: {grievance['tracking_id']}
        Issue: {grievance['title']}
        Severity: {grievance['severity_label']} ({grievance['severity_score']}/10)
        Department: {grievance['dept_name']}
        Assigned to: {grievance['authority_name']}
        SLA Deadline: {grievance['sla_deadline']}
        Hours Overdue: {round(hours_overdue, 1)}
        Report Count: {grievance['report_count']} citizens affected
        Escalation Level: {new_level}
        
        Write a concise, professional escalation notice (3-4 sentences).
        """
        
        escalation_notice = await gemini_service.generate_text(report_prompt)
        
        # Update grievance
        await db.execute("""
            UPDATE grievances 
            SET escalation_level = %s, status = 'ESCALATED', updated_at = NOW()
            WHERE id = %s
        """, [new_level, grievance["id"]])
        
        # Log to timeline
        await db.execute("""
            INSERT INTO grievance_timeline (grievance_id, action, details, performed_by)
            VALUES (%s, 'ESCALATED', %s, 'ESCALATION_AGENT')
        """, [grievance["id"], json.dumps({
            "escalation_level": new_level,
            "hours_overdue": round(hours_overdue, 1),
            "notice": escalation_notice
        })])
        
        # Send notification to higher authority
        await notification_service.send_escalation_email(
            to=grievance["escalation_email"],
            subject=f"[ESCALATION L{new_level}] {grievance['tracking_id']} - {grievance['title']}",
            body=escalation_notice
        )
        
        # Send SMS to original reporter with update
        if grievance.get("reporter_phone"):
            await notification_service.send_sms(
                phone=grievance["reporter_phone"],
                message=f"NagarSeva Update: Your complaint {grievance['tracking_id']} "
                        f"has been escalated to higher authorities. We are working on it."
            )
    
    logger.info(f"Escalation check complete. Escalated {len(overdue)} grievances.")
```

---

### 6.7 Verification Agent (Scheduled)

```python
# backend/agents/verification_agent.py

async def run_verification_loop():
    """
    Scheduled job — runs once daily.
    
    For issues that are IN_PROGRESS or older than 7 days:
    1. Find app users within 500m radius
    2. Send push notification asking if the issue is resolved
    3. Aggregate responses after 24h
    4. Update status based on consensus
    """
    
    # Find grievances needing verification
    candidates = await db.fetch_all("""
        SELECT * FROM grievances
        WHERE (status = 'IN_PROGRESS' 
               OR (status = 'ASSIGNED' AND created_at < NOW() - INTERVAL '7 days'))
          AND id NOT IN (
              -- Exclude recently verified (within last 3 days)
              SELECT DISTINCT grievance_id FROM verification_responses
              WHERE responded_at > NOW() - INTERVAL '3 days'
          )
        ORDER BY severity_score DESC
        LIMIT 50;  -- Process top 50 per run
    """)
    
    for grievance in candidates:
        # Find nearby users within 500m
        nearby_users = await db.fetch_all("""
            SELECT id, phone_number, name FROM users
            WHERE role = 'citizen'
              AND location IS NOT NULL
              AND ST_DWithin(
                  location::geography,
                  ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                  500
              )
              AND id != %s  -- Exclude the reporter
            LIMIT 10;
        """, [
            grievance["location"].x, grievance["location"].y,
            grievance["reporter_id"]
        ])
        
        if not nearby_users:
            # Fallback: Send SMS to original reporter
            if grievance.get("reporter_phone"):
                await notification_service.send_sms(
                    phone=grievance["reporter_phone"],
                    message=f"NagarSeva: Has the issue you reported "
                            f"({grievance['tracking_id']}) been resolved? "
                            f"Reply YES or NO."
                )
            continue
        
        # Send push notifications to nearby users
        for user in nearby_users:
            await notification_service.send_push(
                user_id=user["id"],
                title="Help verify a civic issue near you!",
                body=f"Has this issue been resolved: {grievance['title']}?",
                data={
                    "grievance_id": str(grievance["id"]),
                    "action": "verify",
                    "verify_url": f"/verify/{grievance['id']}"
                }
            )
        
        # Log verification request
        await db.execute("""
            INSERT INTO grievance_timeline (grievance_id, action, details, performed_by)
            VALUES (%s, 'VERIFICATION_SENT', %s, 'VERIFICATION_AGENT')
        """, [grievance["id"], json.dumps({
            "users_notified": len(nearby_users),
            "fallback_sms": len(nearby_users) == 0
        })])


async def aggregate_verification_responses(grievance_id: str):
    """
    Called after verification window closes (24h).
    Aggregates user responses and updates status.
    """
    
    responses = await db.fetch_all("""
        SELECT is_resolved, COUNT(*) as count
        FROM verification_responses
        WHERE grievance_id = %s
          AND responded_at > NOW() - INTERVAL '24 hours'
        GROUP BY is_resolved;
    """, [grievance_id])
    
    total = sum(r["count"] for r in responses)
    if total == 0:
        return  # No responses, keep current status
    
    resolved_count = next(
        (r["count"] for r in responses if r["is_resolved"]), 0
    )
    resolution_ratio = resolved_count / total
    
    if resolution_ratio >= 0.7:  # 70%+ say resolved
        await db.execute("""
            UPDATE grievances 
            SET status = 'VERIFIED_RESOLVED', resolved_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, [grievance_id])
        status = "VERIFIED_RESOLVED"
    elif resolution_ratio <= 0.3:  # 70%+ say NOT resolved
        # Bump severity slightly (community says it's still a problem)
        await db.execute("""
            UPDATE grievances 
            SET severity_score = LEAST(10, severity_score + 0.5), updated_at = NOW()
            WHERE id = %s
        """, [grievance_id])
        status = "STILL_UNRESOLVED"
    else:
        status = "INCONCLUSIVE"
    
    await db.execute("""
        INSERT INTO grievance_timeline (grievance_id, action, details, performed_by)
        VALUES (%s, 'VERIFICATION_AGGREGATED', %s, 'VERIFICATION_AGENT')
    """, [grievance_id, json.dumps({
        "total_responses": total,
        "resolved_count": resolved_count,
        "resolution_ratio": resolution_ratio,
        "result": status
    })])
```

---


## 7. API Endpoints

### 7.1 Grievance Endpoints

```
POST   /api/v1/grievances/file-image        # File grievance via image upload
POST   /api/v1/grievances/file-voice         # File grievance via browser voice recording (audio upload)
GET    /api/v1/grievances                     # List grievances (with filters)
GET    /api/v1/grievances/:id                 # Get single grievance details
GET    /api/v1/grievances/:id/timeline        # Get grievance audit trail
PATCH  /api/v1/grievances/:id/status          # Update grievance status (authority only)
```

### 7.2 Dashboard Endpoints

```
GET    /api/v1/dashboard/stats                # Overview stats (total, resolved, pending)
GET    /api/v1/dashboard/heatmap              # Grievance locations for heatmap (GeoJSON)
GET    /api/v1/dashboard/severity-distribution # Severity breakdown chart data
GET    /api/v1/dashboard/category-breakdown    # Category-wise grievance counts
GET    /api/v1/dashboard/authority-scorecard   # Department performance metrics
GET    /api/v1/dashboard/live-feed             # Recent grievances feed
GET    /api/v1/dashboard/trends                # Weekly/monthly trend data
```

### 7.3 Verification Endpoints

```
GET    /api/v1/verify/nearby                   # Get issues near user's location
POST   /api/v1/verify/:grievance_id            # Submit verification response
```

### 7.4 Auth & User Endpoints

```
POST   /api/v1/auth/register                   # Register citizen/authority
POST   /api/v1/auth/login                       # Login
PUT    /api/v1/users/location                   # Update user location
```

### 7.5 Admin Endpoints

```
GET    /api/v1/admin/assigned                   # Authority's assigned grievances
GET    /api/v1/admin/escalations                # View escalation alerts
POST   /api/v1/admin/grievances/:id/respond     # Authority responds to grievance
GET    /api/v1/admin/performance                # Department performance metrics
```

### Detailed Endpoint Specs

#### `POST /api/v1/grievances/file-image`

```python
# Request (multipart/form-data):
# - images: File[]       (required, max 5 images)
# - description: str     (optional)
# - latitude: float      (optional, from browser geolocation)
# - longitude: float     (optional, from browser geolocation)

# Response: 201 Created
{
    "tracking_id": "NGS-2026-00001",
    "grievance_id": "uuid-here",
    "status": "PROCESSING",
    "message": "Your grievance has been filed and is being analyzed."
}

# After agent pipeline completes (via WebSocket):
{
    "event": "grievance_processed",
    "data": {
        "tracking_id": "NGS-2026-00001",
        "title": "Large pothole on MG Road near City Hospital",
        "category": "ROAD_DAMAGE",
        "severity_score": 7.5,
        "severity_label": "HIGH",
        "severity_explanation": "Severe road damage detected...",
        "assigned_to": "Public Works Department, Ward 12",
        "sla_deadline": "2026-11-03T10:22:00Z"
    }
}
```

#### `POST /api/v1/grievances/file-voice`

```python
# Citizen speaks in native language via browser mic (MediaRecorder API)
# Request (multipart/form-data):
# - audio: File          (required, wav/webm/mp3, max 25MB)
# - latitude: float      (optional, from browser geolocation)
# - longitude: float     (optional, from browser geolocation)
# - language_hint: str   (optional, e.g. "auto", "hi", "te", "ta")

# Response: 201 Created
{
    "tracking_id": "NGS-2026-00002",
    "grievance_id": "uuid-here",
    "status": "PROCESSING",
    "message": "Audio received. Transcribing with Sarvam AI and running triage pipeline..."
}

# Backend flow:
# 1. Save audio to temporary scratch / Cloudinary
# 2. Sarvam ASR converts audio to native transcript (auto language detection)
# 3. Sarvam translates to English
# 4. Intake Agent extracts structured fields & geocodes landmark via Nominatim
# 5. Duplicate Detection -> Triage Agent -> Routing Agent
# 6. Returns complete status & emits live update via WebSocket
```

#### `GET /api/v1/dashboard/heatmap`

```python
# Request: GET /api/v1/dashboard/heatmap?bounds=17.3,78.4,17.5,78.6&severity_min=5

# Response: 200 OK (GeoJSON)
{
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": { "type": "Point", "coordinates": [78.4867, 17.385] },
            "properties": {
                "grievance_id": "uuid",
                "tracking_id": "NGS-2026-00001",
                "title": "Large pothole",
                "category": "ROAD_DAMAGE",
                "severity_score": 7.5,
                "severity_label": "HIGH",
                "status": "ASSIGNED",
                "report_count": 5,
                "created_at": "2026-10-31T10:00:00Z"
            }
        }
    ]
}
```

---

## 8. Frontend Dashboard

### 8.1 Page Layout — Public Dashboard (`/dashboard`)

```
┌──────────────────────────────────────────────────────────────────┐
│  🏛️ NagarSeva — Public Civic Grievance Dashboard                │
│  ─────────────────────────────────────────────────────────────── │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ 📊 Total │ │ ✅ Resolved│ │ ⏳ Pending│ │ 🔴 SLA    │           │
│  │  1,247   │ │    834    │ │   389     │ │ Breached  │           │
│  │          │ │  (67%)   │ │           │ │    24     │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                  │
│  ┌─────────────────────────────────┐ ┌────────────────────────┐ │
│  │        GRIEVANCE HEATMAP        │ │  SEVERITY DISTRIBUTION │ │
│  │   [Leaflet Map with clusters    │ │  ████ Critical: 45     │ │
│  │    colored by severity]         │ │  ████████ High: 124    │ │
│  │   🔴 Critical  🟠 High         │ │  ████████████ Med: 198 │ │
│  │   🟡 Medium    🟢 Low          │ │  ████ Low: 22          │ │
│  └─────────────────────────────────┘ └────────────────────────┘ │
│                                                                  │
│  ┌─────────────────────────────────┐ ┌────────────────────────┐ │
│  │    CATEGORY BREAKDOWN (Donut)   │ │ AUTHORITY SCORECARD    │ │
│  │  🛣️ Road: 34%                   │ │ PWD         67% ██████ │ │
│  │  💧 Water: 18%                  │ │ Water Board 81% ████████│ │
│  │  🗑️ Garbage: 15%               │ │ Sanitation  54% █████  │ │
│  │  ⚡ Electricity: 12%            │ │ Electricity 72% ███████│ │
│  └─────────────────────────────────┘ └────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  LIVE GRIEVANCE FEED                                        ││
│  │  🔴 2m ago  | NGS-2026-01247 | Bridge crack on NH-44       ││
│  │             | Severity: 8.5 CRITICAL | → PWD                ││
│  │  🟠 15m ago | NGS-2026-01246 | Water leak near MG Road     ││
│  │             | Severity: 6.2 HIGH | → Water Board            ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### 8.2 Page Layout — Report Grievance (`/report`)

```
┌──────────────────────────────────────────────────────────────────┐
│  📷 Report a Civic Issue                                         │
│                                                                  │
│  ┌────────────────────────────────────────────┐                 │
│  │  Upload Photos (drag & drop, max 5)        │                 │
│  │  ┌──────┐ ┌──────┐ ┌──────┐               │                 │
│  │  │ 📷+  │ │ img1 │ │ img2 │               │                 │
│  │  └──────┘ └──────┘ └──────┘               │                 │
│  └────────────────────────────────────────────┘                 │
│                                                                  │
│  ┌────────────────────────────────────────────┐                 │
│  │  🎤 Or Record Voice Description             │                 │
│  │  [  🔴 Start Recording  ]                  │                 │
│  │  Speak in any language                      │                 │
│  └────────────────────────────────────────────┘                 │
│                                                                  │
│  Description (optional): [________________________]              │
│                                                                  │
│  📍 Location:                                                    │
│  [📍 Use My Location] or [📌 Pick on Map]                       │
│  ┌────────────────────────────────────────────┐                 │
│  │  [Interactive Leaflet Map]                  │                 │
│  └────────────────────────────────────────────┘                 │
│                                                                  │
│  [        🚀 Submit Grievance        ]                           │
│                                                                  │
│  📞 Can't use the website? Call: 1800-XXX-XXXX                   │
└──────────────────────────────────────────────────────────────────┘
```

### 8.3 Page Layout — Grievance Detail (`/grievance/:id`)

```
┌──────────────────────────────────────────────────────────────────┐
│  Grievance #NGS-2026-01247                                       │
│  Title: Bridge crack on NH-44 near District Hospital             │
│  Status: 🟠 ASSIGNED         Severity: 🔴 8.5 CRITICAL          │
│  Filed: Oct 31, 2026         SLA: Nov 1, 2026 10:15 AM          │
│                                                                  │
│  ┌───────────────────┐  ┌────────────────────────────────────┐  │
│  │  [Photo of crack] │  │  AI SEVERITY ANALYSIS              │  │
│  │                   │  │  Score: 8.5/10 (CRITICAL)          │  │
│  │                   │  │  📊 Signal Breakdown:              │  │
│  │                   │  │  Visual Damage:    8.2 ████████░░  │  │
│  │                   │  │  Text Urgency:     7.5 ███████░░░  │  │
│  │                   │  │  Category Risk:    9.0 █████████░  │  │
│  │                   │  │  Geo Context:      8.5 ████████░░  │  │
│  │                   │  │  Population:       6.0 ██████░░░░  │  │
│  │                   │  │  Weather:          7.0 ███████░░░  │  │
│  └───────────────────┘  └────────────────────────────────────┘  │
│                                                                  │
│  TIMELINE                                                        │
│  ● Oct 31, 10:15 AM — Filed via voice call                      │
│  ● Oct 31, 10:15 AM — AI triage: CRITICAL (8.5/10)             │
│  ● Oct 31, 10:16 AM — Routed to PWD, Ward 12                   │
│  ● Oct 31, 04:00 PM — 2 similar reports merged (count: 3)      │
│  ○ Nov 1, 10:15 AM — SLA Deadline                               │
└──────────────────────────────────────────────────────────────────┘
```

### 8.4 Key Frontend Components

#### GrievanceHeatmap.tsx

```tsx
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';

const severityColors: Record<string, string> = {
  CRITICAL: '#EF4444',
  HIGH: '#F97316',
  MEDIUM: '#EAB308',
  LOW: '#22C55E',
};

interface Grievance {
  id: string;
  tracking_id: string;
  title: string;
  lat: number;
  lng: number;
  severity_score: number;
  severity_label: string;
  category: string;
  status: string;
}

export function GrievanceHeatmap({ grievances }: { grievances: Grievance[] }) {
  return (
    <MapContainer center={[20.5937, 78.9629]} zoom={5} className="h-[500px] w-full rounded-xl">
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <MarkerClusterGroup chunkedLoading>
        {grievances.map((g) => (
          <CircleMarker
            key={g.id}
            center={[g.lat, g.lng]}
            radius={8 + g.severity_score * 0.5}
            fillColor={severityColors[g.severity_label]}
            fillOpacity={0.8}
            stroke={true}
            weight={2}
            color="#fff"
          >
            <Popup>
              <div className="text-sm">
                <p className="font-bold">{g.tracking_id}</p>
                <p>{g.title}</p>
                <p>Severity: {g.severity_score}/10 ({g.severity_label})</p>
                <p>Status: {g.status}</p>
                <a href={`/grievance/${g.id}`} className="text-blue-500 underline">
                  View Details →
                </a>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MarkerClusterGroup>
    </MapContainer>
  );
}
```

#### ImageUploader.tsx

```tsx
import { useDropzone } from 'react-dropzone';
import { useState } from 'react';

export function ImageUploader({ onFilesSelected }: { onFilesSelected: (files: File[]) => void }) {
  const [previews, setPreviews] = useState<string[]>([]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'image/*': ['.jpg', '.jpeg', '.png', '.webp'] },
    maxFiles: 5,
    maxSize: 10 * 1024 * 1024, // 10MB
    onDrop: (files) => {
      onFilesSelected(files);
      setPreviews(files.map((f) => URL.createObjectURL(f)));
    },
  });

  return (
    <div>
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors
          ${isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}`}
      >
        <input {...getInputProps()} />
        <p className="text-gray-600">
          {isDragActive ? 'Drop images here...' : 'Drag & drop photos, or click to select (max 5)'}
        </p>
      </div>
      {previews.length > 0 && (
        <div className="flex gap-3 mt-4">
          {previews.map((src, i) => (
            <img key={i} src={src} alt={`Preview ${i}`} className="w-24 h-24 object-cover rounded-lg" />
          ))}
        </div>
      )}
    </div>
  );
}
```

#### Real-Time WebSocket Setup

```tsx
// frontend/lib/socket.ts
import { io, Socket } from 'socket.io-client';

let socket: Socket | null = null;

export function getSocket(): Socket {
  if (!socket) {
    socket = io(process.env.NEXT_PUBLIC_WS_URL!, {
      transports: ['websocket'],
      autoConnect: true,
    });
  }
  return socket;
}

// Usage in dashboard:
// const socket = getSocket();
// socket.on('new_grievance', (data) => { /* update live feed */ });
// socket.on('grievance_updated', (data) => { /* update specific card */ });
// socket.on('grievance_escalated', (data) => { /* show alert */ });
```

---

## 9. Real-Time Data Sources & APIs

> ⚠️ **CRITICAL**: The hackathon has a zero-tolerance policy for dummy/mock data. Every data point must come from a real API.

### 9.1 Required API Keys (100% Free Tiers — No Credit Card Needed)

| API | Purpose | Free Tier | Signup URL |
|-----|---------|-----------|------------|
| **Google Gemini** | Vision + LLM reasoning | 60 RPM, 1500 req/day | https://aistudio.google.com |
| **Sarvam AI** | Multilingual Voice ASR + Translation | Free trial/developer tier | https://www.sarvam.ai |
| **OpenWeatherMap** | Current weather + rainfall | 60 calls/min, 1M calls/mo | https://openweathermap.org/api |
| **Cloudinary** | Image & voice file hosting | 25GB storage, 25K ops/mo | https://cloudinary.com |

### 9.2 Open Data & Geospatial Services (Completely Free — No API Key Required)

| Source | Capability | Implementation / URL |
|--------|------------|----------------------|
| **Nominatim (OpenStreetMap)** | Free address ↔ coordinates geocoding | `https://nominatim.openstreetmap.org/search` |
| **Overpass API (OSM)** | Query nearby critical infrastructure (hospitals, schools) | `https://overpass-api.de/api/interpreter` |
| **Data.gov.in** | Official government infrastructure & ward data | https://data.gov.in |
| **Census India** | District-wise population density for impact scoring | https://censusindia.gov.in |
| **ISRO Bhuvan** | Geospatial visual data & map tile layers | https://bhuvan.nrsc.gov.in |

### 9.3 Service Integration Code

#### Sarvam AI — Speech-to-Text + Translation

```python
# backend/services/sarvam_service.py
import httpx

class SarvamService:
    BASE_URL = "https://api.sarvam.ai"

    def __init__(self, api_key: str):
        self.client = httpx.AsyncClient(
            headers={"API-Subscription-Key": api_key}
        )

    async def speech_to_text(self, audio_file_path: str, language_code: str = "auto"):
        """Transcribe audio using Sarvam Saaras v2. Supports: hi, bn, kn, ml, mr, od, pa, ta, te, gu, en."""
        with open(audio_file_path, "rb") as f:
            response = await self.client.post(
                f"{self.BASE_URL}/speech-to-text",
                files={"file": ("audio.wav", f, "audio/wav")},
                data={"model": "saaras:v2", "language_code": language_code}
            )
        response.raise_for_status()
        result = response.json()
        return {"transcript": result["transcript"], "language": result.get("language_code", language_code)}

    async def translate(self, text: str, source_lang: str, target_lang: str = "en"):
        """Translate between Indian languages using Sarvam Mayura."""
        response = await self.client.post(
            f"{self.BASE_URL}/translate",
            json={
                "input": text,
                "source_language_code": source_lang,
                "target_language_code": target_lang,
                "model": "mayura:v1",
                "enable_preprocessing": True
            }
        )
        response.raise_for_status()
        return {"translated_text": response.json()["translated_text"]}

    async def text_to_speech(self, text: str, language: str = "hi"):
        """Generate speech for call-back confirmations."""
        response = await self.client.post(
            f"{self.BASE_URL}/text-to-speech",
            json={"inputs": [text], "target_language_code": language, "model": "bulbul:v1", "speaker": "meera"}
        )
        response.raise_for_status()
        return response.json()["audios"][0]
```

#### Gemini Vision — Image Analysis

```python
# backend/services/gemini_service.py
import google.generativeai as genai
import json, PIL.Image

class GeminiService:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    async def analyze_image(self, image_paths: list[str], prompt: str) -> dict:
        """Analyze civic infrastructure images for damage assessment."""
        images = [PIL.Image.open(p) for p in image_paths]
        response = await self.model.generate_content_async(
            [prompt] + images,
            generation_config=genai.GenerationConfig(response_mime_type="application/json", temperature=0.1)
        )
        return json.loads(response.text)

    async def generate_structured(self, prompt: str) -> dict:
        """Generate structured JSON output."""
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(response_mime_type="application/json", temperature=0.2)
        )
        return json.loads(response.text)

    async def generate_text(self, prompt: str) -> str:
        """Generate free-form text (explanations, reports)."""
        response = await self.model.generate_content_async(prompt)
        return response.text
```

#### OpenWeatherMap

```python
# backend/agents/tools/weather.py
import httpx
from config.settings import settings

async def get_current_weather(lat: float, lon: float) -> dict:
    """Fetch current weather for severity amplification."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": settings.OPENWEATHERMAP_API_KEY, "units": "metric"}
        )
        data = resp.json()
    return {
        "temp_celsius": data["main"]["temp"],
        "humidity": data["main"]["humidity"],
        "wind_speed_kmh": data["wind"]["speed"] * 3.6,
        "rain_mm": data.get("rain", {}).get("1h", 0),
        "weather_main": data["weather"][0]["main"],
        "weather_description": data["weather"][0]["description"],
    }
```

#### Browser Voice Recording & Audio Handler (100% Free)

```python
# backend/services/voice_service.py
import aiofiles
from pathlib import Path

class VoiceService:
    """
    Handles audio uploaded directly from citizen's browser or mobile device.
    Uses browser MediaRecorder API (captures audio/webm or audio/wav).
    Zero telephony charges or carrier contracts required.
    """
    UPLOAD_DIR = Path("scratch/audio_uploads")

    def __init__(self):
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async def save_audio_stream(self, file_bytes: bytes, filename: str) -> str:
        """Save received citizen voice recording locally before passing to Sarvam ASR."""
        file_path = self.UPLOAD_DIR / filename
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_bytes)
        return str(file_path)
```

#### Nominatim Geocoding (OpenStreetMap — Free, No Key Required)

```python
# backend/agents/tools/geocoding.py
import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

async def geocode(address: str) -> dict | None:
    """
    Convert landmark/address to coordinates using OpenStreetMap Nominatim.
    Completely free, no credit card or API key required.
    """
    headers = {"User-Agent": "NagarSeva-CivicTriage/1.0 (contact: team@nagarseva.org)"}
    params = {
        "q": address,
        "format": "json",
        "addressdetails": 1,
        "limit": 1,
        "countrycodes": "in"  # Restrict to India
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(NOMINATIM_URL, params=params, headers=headers, timeout=10.0)
        data = resp.json()

    if data and len(data) > 0:
        result = data[0]
        addr = result.get("address", {})
        return {
            "lat": float(result["lat"]),
            "lng": float(result["lon"]),
            "formatted_address": result.get("display_name", address),
            "district": addr.get("state_district") or addr.get("county") or addr.get("city"),
            "state": addr.get("state"),
            "pincode": addr.get("postcode"),
            "ward": addr.get("suburb") or addr.get("neighbourhood")
        }
    return None
```

#### Overpass API — Nearby Critical POIs (Free, No Key Required)

```python
# backend/agents/tools/overpass.py
import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

async def check_nearby_critical_places(lat: float, lng: float, radius: int = 500) -> dict:
    """
    Query OpenStreetMap Overpass API for nearby critical infrastructure:
    hospitals, schools, colleges, railway stations, bus terminals.
    Free, no API key needed.
    """
    # Overpass QL query searching for critical civic nodes within radius
    query = f"""
    [out:json][timeout:10];
    (
      node["amenity"="hospital"](around:{radius},{lat},{lng});
      node["amenity"="school"](around:{radius},{lat},{lng});
      node["amenity"="bus_station"](around:{radius},{lat},{lng});
      node["railway"="station"](around:{radius},{lat},{lng});
    );
    out center;
    """
    results = {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(OVERPASS_URL, data={"data": query}, timeout=12.0)
            data = resp.json()

        for element in data.get("elements", []):
            tags = element.get("tags", {})
            place_type = tags.get("amenity") or tags.get("railway") or "infrastructure"
            # Calculate approx distance (meters)
            e_lat, e_lon = element["lat"], element["lon"]
            dist = int(((lat - e_lat)**2 + (lng - e_lon)**2)**0.5 * 111000)
            if place_type not in results or dist < results[place_type]:
                results[place_type] = dist
    except Exception:
        # Fallback to standard proximity if Overpass times out
        results = {"critical_area": 300}
    return results
```

---

## 10. Setup & Installation

### 10.1 Prerequisites

- **Python 3.11+** with pip
- **Node.js 18+** with pnpm (or npm)
- **PostgreSQL 16** with PostGIS extension (or free Supabase PostgreSQL)
- **Redis** (optional, for caching/rate limiting)
- **Free API keys**: Google Gemini (AI Studio), Sarvam AI, OpenWeatherMap, Cloudinary (all 100% free signup, zero credit card)

### 10.2 Environment Variables

```bash
# backend/.env

# Database (Local Postgres or free Supabase)
DATABASE_URL=postgresql://user:password@localhost:5432/nagarseva
REDIS_URL=redis://localhost:6379/0

# AI Services (Free tiers)
SARVAM_API_KEY=your_sarvam_api_key
GEMINI_API_KEY=your_gemini_api_key

# External APIs (Free tier)
OPENWEATHERMAP_API_KEY=your_openweather_key

# Storage (Free tier)
CLOUDINARY_URL=cloudinary://key:secret@cloud_name

# App
SECRET_KEY=your-secret-key-here
FRONTEND_URL=http://localhost:3000
```

```bash
# frontend/.env.local

NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NEXTAUTH_SECRET=your-nextauth-secret
NEXTAUTH_URL=http://localhost:3000
```

### 10.3 Backend Setup

```bash
# 1. Clone and enter project
git clone https://github.com/your-team/nagarseva.git
cd nagarseva/backend

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate          # Linux/Mac
# venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up PostgreSQL with PostGIS
sudo -u postgres psql
# CREATE DATABASE nagarseva;
# \c nagarseva
# CREATE EXTENSION postgis;
# CREATE EXTENSION pg_trgm;
# CREATE EXTENSION vector;
# \q

# 5. Run migrations
alembic upgrade head

# 6. Seed department data
python scripts/seed_departments.py

# 7. Start server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 10.4 Frontend Setup

```bash
cd ../frontend
pnpm install
pnpm dev    # Runs on http://localhost:3000
```

### 10.5 `backend/requirements.txt`

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9
sqlalchemy==2.0.35
asyncpg==0.29.0
alembic==1.13.0
geoalchemy2==0.15.0
pgvector==0.3.0
google-generativeai==0.8.0
langgraph==0.2.30
langchain-core==0.3.10
langchain-google-genai==2.0.0
httpx==0.27.0
pydantic==2.9.0
pydantic-settings==2.5.0
numpy==1.26.0
Pillow==10.4.0
apscheduler==3.10.4
python-socketio==5.11.0
cloudinary==1.41.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-dotenv==1.0.1
loguru==0.7.2
```

### 10.6 `frontend/package.json` (key dependencies)

```json
{
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-leaflet": "^4.2.0",
    "leaflet": "^1.9.4",
    "react-leaflet-cluster": "^2.1.0",
    "recharts": "^2.12.0",
    "socket.io-client": "^4.7.0",
    "next-auth": "^4.24.0",
    "axios": "^1.7.0",
    "tailwindcss": "^3.4.0",
    "@headlessui/react": "^2.1.0",
    "@heroicons/react": "^2.1.0",
    "react-dropzone": "^14.2.0",
    "react-hot-toast": "^2.4.0",
    "date-fns": "^3.6.0",
    "framer-motion": "^11.0.0"
  }
}
```

---

## 11. Deployment

### 11.1 Backend — Railway or Render

```yaml
# railway.toml
services:
  - type: web
    name: nagarseva-api
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT

  - type: worker
    name: nagarseva-scheduler
    runtime: python
    startCommand: python schedulers/run_schedulers.py
```

### 11.2 Frontend — Vercel

```bash
cd frontend
vercel --prod
# Or connect GitHub repo for auto-deploy
```

### 11.3 Database — Supabase (Free PostgreSQL + PostGIS)

1. Create project at https://supabase.com
2. Run the SQL schema from Section 5
3. Copy the connection string into `DATABASE_URL`

---

## 12. Demo Script

### Recommended Flow (5 minutes)

| Time | Segment | What to Show |
|------|---------|-------------|
| 0:00 | **Intro** (30s) | Public dashboard with existing grievances on heatmap, real-time stats |
| 0:30 | **Voice Demo** (90s) | Speak into the browser microphone LIVE in Hindi (or Tamil/Telugu). Show backend processing: Sarvam transcription → translation → Intake Agent → Triage Agent severity breakdown → Routing. Show live toast confirmation and new pin on dashboard. |
| 2:00 | **Image Demo** (60s) | Upload a real photo. Show Gemini Vision analyzing damage. Show severity scoring with all 8 signals. Show it on heatmap. |
| 3:00 | **Duplicate Detection** (30s) | File another report for same location. Show it detected as duplicate, report_count incrementing, severity bumping up. |
| 3:30 | **Dashboard Deep Dive** (60s) | Click grievance → detail page with timeline + severity signal breakdown. Show authority scorecard + category chart. |
| 4:30 | **Escalation** (30s) | Show a pre-existing overdue grievance. Trigger escalation. Show status change + notification. |
| 5:00 | **Close** | Everything live, no dummy data, real APIs |

### Edge Cases to Prepare For

| Scenario | Handling Strategy |
|----------|------------------|
| Unclear voice recording | Low-confidence flag → manual review queue + ask via SMS for clarification |
| No location in voice report | Use caller's phone area code as approximate location; request via SMS |
| Image with no visible issue | Low confidence → prompt user to add text description |
| Same citizen re-reports same issue | Duplicate agent merges automatically |
| External API timeout | Retry with exponential backoff (3 attempts) → graceful degradation message |
| Unsupported language | Sarvam covers 10+ Indian languages; others → flagged for manual review |
| Authority doesn't respond | Escalation agent auto-escalates after SLA breach |
| No nearby users for verification | Fallback: SMS to original reporter |

---

## Quick Reference: Build Priority Order

| Priority | Component | Time | Dependency |
|----------|-----------|------|------------|
| 🔴 P0 | DB schema + FastAPI boilerplate | 2h | None |
| 🔴 P0 | Gemini Vision image analysis endpoint | 2h | FastAPI |
| 🔴 P0 | Intake Agent (image flow) | 2h | Gemini service |
| 🔴 P0 | Triage Agent (severity scoring) | 3h | Intake Agent |
| 🔴 P0 | Frontend: Report page + Dashboard | 4h | API endpoints |
| 🟠 P1 | Sarvam voice integration | 2h | Sarvam API key |
| 🟠 P1 | Duplicate Detection Agent | 2h | PostGIS, embeddings |
| 🟠 P1 | Routing Agent | 1.5h | Departments data |
| 🟠 P1 | Grievance detail page + timeline | 2h | API endpoints |
| 🟡 P2 | Browser voice recording UI & pipeline | 2h | MediaRecorder API |
| 🟡 P2 | Escalation Agent (scheduled) | 1.5h | SLA data |
| 🟡 P2 | Verification Agent | 2h | User locations |
| 🟡 P2 | Authority admin panel | 2h | Auth |
| 🟢 P3 | WebSocket real-time updates | 1.5h | Socket.IO |
| 🟢 P3 | Weather amplification signal | 1h | OpenWeatherMap |
| 🟢 P3 | Population density signal | 1h | Census data |

> **Minimum Viable Demo (P0):** ~13h → Image upload → AI triage → dashboard
> **Full Demo (P0+P1):** ~20h → adds voice, deduplication, routing
> **Impressive Demo (all):** ~30h → voice recording, escalation, verification

---

*Built with ❤️ by Team [Your Team Name] — [Hackathon Name] 2026*