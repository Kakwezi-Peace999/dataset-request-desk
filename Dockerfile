FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

# Default command: apply migrations, create seed users/episodes, start the API on :8000.
CMD ["python", "-m", "app.entrypoint"]
