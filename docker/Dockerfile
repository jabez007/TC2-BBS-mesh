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

# Install Python dependencies from requirements.txt in the repo (run as root)
WORKDIR /home/mesh/bbs
COPY --from=build /TC2-BBS-mesh/requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Switch to non-root user with explicit UID 1000
RUN adduser -D -u 1000 mesh && chown -R mesh:mesh /home/mesh/bbs
USER mesh

# Copy over app code and examples for initialization
COPY --chown=mesh:mesh --from=build /TC2-BBS-mesh/*.py ./
COPY --chown=mesh:mesh --from=build /TC2-BBS-mesh/example_config.ini ./
COPY --chown=mesh:mesh --from=build /TC2-BBS-mesh/examples/ ./examples/

# Define config volume
VOLUME /home/mesh/bbs/config

# Copy and setup entrypoint script (assumes context is the docker/ directory)
COPY --chown=mesh:mesh configini.sh /usr/local/bin/entrypoint.sh
RUN chmod a+x /usr/local/bin/entrypoint.sh

# Add robust healthcheck with increased timeout
HEALTHCHECK --interval=20s --timeout=20s --start-period=40s --retries=2 \
  CMD /usr/local/bin/healthcheck.py

# Use the entrypoint script to handle config/database paths
ENTRYPOINT [ "/usr/local/bin/entrypoint.sh" ]
