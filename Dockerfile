FROM python:3.11-slim

WORKDIR /app

# dependencies 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY tests/ tests/
COPY pytest.ini app.py ./
# the small CSVs the tests and dashboard read; the PDFs and LLM cache stay out (.dockerignore)
COPY data/ data/

CMD ["python", "-m", "pytest", "-q"]
