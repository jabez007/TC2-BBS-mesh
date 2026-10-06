# Build from the repository root so the image runs this checkout's code:
#   docker build -f docker/Dockerfile -t tc2-bbs-mesh .
FROM python:3.12-alpine

# Install Python dependencies (run as root)
WORKDIR /home/mesh/bbs
COPY requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Install healthcheck script
COPY docker/healthcheck.py /usr/local/bin/healthcheck.py
RUN chmod a+x /usr/local/bin/healthcheck.py

# Switch to non-root user with explicit UID 1000
RUN adduser -D -u 1000 mesh && \
    mkdir -p /home/mesh/bbs/config && \
    chown -R mesh:mesh /home/mesh/bbs
USER mesh

# Copy over app code and examples for initialization
COPY --chown=mesh:mesh *.py ./
COPY --chown=mesh:mesh example_config.ini ./
COPY --chown=mesh:mesh examples/ ./examples/

# Define config volume
VOLUME /home/mesh/bbs/config

# Copy and setup entrypoint script
COPY --chown=mesh:mesh docker/configini.sh /usr/local/bin/entrypoint.sh
RUN chmod a+x /usr/local/bin/entrypoint.sh

# Add robust healthcheck with increased timeout using exec-form
HEALTHCHECK --interval=20s --timeout=20s --start-period=40s --retries=2 \
  CMD ["/usr/local/bin/healthcheck.py"]

# Use the entrypoint script to handle config/database paths
ENTRYPOINT [ "/usr/local/bin/entrypoint.sh" ]
