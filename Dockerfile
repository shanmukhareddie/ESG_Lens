FROM python:3.11-slim

WORKDIR /app

# dependencies 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY tests/ tests/
COPY pytest.ini .

CMD ["python", "-m", "pytest", "-q"]