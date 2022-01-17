FROM python:3.8-slim-buster

WORKDIR /root

ENV DEBIAN_FRONTEND=noninteractive \
    TERM=xterm

# Install required packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends apt-utils \
    && apt-get upgrade -y \
    && mkdir -p /usr/share/man/man1 \
    && apt-get install -y --no-install-recommends \
        wget less vim \
        build-essential \
        firefox-esr \
        default-jre-headless \
    && apt-get clean && rm -rf /var/lib/apt/lists

# Create sandbox user
RUN useradd sandbox --create-home --shell /bin/bash -G users\
    && su -c "mkdir -p /home/sandbox/.local/bin" sandbox

# Download geckodriver
RUN runuser -l sandbox -c '\
    wget -qO- https://api.github.com/repos/mozilla/geckodriver/releases/latest \
        | python -mjson.tool \
        | grep "browser_download_url.*linux64.tar.gz[^.]" \
        | sed "s/^.*\(http.*tar.gz\).*$/\1/" \
        | xargs wget -qO-\
        | tar -xz -C /home/sandbox/.local/bin/'

# Download selenium server
RUN runuser -l sandbox -c '\
    wget -q -nv -O /home/sandbox/.local/bin/selenium-server-standalone.jar \
         https://selenium-release.storage.googleapis.com/3.141/selenium-server-standalone-3.141.59.jar'

# Download latest firefox
RUN runuser -l sandbox -c '\
    wget -qO- "https://download.mozilla.org/?product=firefox-latest&os=Linux64&lang=en-US" \
        | tar -xj -C /home/sandbox/.local/'

# Copy rc files
COPY --chown=sandbox:sandbox ./etc/.bash_aliases ./etc/.vimrc /home/sandbox/

# Copy requirements file
COPY --chown=sandbox:sandbox requirements.in setup.py /home/sandbox/ml/

# Build requirements
RUN runuser -l sandbox -c '\
    PATH="$HOME/.local/bin:$PATH" &&\
    cd "$HOME/ml" &&\
    pip install --user --upgrade setuptools pip pip-tools && \
    pip-compile --quiet --build-isolation --generate-hashes requirements.in &&\
    pip-sync --user requirements.txt && \
    pip install -e . &&\
    rm -rf $HOME/.cache/pip*'

# Copy application files
COPY --chown=sandbox:sandbox . /home/sandbox/ml

# Work in sandbox users directory
WORKDIR /home/sandbox/ml

# Switch to sandbox user
USER sandbox

# Run supervisor
CMD ["/home/sandbox/.local/bin/supervisord", "-c", "/home/sandbox/ml/etc/supervisord.conf"]
