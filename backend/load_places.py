import os
import pandas as pd
import psycopg
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL in backend/.env")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY in backend/.env")

client = OpenAI(api_key=OPENAI_API_KEY)

# CSV is in project root (one level up from backend)
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "stpete_places.csv")

def embed(text: str):
    resp = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return resp.data[0].embedding

def make_embedding_text(row: dict) -> str:
    # Build a single "meaning" string for embeddings
    parts = [
        f"name={row.get('name','')}",
        f"city={row.get('city','')}",
        f"neighborhood={row.get('neighborhood','')}",
        f"county={row.get('county','')}",
        f"category={row.get('category','')}",
        f"sub_category={row.get('sub_category','')}",
        f"type={row.get('type','')}",
        f"price={row.get('price','')}",
        f"vibe_tags={row.get('vibe_tags','')}",
        f"best_for={row.get('best_for','')}",
        f"notes={row.get('notes','')}",
        f"varun_score={row.get('varun_score','')}",
        f"varun_tags={row.get('varun_tags','')}",
    ]
    return " | ".join([p for p in parts if p.split("=", 1)[1].strip()])

def main():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"CSV not found at: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH).fillna("")
    if "name" not in df.columns:
        raise ValueError("CSV must include column: name")

    # Insert rows
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for _, r in df.iterrows():
                row = r.to_dict()
                text = make_embedding_text(row)
                emb = embed(text)

                cur.execute(
                    """
                    INSERT INTO places
                    (name, city, neighborhood, county, category, sub_category, type, price,
                     vibe_tags, best_for, notes, varun_score, varun_tags, embedding)
                    VALUES
                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    """,
                    (
                        row.get("name",""),
                        row.get("city",""),
                        row.get("neighborhood",""),
                        row.get("county",""),
                        row.get("category",""),
                        row.get("sub_category",""),
                        row.get("type",""),
                        row.get("price",""),
                        row.get("vibe_tags",""),
                        row.get("best_for",""),
                        row.get("notes",""),
                        int(row["varun_score"]) if str(row.get("varun_score","")).strip() != "" else None,
                        row.get("varun_tags",""),
                        emb,
                    )
                )
            conn.commit()

    print(f"Loaded {len(df)} places + embeddings into Supabase.")

if __name__ == "__main__":
    main()
