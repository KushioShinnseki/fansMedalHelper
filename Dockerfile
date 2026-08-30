FROM python:3.9-alpine

ENV TZ="Asia/Shanghai"

WORKDIR /app/fansMedalHelper

COPY . /app/fansMedalHelper

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["/bin/sh", "/app/fansMedalHelper/entrypoint.sh"]