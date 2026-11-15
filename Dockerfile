# SPDX-License-Identifier: GPL-3.0-or-later
FROM python:3.13-slim

LABEL org.opencontainers.image.title="simplyusage" \
      org.opencontainers.image.description="Deducts filament from SimplyPrint spools for Bambu Lab prints sent outside SimplyPrint" \
      org.opencontainers.image.source="https://github.com/wendsell/simplyusage" \
      org.opencontainers.image.url="https://wendsell.github.io/simplyusage/" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# The program is shipped as source; LICENSE travels with it.
COPY LICENSE README.md ./
COPY simplyusage ./simplyusage

VOLUME /data
ENTRYPOINT ["python", "-m", "simplyusage"]
