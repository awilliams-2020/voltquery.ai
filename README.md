# NREL RAG SaaS - EV Infrastructure

A monorepo RAG SaaS application for finding EV charging stations using the NREL API.

## Project Structure

```
nrel-rag-saas/
├── frontend/          # Next.js 15 application
├── backend/           # FastAPI application
└── README.md
```

## Quick Start

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment:
```bash
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env and add your NREL_API_KEY and GEMINI_API_KEY
```

5. Get your NREL API key from https://developer.nrel.gov/signup/

6. Run the backend server:
```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at http://localhost:8000
API documentation: http://localhost:8000/docs

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env if you need to change the API URL (default: http://localhost:8000)
```

4. Run the development server:
```bash
npm run dev
```

The frontend will be available at http://localhost:3000

## Features

- **Backend**: FastAPI with NREL API integration
  - `/api/fetch-stations` endpoint that accepts zip codes
  - Modular service architecture for RAG logic
  - CORS configured for Next.js frontend

- **Frontend**: Next.js 15 with Shadcn UI
  - Modern dashboard with search functionality
  - Responsive design with Tailwind CSS
  - Real-time station search by zip code

## API Endpoints

### POST /api/fetch-stations

Fetches EV charging stations for a given zip code.

**Request Body:**
```json
{
  "zip_code": "80202"
}
```

**Response:**
```json
{
  "zip_code": "80202",
  "stations": [
    {
      "station_name": "Station Name",
      "street_address": "123 Main St",
      "city": "Denver",
      "state": "CO",
      "zip": "80202",
      "ev_network": "Network Name",
      "ev_connector_types": ["J1772", "CCS"],
      "ev_dc_fast_num": 2,
      "ev_level2_evse_num": 4
    }
  ]
}
```

## Tech Stack

- **Frontend**: Next.js 15 (App Router), TypeScript, Tailwind CSS, Shadcn UI
- **Backend**: Python 3.12, FastAPI, httpx
- **API**: NREL Alternative Fuels Data Center API
- **Future**: LlamaIndex RAG, Gemini 1.5 Pro, Supabase (pgvector)

## Development

Both frontend and backend should be running simultaneously for full functionality:
- Backend: http://localhost:8000
- Frontend: http://localhost:3000

## License

MIT

