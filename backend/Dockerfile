FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Nothing here needs root: a break-in through the app stays an unprivileged user
RUN useradd --system --uid 1001 --no-create-home app
USER app

EXPOSE 8000
CMD ["python", "scripts/docker_start.py"]
