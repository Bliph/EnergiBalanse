# syntax=docker/dockerfile:1
#
# Single image for the EnergiBalanse "shedder" service (the EV charge controller
# that listens to MQTT and drives the Tesla API). The process is launched by the
# container command in deploy/docker-compose.yml.
#
# Outbound-only: it dials an external MQTT broker and the Tesla REST API and
# does not listen for inbound connections, so the image EXPOSEs no ports.

FROM python:3.14-slim

# Stream logs straight to Docker, skip .pyc clutter, keep pip quiet and cache-free.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Persistent runtime state (Tesla token cache, dynamic control file, power/energy
# buffers, log files) is written here. Mounted as a volume in compose so it
# survives image rebuilds; shedder.py honours STATE_DIR (see apply_env_overrides).
ENV STATE_DIR=/state

WORKDIR /app

# All wheels are prebuilt for cp314 (PyYAML 6.0.3, paho-mqtt, TeslaPy, ...), so no
# C toolchain is needed. If a future dependency lacks a wheel, add an apt-get
# build-essential layer here before the pip install.

# Install deps first (cached unless requirements change), then copy the code.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user. Create /state owned by appuser so that a freshly
# created named volume mounted there inherits writable ownership.
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /state \
    && chown -R appuser:appuser /app /state
USER appuser

# No EXPOSE / no ports — outbound MQTT + Tesla REST only.
# shedder.py needs its own directory on sys.path (it does `from integration...`),
# so run it from there; config is read (read-only) from the baked-in /app/conf.
WORKDIR /app/shedder
CMD ["python", "shedder.py", "--cfg_dir", "/app/conf"]
