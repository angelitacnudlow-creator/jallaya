FROM python:3.12-slim
WORKDIR /app
COPY server.py admin.py build.py bundle.zip ./
RUN python -m zipfile -e bundle.zip . && rm bundle.zip
ENV ALLAYA_HOST=0.0.0.0 PYTHONUNBUFFERED=1
CMD ["python", "server.py"]
