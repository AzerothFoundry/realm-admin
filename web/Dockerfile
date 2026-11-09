FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY wowgm ./wowgm
RUN groupadd -g 10001 wowweb && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin wowweb && mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 18086
CMD ["uvicorn", "wowgm.app:app", "--host", "0.0.0.0", "--port", "18086", "--workers", "1", "--no-access-log"]
