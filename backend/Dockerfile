FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# scenario_builder/importer ищут planner в /solution (parents[3] от модуля)
COPY --from=solution planner /solution/planner
COPY --from=solution tools/address.py /solution/tools/address.py
COPY --from=solution data/*.json /solution/data/
# Общественный транспорт: фид для RAPTOR и заранее посчитанные профили rRAPTOR
COPY --from=solution data/transit_profiles.bin /solution/data/
COPY --from=solution deploy/ors/files/gtfs.zip /solution/deploy/ors/files/

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
