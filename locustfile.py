from locust import HttpUser, task, between
import random, requests

CATALOG = []

class Shopper(HttpUser):
    wait_time = between(0.01, 0.1)

    def on_start(self):
        # Preload some product IDs for variety
        try:
            r = requests.get("http://localhost:8003/products?offset=0&limit=200", timeout=3)
            if r.ok:
                global CATALOG
                CATALOG = [p["id"] for p in r.json()]
        except Exception:
            pass

    @task(5)
    def buy(self):
        pid = random.choice(CATALOG) if CATALOG else f"p{random.randint(1,600):04d}"
        qty = random.choice([1,1,1,2])  # mostly 1
        # Gateway buy endpoint expects query params
        self.client.post("/buy", params={"product_id": pid, "qty": qty})
