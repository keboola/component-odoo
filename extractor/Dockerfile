FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# uncomment the following line should you have any troubles installing certain packages which require C/C++ extensions
# to be compiled during installation, eg. numpy, psycopg2, …
# RUN apt-get update && apt-get install -y build-essential

# add Keboola's default user to correctly create their home dir (used for uv cache)
RUN adduser --uid 1000 --disabled-password keboola

USER 1000:1000

WORKDIR /code/

COPY pyproject.toml .
COPY uv.lock .
COPY packages/ packages/

RUN uv sync --all-groups --frozen

COPY extractor/src/ src/
COPY tests/ tests/
COPY scripts/ scripts/
COPY .flake8 .
COPY deploy.sh .

CMD ["uv", "run", "--no-sync", "python", "-u", "src/extractor_component.py"]
