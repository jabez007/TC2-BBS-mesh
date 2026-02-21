# Stage 1: Build stage to clone the repo
FROM debian:12-slim AS build

RUN apt-get update && \
  apt-get install -y \
  git \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Clone the repository
RUN git clone https://github.com/TheCommsChannel/TC2-BBS-mesh.git

####

# Stage 2: App stage using python:3.12-alpine to minimize final image
FROM python:3.12-alpine

# Install healthcheck script (assumes context is the docker/ directory)
COPY healthcheck.py /usr/local/bin/healthcheck.py
RUN chmod a+x /usr/local/bin/healthcheck.py

# Switch to non-root user with explicit UID 1000
RUN adduser -D -u 1000 mesh
USER mesh
RUN mkdir -p /home/mesh/bbs
WORKDIR /home/mesh/bbs

# Install Python dependencies from requirements.txt in the repo
COPY --from=build /TC2-BBS-mesh/requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copy over app code and examples for initialization
COPY --from=build /TC2-BBS-mesh/*.py ./
COPY --from=build /TC2-BBS-mesh/example_config.ini ./
COPY --from=build /TC2-BBS-mesh/examples/ ./examples/

# Define config volume
VOLUME /home/mesh/bbs/config

# Copy and setup entrypoint script (assumes context is the docker/ directory)
COPY --chown=mesh:mesh configini.sh /usr/local/bin/entrypoint.sh
RUN chmod a+x /usr/local/bin/entrypoint.sh

# Add robust healthcheck
HEALTHCHECK --interval=20s --timeout=10s --start-period=40s --retries=2 \
  CMD /usr/local/bin/healthcheck.py

# Use the entrypoint script to handle config/database paths
ENTRYPOINT [ "/usr/local/bin/entrypoint.sh" ]
