FROM quay.io/ekimekim/wubloader-downloader:32138bb
COPY girc /tmp/girc
RUN pip install /tmp/girc && rm -r /tmp/girc
COPY . /tmp/archiver
RUN pip install /tmp/archiver && rm -r /tmp/archiver
ENTRYPOINT ["python", "-m", "chat_archiver", "--base-dir", "/mnt"]
