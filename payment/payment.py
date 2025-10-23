from fastapi import FastAPI
import random, time

app = FastAPI()

@app.post("/pay")
async def pay(order_id: str = None, amount: float = 0.0):
    p = random.random()
    if p < 0.10:
        time.sleep(0.05)
        return {"status":"error","reason":"card declined"}, 500
    elif p < 0.6:
        time.sleep(random.uniform(2.5, 6.0))  # slow path
    else:
        time.sleep(random.uniform(0.01, 0.2)) # fast path
    return {"status":"charged","order_id":order_id,"amount":amount}
