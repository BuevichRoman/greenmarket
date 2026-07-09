from fastapi import FastAPI

app = FastAPI(
    title="GreenMarket Backend",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {"status": "UP"}
