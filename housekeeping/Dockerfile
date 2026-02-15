ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and pip
RUN apk add --no-cache python3 py3-pip py3-websockets

# Install pip packages
RUN pip3 install --no-cache-dir --break-system-packages \
    fastapi==0.110.0 \
    uvicorn==0.27.1 \
    pyyaml==6.0.1

# Copy files
WORKDIR /app
COPY src/ ./src/
COPY config/ ./config/
COPY www/ ./www/
COPY run.sh /
RUN chmod a+x /run.sh

# Labels
LABEL io.hass.name="Housekeeping"
LABEL io.hass.version="2.0.20"
LABEL io.hass.type="addon"

CMD ["/run.sh"]
