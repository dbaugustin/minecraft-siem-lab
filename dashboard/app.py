"""Placeholder app so `docker compose up` works. Real dashboard comes next."""
from flask import Flask

app = Flask(__name__)


@app.get("/")
def index():
    return "Minecraft dashboard: scaffold only."
