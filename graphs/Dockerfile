FROM python:3.11

RUN pip install bokeh

COPY donation_graphs /tmp/donation_graphs
RUN pip install /tmp/donation_graphs && rm -r /tmp/donation_graphs

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "donation_graphs"]
