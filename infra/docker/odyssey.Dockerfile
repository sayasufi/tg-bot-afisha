# Odyssey — multithreaded PostgreSQL connection pooler (github.com/yandex/odyssey),
# built from official source. Used as a transaction-pooling layer in front of Postgres
# so the API can scale workers/instances without exhausting max_connections.
FROM ubuntu:22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates cmake make gcc g++ libssl-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Default branch HEAD (pin to a release tag once a build is confirmed green).
RUN git clone --depth 1 https://github.com/yandex/odyssey.git . \
    && mkdir build && cd build \
    && cmake -DCMAKE_BUILD_TYPE=Release .. \
    && make -j"$(nproc)" \
    && cp "$(find /src/build -name odyssey -type f -executable | head -1)" /odyssey

FROM ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /odyssey /usr/local/bin/odyssey
ENTRYPOINT ["/usr/local/bin/odyssey"]
CMD ["/etc/odyssey/odyssey.conf"]
