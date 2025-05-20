FROM --platform=$BUILDPLATFORM golang:alpine AS rmapi-builder
WORKDIR /app
RUN apk add --no-cache git
ARG TARGETPLATFORM
RUN case "$TARGETPLATFORM" in \
        'linux/arm/v6') export GOARCH=arm GOARM=6 ;; \
        'linux/arm/v7') export GOARCH=arm GOARM=7 ;; \
        'linux/arm64') export GOARCH=arm64 ;; \
        *) export GOARCH=amd64 ;; \
    esac && \
    git clone https://github.com/ddvk/rmapi && \
    cd rmapi && \
    go build -ldflags='-w -s' .

FROM python:3.13-alpine

# Install deps
WORKDIR /app
COPY --from=rmapi-builder /app/rmapi/rmapi /usr/local/bin/rmapi
COPY requirements.txt ./
# Install Ghostscript + Python deps in one layer
RUN apk add --no-cache ghostscript \
 && pip install --no-cache-dir -r requirements.txt

# Copy script
COPY app.py ./

ENTRYPOINT ["python", "app.py"]
