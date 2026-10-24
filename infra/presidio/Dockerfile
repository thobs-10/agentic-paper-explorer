FROM mcr.microsoft.com/presidio-analyzer:2.2.362

USER root
# `spacy download` resolves the model version compatible with the image's installed spaCy.
RUN python -m spacy download en_core_web_sm
COPY nlp-config.yaml /app/presidio_analyzer/conf/nlp-small.yaml
USER 1001

# Read by the analyzer server at startup; WORKERS=1 keeps a single model copy in memory
# (each gunicorn worker loads its own).
ENV NLP_CONF_FILE=presidio_analyzer/conf/nlp-small.yaml \
    WORKERS=1
