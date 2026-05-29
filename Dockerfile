FROM python:3.12-slim

WORKDIR /app

COPY app.py .
RUN chmod 644 app.py

CMD ["python", "-u", "app.py"]
