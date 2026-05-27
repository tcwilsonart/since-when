FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY app.py database.py charts.py mailer.py scheduler.py ./

# Data volume — since_when.db lives here
VOLUME ["/data"]
ENV DATA_DIR=/data

EXPOSE 8501

# headless=true suppresses the "open browser" prompt
# gatherUsageStats=false skips the telemetry nag
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
