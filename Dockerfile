# bookformatter web — container image for public hosting (Fly.io, Railway,
# Render, or any Docker host). Includes WeasyPrint for full print fidelity
# (running heads, TOC page numbers, recto chapter openers).

FROM python:3.12-slim

# WeasyPrint's system libraries + decent serif fonts for the PDF output.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-dejavu-core fonts-liberation fonts-texgyre fonts-urw-base35 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir weasyprint

WORKDIR /app
COPY pyproject.toml README.md ./
COPY bookformatter ./bookformatter
RUN pip install --no-cache-dir .

# Public-mode defaults: SSRF guard + rate limiting on. Set
# BOOKFORMATTER_BASE_PATH=/book when proxying from a path, and
# BOOKFORMATTER_PASSCODE=... to keep the press private.
ENV BOOKFORMATTER_PUBLIC=1 \
    PORT=8080

EXPOSE 8080
CMD ["bookformatter-web", "--host", "0.0.0.0", "--no-browser"]
