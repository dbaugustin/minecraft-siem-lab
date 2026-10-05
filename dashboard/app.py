"""Entry point for the dashboard.

In Docker, gunicorn imports `app:app` (see Dockerfile). The compose file
publishes it on 127.0.0.1:5000 only.

Run directly with `python app.py` for local use outside Docker; it binds to
127.0.0.1:5000 and nothing else. The dashboard is localhost-only: it is never
exposed on 0.0.0.0, through playit.gg, or any other tunnel. Only the game port
(25565) leaves the box.
"""

import os

HOST = "127.0.0.1"
PORT = 5000


def load_dotenv(path):
    """Minimal .env loader: KEY=VALUE lines, # comments, no $ expansion.

    Only used for `python app.py`; under compose, env_file does this job.
    Existing environment variables win over the file.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from mcdash import create_app  # noqa: E402  (needs the env loaded first)

app = create_app()

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
