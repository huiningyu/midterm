import os, time, asyncio, httpx
from fastapi import FastAPI, HTTPException
from starlette.responses import JSONResponse

app = FastAPI()
MODE = os.getenv("MODE", "BROKEN").upper()   # BROKEN or FAILFAST

INVENTORY = "http://inventory:8003"
PAYMENT   = "http://payment:8002/pay"

# tiny metrics for demo
stats = {"requests": 0, "errors": 0, "lat": []}

# BROKEN bits (unbounded queue + leak)
_leaky_bag = []
pending_broken = 0
pending_broken_lock = asyncio.Lock()

# FAIL-FAST bits (bounded queue)
pending = 0
pend_lock = asyncio.Lock()
MAX_QUEUE = 150  # tweak during demo

async def _get_product(product_id: str, timeout=None):
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(f"{INVENTORY}/products/{product_id}")
        if r.status_code != 200:
            raise HTTPException(404, "product not found")
        return r.json()

@app.post("/buy")
async def buy(product_id: str, qty: int = 1):
    t0 = time.time()
    stats["requests"] += 1
    if qty <= 0:
        raise HTTPException(400, "qty must be > 0")

    if MODE == "BROKEN":
        global pending_broken
        async with pending_broken_lock:
            pending_broken += 1
            _leaky_bag.append(bytearray(256 * 1024))  # ~256KB leak per request
        try:
            product = await _get_product(product_id, timeout=None)
            amount = float(product["price"]) * qty

            async with httpx.AsyncClient(timeout=None) as c:
                r = await c.post(f"{INVENTORY}/reserve", json={"product_id": product_id, "qty": qty})
                if r.status_code != 200:
                    stats["errors"] += 1
                    raise HTTPException(r.status_code, "reserve failed")

            async with httpx.AsyncClient(timeout=60.0) as c:  # long timeout -> queue explosion
                pr = await c.post(PAYMENT, json={"order_id": f"ord-{int(time.time()*1000)}", "amount": amount})
                if pr.status_code != 200:
                    await c.post(f"{INVENTORY}/release", json={"product_id": product_id, "qty": qty})
                    stats["errors"] += 1
                    raise HTTPException(502, "payment failure")

            async with httpx.AsyncClient(timeout=None) as c:
                cr = await c.post(f"{INVENTORY}/commit", json={"product_id": product_id, "qty": qty, "order_id": f"ord-{int(time.time()*1000)}"})
                if cr.status_code != 200:
                    await c.post(f"{INVENTORY}/release", json={"product_id": product_id, "qty": qty})
                    stats["errors"] += 1
                    raise HTTPException(500, "commit failure")

            stats["lat"].append(time.time() - t0)
            return {"status": "ok-broken", "product": product_id, "qty": qty}
        finally:
            async with pending_broken_lock:
                pending_broken -= 1

    else:  # FAILFAST
        global pending
        async with pend_lock:
            if pending >= MAX_QUEUE:
                stats["errors"] += 1
                raise HTTPException(503, "server overloaded (fail-fast)")
            pending += 1
        try:
            product = await _get_product(product_id, timeout=2.0)
            amount = float(product["price"]) * qty

            async with httpx.AsyncClient(timeout=2.5) as c:
                r = await c.post(f"{INVENTORY}/reserve", json={"product_id": product_id, "qty": qty})
                if r.status_code != 200:
                    stats["errors"] += 1
                    raise HTTPException(r.status_code, "reserve failed")

            async with httpx.AsyncClient(timeout=5.0) as c:  # still no bulkhead/breaker; just shorter timeout
                pr = await c.post(PAYMENT, json={"order_id": f"ord-{int(time.time()*1000)}", "amount": amount})
                if pr.status_code != 200:
                    await c.post(f"{INVENTORY}/release", json={"product_id": product_id, "qty": qty})
                    stats["errors"] += 1
                    raise HTTPException(502, "payment failure")

            async with httpx.AsyncClient(timeout=2.0) as c:
                cr = await c.post(f"{INVENTORY}/commit", json={"product_id": product_id, "qty": qty, "order_id": f"ord-{int(time.time()*1000)}"})
                if cr.status_code != 200:
                    await c.post(f"{INVENTORY}/release", json={"product_id": product_id, "qty": qty})
                    stats["errors"] += 1
                    raise HTTPException(500, "commit failure")

            stats["lat"].append(time.time() - t0)
            return {"status":"ok", "product": product_id, "qty": qty}
        finally:
            async with pend_lock:
                pending -= 1

@app.get("/metrics")
def metrics():
    p95 = "n/a"
    if stats["lat"]:
        s = sorted(stats["lat"])
        p95 = s[int(0.95*(len(s)-1))]
    out = {"mode": MODE, "requests": stats["requests"], "errors": stats["errors"], "p95_latency_seconds": p95}
    if MODE == "BROKEN":
        out["pending"] = pending_broken
        out["leaky_bag_megabytes"] = round(sum(len(x) for x in _leaky_bag)/1048576, 1)
    else:
        out["pending"] = pending
        out["max_queue"] = MAX_QUEUE
    return out
