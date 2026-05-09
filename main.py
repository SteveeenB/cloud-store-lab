"""
Minimal FastAPI teaching app for cloud evaluation.

This file is intentionally incomplete. Students must implement:
- Cloud SQL (PostgreSQL) integration
- Cloud Storage integration
- Firestore integration
"""

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
import psycopg2
from psycopg2 import Error as PsycopgError
from dotenv import load_dotenv
from google.cloud import storage, firestore

import os
import uuid

app = FastAPI(title="Cloud Computing Evaluation API (Starter)")
load_dotenv()
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
AUDIT_COLLECTION = os.getenv("FIRESTORE_COLLECTION_AUDIT_EVENTS") or "audit_events"
fs_client = firestore.Client()

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    price: float


class CommentCreate(BaseModel):
    author: str
    text: str


@app.get("/health")
def health():
    # TODO: Return service status and optionally dependency status.
    # Keep this endpoint simple for uptime checks.

    return {"status": "ok"}


@app.post("/products", status_code=201)
def create_product(payload: ProductCreate):
    # TODO: Validate and store product data in Cloud SQL (PostgreSQL).
    # Do not keep products in memory for the final solution.
    # Students should use psycopg2 and proper SQL schema design.
    try:
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO products (name, description, price) VALUES (%s, %s, %s) RETURNING id",
                (payload.name, payload.description, payload.price),
            )
            new_id = cursor.fetchone()[0]
            conn.commit()
        return {"id": new_id, "name": payload.name, "description": payload.description, "price": payload.price}
    except Exception as exc:
        print(f"ERROR: {exc}")  # verás esto en la terminal
        raise HTTPException(status_code=500, detail=str(exc))  # y en la respuesta


@app.get("/products")
def list_products(
    limit: int = Query(default=10, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = None
):
    # TODO: Read and return product records from Cloud SQL (PostgreSQL).
    # Consider pagination and filtering in the final implementation.
    try:
        with get_db_connection() as conn, conn.cursor() as cursor:

            if search:
                cursor.execute(
                    """
                    SELECT id, name, description, price, image_url
                    FROM products
                    WHERE name ILIKE %s
                    LIMIT %s OFFSET %s
                    """,
                    (f"%{search}%", limit, offset)
                )
            else:
                cursor.execute(
                    """
                    SELECT id, name, description, price, image_url
                    FROM products
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset)
                )

            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "price": float(row[3]),
                    "image_url": row[4],
                }
                for row in rows
            ]

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc)
        )
    pass


@app.post("/products/{product_id}/image")
def upload_product_image(product_id: int, image: UploadFile = File(...)):
    try:
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Product not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    ext = os.path.splitext(image.filename)[1].lower() if image.filename else ""
    object_name = f"products/{product_id}/{uuid.uuid4().hex}{ext}"

    try:
        client = storage.Client()
        blob = client.bucket(BUCKET_NAME).blob(object_name)
        blob.upload_from_file(image.file, content_type=image.content_type)
        image_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{object_name}"
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {exc}")

    try:
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "UPDATE products SET image_url = %s WHERE id = %s",
                (image_url, product_id),
            )
            conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB update failed: {exc}")

    return {"product_id": product_id, "image_url": image_url}


@app.post("/products/{product_id}/comments", status_code=201)
def add_product_comment(product_id: int, payload: CommentCreate):
    
    try:
        with get_db_connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Product not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        doc_ref = fs_client.collection(AUDIT_COLLECTION).document()
        doc_ref.set({
            "product_id": product_id,
            "author": payload.author,
            "text": payload.text,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        return {"id": doc_ref.id, "product_id": product_id, "author": payload.author, "text": payload.text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Firestore write failed: {exc}")


@app.get("/audit/events")
def get_audit_events(limit: int = Query(default=20, le=100)):
    try:
        docs = (
            fs_client.collection(AUDIT_COLLECTION)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Firestore read failed: {exc}")
