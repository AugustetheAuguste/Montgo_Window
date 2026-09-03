# Build context is the parent "server" directory, not this project
# directory, because shared/status.py lives outside the project and must
# be baked into the image (see Phase 4 of the task brief).
FROM python:3.12-slim

WORKDIR /app

COPY webcam-montgo/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY webcam-montgo/scripts/ ./scripts/

CMD ["python", "scripts/capture.py"]
