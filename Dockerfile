FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py auth.py ./

# wiki.sqlite is mounted at runtime — not baked in
ENV WIKI_DB=/data/wiki.sqlite
ENV PORT=3000

EXPOSE 3000
CMD ["python", "server.py"]
