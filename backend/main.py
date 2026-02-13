import os
from typing import List, Optional, Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import psycopg
from openai import OpenAI

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL. Fill it in inside backend/.env")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY. Fill it in inside backend/.env")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="St Pete Tour Guide API")
from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
      <head><title>St Pete Tour Guide</title></head>
      <body style="font-family: Arial; padding: 40px;">
        <h1>St Pete Tour Guide API</h1>
        <p>This is the backend. Use the app UI to chat.</p>
        <ul>
          <li><a href="/docs">API Docs</a></li>
          <li><a href="/health">Health Check</a></li>
        </ul>
      </body>
    </html>
    """


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    category: Optional[str] = None
    neighborhood: Optional[str] = None
    vibe: Optional[str] = None
    budget: Optional[str] = None  # $, $$, $$$, $$$$
    city: Optional[str] = None

class Place(BaseModel):
    id: int
    name: str
    city: Optional[str] = None
    neighborhood: Optional[str] = None
    county: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    type: Optional[str] = None
    price: Optional[str] = None
    vibe_tags: Optional[str] = None
    best_for: Optional[str] = None
    notes: Optional[str] = None
    varun_score: Optional[int] = None
    varun_tags: Optional[str] = None
    score: float

class ChatResponse(BaseModel):
    reply: str
    places: List[Place]

def embed_text(text: str) -> List[float]:
    # DB uses vector(1536) — keep it aligned with text-embedding-3-small
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding

def build_filter_sql(req: ChatRequest) -> (str, List[Any]):
    clauses = []
    params: List[Any] = []

    if req.category:
        clauses.append("category ILIKE %s")
        params.append(f"%{req.category}%")

    if req.neighborhood:
        clauses.append("neighborhood ILIKE %s")
        params.append(f"%{req.neighborhood}%")

    if req.budget:
        clauses.append("price = %s")
        params.append(req.budget)

    if req.vibe:
        clauses.append("vibe_tags ILIKE %s")
        params.append(f"%{req.vibe}%")

    if req.city:
        clauses.append("city ILIKE %s")
        params.append(f"%{req.city}%")

    if clauses:
        return "WHERE " + " AND ".join(clauses), params
    return "", params

def search_places(query_embedding: List[float], req: ChatRequest, k: int = 15) -> List[Dict[str, Any]]:
    where_sql, params = build_filter_sql(req)

    # <=> is cosine distance in pgvector; smaller = closer
    sql = f"""
      SELECT
        id, name, city, neighborhood, county, category, sub_category, type, price,
        vibe_tags, best_for, notes, varun_score, varun_tags,
        (embedding <=> %s::vector) AS distance
      FROM places
      {where_sql}
      ORDER BY embedding <=> %s::vector
      LIMIT {k};
    """

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [query_embedding, *params, query_embedding])
            rows = cur.fetchall()

    out = []
    for r in rows:
        (
            pid, name, city, neighborhood, county, category, sub_category, type_, price,
            vibe_tags, best_for, notes, varun_score, varun_tags, distance
        ) = r
        out.append({
            "id": pid,
            "name": name,
            "city": city,
            "neighborhood": neighborhood,
            "county": county,
            "category": category,
            "sub_category": sub_category,
            "type": type_,
            "price": price,
            "vibe_tags": vibe_tags,
            "best_for": best_for,
            "notes": notes,
            "varun_score": varun_score,
            "varun_tags": varun_tags,
            "distance": float(distance),
        })
    return out

def format_places_for_prompt(places: List[Dict[str, Any]]) -> str:
    lines = []
    for p in places:
        lines.append(
            f"- {p['name']} | city={p.get('city')} | neighborhood={p.get('neighborhood')} | "
            f"category={p.get('category')} | sub_category={p.get('sub_category')} | type={p.get('type')} | "
            f"price={p.get('price')} | vibe_tags={p.get('vibe_tags')} | best_for={p.get('best_for')} | "
            f"varun_score={p.get('varun_score')} | notes={p.get('notes')}"
        )
    return "\n".join(lines)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    q = req.message.strip()
    qemb = embed_text(q)

    candidates = search_places(qemb, req, k=18)
    context = format_places_for_prompt(candidates)

    system = (
        "You are a Tampa Bay / St. Pete tour guide. "
        "Only recommend places from the provided dataset context. "
        "Always give 3 top picks + 2 backups. "
        "For each pick: why it fits, best time if known, and one practical tip "
        "(parking/noise/reservations/location). "
        "If the user asks for a plan, build a mini itinerary (2–4 stops) with times. "
        "If info isn't in the dataset, say 'not in my notes' rather than inventing."
    )

    user = (
        f"User request: {req.message}\n"
        f"Filters: city={req.city}, category={req.category}, neighborhood={req.neighborhood}, vibe={req.vibe}, budget={req.budget}\n\n"
        f"Dataset context:\n{context}\n\n"
        "Now answer."
    )

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
    )
    reply = completion.choices[0].message.content or ""

    places_out: List[Place] = []
    for p in candidates[:10]:
        # similarity-ish score
        base = max(0.0, 1.0 - p["distance"])
        # optional Varun boost
        boost = 0.0
        if p.get("varun_score") is not None:
            boost = min(0.25, (p["varun_score"] / 10.0) * 0.25)
        score = base + boost

        places_out.append(
            Place(
                id=p["id"],
                name=p["name"],
                city=p.get("city"),
                neighborhood=p.get("neighborhood"),
                county=p.get("county"),
                category=p.get("category"),
                sub_category=p.get("sub_category"),
                type=p.get("type"),
                price=p.get("price"),
                vibe_tags=p.get("vibe_tags"),
                best_for=p.get("best_for"),
                notes=p.get("notes"),
                varun_score=p.get("varun_score"),
                varun_tags=p.get("varun_tags"),
                score=score
            )
        )

    return ChatResponse(reply=reply, places=places_out)
