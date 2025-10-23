from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio, random, math, time
from typing import Dict, List, Optional

app = FastAPI()
lock = asyncio.Lock()

class Product(BaseModel):
    id: str
    name: str
    price: float
    stock: int          # free stock units available (not reserved)
    reserved: int = 0   # units on hold (reserved but not yet committed)

# --- seed deterministic catalog of 600 products ---
random.seed(42)
PRODUCTS: Dict[str, Product] = {}
for i in range(1, 601):
    pid = f"p{i:04d}"
    price = round(random.uniform(5, 200), 2)
    # Skew distribution so some items are scarce (fun for demos)
    base = 5 if i % 17 == 0 else 50
    stock = base + int(45 * abs(math.sin(i / 13.0)))
    PRODUCTS[pid] = Product(id=pid, name=f"Product {pid}", price=price, stock=stock)

# --------- Models ---------
class ReserveReq(BaseModel):
    product_id: str
    qty: int

class CommitReq(BaseModel):
    product_id: str
    qty: int
    order_id: str

class ReleaseReq(BaseModel):
    product_id: str
    qty: int

# --------- Reads (for your “read function” demo) ---------
@app.get("/products")
async def list_products(offset: int = 0, limit: int = 50) -> List[Product]:
    ids = sorted(PRODUCTS.keys())
    slice_ids = ids[offset: offset + limit]
    return [PRODUCTS[i] for i in slice_ids]

@app.get("/products/{product_id}")
async def get_product(product_id: str) -> Product:
    p = PRODUCTS.get(product_id)
    if not p:
        raise HTTPException(404, "product not found")
    return p

@app.get("/summary")
async def inventory_summary():
    # quick, demo-oriented summary
    total_products = len(PRODUCTS)
    total_free = sum(p.stock for p in PRODUCTS.values())
    total_reserved = sum(p.reserved for p in PRODUCTS.values())
    low_stock = sum(1 for p in PRODUCTS.values() if p.stock < 5)
    return {
        "total_products": total_products,
        "total_free_units": total_free,
        "total_reserved_units": total_reserved,
        "low_stock_product_count": low_stock,
    }

@app.get("/availability")
async def availability(product_id: str, qty: int = 1):
    p = PRODUCTS.get(product_id)
    if not p:
        raise HTTPException(404, "product not found")
    return {"product_id": product_id, "requested": qty, "available": p.stock >= qty, "free": p.stock}

# --------- Write ops (reserve → commit / release) ---------
@app.post("/reserve")
async def reserve(req: ReserveReq):
    if req.qty <= 0:
        raise HTTPException(400, "qty must be > 0")
    async with lock:
        p = PRODUCTS.get(req.product_id)
        if not p:
            raise HTTPException(404, "product not found")
        if p.stock < req.qty:
            raise HTTPException(409, "insufficient stock")
        p.stock -= req.qty
        p.reserved += req.qty
        return {"status": "reserved", "product_id": p.id, "qty": req.qty, "free_now": p.stock, "reserved_now": p.reserved}

@app.post("/commit")
async def commit(req: CommitReq):
    if req.qty <= 0:
        raise HTTPException(400, "qty must be > 0")
    async with lock:
        p = PRODUCTS.get(req.product_id)
        if not p:
            raise HTTPException(404, "product not found")
        if p.reserved < req.qty:
            raise HTTPException(409, "commit exceeds reserved")
        p.reserved -= req.qty
        # committed stock leaves the system; nothing to add back
        return {"status": "committed", "product_id": p.id, "qty": req.qty, "order_id": req.order_id}

@app.post("/release")
async def release(req: ReleaseReq):
    if req.qty <= 0:
        raise HTTPException(400, "qty must be > 0")
    async with lock:
        p = PRODUCTS.get(req.product_id)
        if not p:
            raise HTTPException(404, "product not found")
        if p.reserved < req.qty:
            raise HTTPException(409, "release exceeds reserved")
        p.reserved -= req.qty
        p.stock += req.qty
        return {"status": "released", "product_id": p.id, "qty": req.qty, "free_now": p.stock, "reserved_now": p.reserved}
