FROM python:3.11

RUN pip install bokeh

COPY graphs /tmp/graphs
RUN pip install /tmp/graphs && rm -r /tmp/graphs

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "graphs"]
